"""Execute a tiny set of Colony debate-driven Polymarket bets.

The Colony harness already emits `forecasts.csv` after the debate. This adapter
turns those forecasts into a conservative trade plan:

1. read the agents' post-debate probabilities;
2. refresh or accept the latest Polymarket ask prices;
3. pick the best live edge per eligible agent;
4. post at most a few capped BUY orders.

Safety model:
  - dry-run is the default via PM_DRY_RUN=true;
  - live posting also requires --execute;
  - total notional is capped by PM_MAX_TEST_USDC unless overridden lower/higher
    on the CLI;
  - only BUY orders are produced.

Example:
    python polymarket/execute_colony_bets.py \
      --run-dir colony/runs/20260613_052623_round_world_cup_demo_001 \
      --home-token-id 123 \
      --away-token-id 456 \
      --home-ask 0.61 \
      --away-ask 0.42
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, get_config  # noqa: E402
from pm_client import build_client  # noqa: E402

USER_AGENT = "ColonyPolymarket/0.1 (debate trade executor)"


@dataclass(frozen=True)
class ForecastRow:
    agent_id: str
    genome_id: str
    home_probability: float
    side: str
    stake: float
    bankroll: float
    decision_reason: str


@dataclass(frozen=True)
class OutcomeQuote:
    label: str
    token_id: str
    ask: float


@dataclass(frozen=True)
class PlannedOrder:
    agent_id: str
    genome_id: str
    outcome: str
    token_id: str
    probability: float
    ask: float
    live_edge: float
    notional_usdc: float
    size: float
    limit_price: float
    forecast_side: str
    reason: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute Colony debate-driven Polymarket bets.")
    parser.add_argument("--run-dir", default="", help="Colony run directory containing forecasts.csv.")
    parser.add_argument("--forecasts", default="", help="Explicit forecasts.csv path. Overrides --run-dir.")
    parser.add_argument("--home-token-id", required=True, help="Polymarket CLOB token id for the home/YES outcome.")
    parser.add_argument("--away-token-id", required=True, help="Polymarket CLOB token id for the away/NO outcome.")
    parser.add_argument("--home-ask", type=float, default=None, help="Home token ask price. If omitted, fetch live CLOB ask.")
    parser.add_argument("--away-ask", type=float, default=None, help="Away token ask price. If omitted, fetch live CLOB ask.")
    parser.add_argument("--max-agents", type=int, default=3, help="Maximum agents allowed to place real orders.")
    parser.add_argument("--min-live-edge", type=float, default=0.0, help="Minimum live edge after current pricing.")
    parser.add_argument("--max-total-usdc", type=float, default=None, help="Total USDC cap. Defaults to PM_MAX_TEST_USDC.")
    parser.add_argument("--max-per-agent-usdc", type=float, default=None, help="Per-agent USDC cap.")
    parser.add_argument(
        "--include-passes",
        action="store_true",
        help="Allow agents that originally passed to become eligible if live pricing creates an edge.",
    )
    parser.add_argument(
        "--lock-forecast-side",
        action="store_true",
        help="Keep each agent on its original forecast side instead of choosing the best live-priced side.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually post orders. Requires PM_DRY_RUN=false in polymarket/.env.test too.",
    )
    parser.add_argument("--plan-out", default="", help="Optional JSON path for the generated trade plan.")
    args = parser.parse_args()

    if args.max_agents < 1:
        raise SystemExit("--max-agents must be >= 1")
    if args.min_live_edge < 0:
        raise SystemExit("--min-live-edge must be >= 0")

    cfg = get_config(test=True)
    forecasts_path = _resolve_forecasts_path(run_dir=args.run_dir, forecasts=args.forecasts)
    forecasts = _read_forecasts(forecasts_path)
    quotes = {
        "home": OutcomeQuote(
            label="home",
            token_id=args.home_token_id,
            ask=_resolve_ask(cfg, args.home_token_id, args.home_ask),
        ),
        "away": OutcomeQuote(
            label="away",
            token_id=args.away_token_id,
            ask=_resolve_ask(cfg, args.away_token_id, args.away_ask),
        ),
    }
    total_cap = cfg.max_test_usdc if args.max_total_usdc is None else args.max_total_usdc
    per_agent_cap = (total_cap / args.max_agents) if args.max_per_agent_usdc is None else args.max_per_agent_usdc
    if total_cap <= 0 or per_agent_cap <= 0:
        raise SystemExit("USDC caps must be positive.")

    orders = build_trade_plan(
        forecasts,
        quotes=quotes,
        max_agents=args.max_agents,
        min_live_edge=args.min_live_edge,
        max_total_usdc=total_cap,
        max_per_agent_usdc=per_agent_cap,
        include_passes=args.include_passes,
        lock_forecast_side=args.lock_forecast_side,
    )

    plan = {
        "source_forecasts": str(forecasts_path),
        "dry_run": cfg.dry_run,
        "execute_requested": args.execute,
        "max_agents": args.max_agents,
        "max_total_usdc": round(total_cap, 6),
        "max_per_agent_usdc": round(per_agent_cap, 6),
        "min_live_edge": args.min_live_edge,
        "quotes": {side: asdict(quote) for side, quote in quotes.items()},
        "orders": [asdict(order) for order in orders],
    }
    if args.plan_out:
        plan_path = Path(args.plan_out)
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    _print_plan(plan)

    will_execute = args.execute and not cfg.dry_run
    if not will_execute:
        reasons = []
        if cfg.dry_run:
            reasons.append("PM_DRY_RUN=true")
        if not args.execute:
            reasons.append("--execute not passed")
        print(f"\nDRY RUN ({', '.join(reasons)}). No orders posted.")
        print("To execute for real: set PM_DRY_RUN=false in polymarket/.env.test AND pass --execute.")
        return 0

    if not orders:
        print("\nNo eligible orders to post.")
        return 0

    _post_orders(cfg, orders)
    return 0


def build_trade_plan(
    forecasts: list[ForecastRow],
    *,
    quotes: dict[str, OutcomeQuote],
    max_agents: int,
    min_live_edge: float,
    max_total_usdc: float,
    max_per_agent_usdc: float,
    include_passes: bool,
    lock_forecast_side: bool,
) -> list[PlannedOrder]:
    candidates: list[PlannedOrder] = []
    for forecast in forecasts:
        if forecast.side == "pass" and not include_passes:
            continue
        quote = _quote_for_forecast(forecast, quotes, lock_forecast_side=lock_forecast_side)
        probability = forecast.home_probability if quote.label == "home" else 1.0 - forecast.home_probability
        live_edge = probability - quote.ask
        if live_edge < min_live_edge:
            continue
        notional = min(forecast.stake, max_per_agent_usdc)
        if notional <= 0:
            continue
        candidates.append(
            _planned_order(
                forecast=forecast,
                quote=quote,
                probability=probability,
                live_edge=live_edge,
                notional_usdc=notional,
            )
        )

    candidates.sort(key=lambda order: (order.live_edge, order.notional_usdc), reverse=True)
    selected: list[PlannedOrder] = []
    remaining = max_total_usdc
    for candidate in candidates:
        if len(selected) >= max_agents or remaining <= 0:
            break
        notional = min(candidate.notional_usdc, remaining)
        if notional <= 0:
            continue
        selected.append(
            _planned_order(
                forecast=ForecastRow(
                    agent_id=candidate.agent_id,
                    genome_id=candidate.genome_id,
                    home_probability=candidate.probability if candidate.outcome == "home" else 1.0 - candidate.probability,
                    side=candidate.forecast_side,
                    stake=notional,
                    bankroll=0.0,
                    decision_reason=candidate.reason,
                ),
                quote=OutcomeQuote(candidate.outcome, candidate.token_id, candidate.ask),
                probability=candidate.probability,
                live_edge=candidate.live_edge,
                notional_usdc=notional,
            )
        )
        remaining = round(remaining - notional, 6)
    return selected


def _quote_for_forecast(
    forecast: ForecastRow,
    quotes: dict[str, OutcomeQuote],
    *,
    lock_forecast_side: bool,
) -> OutcomeQuote:
    if lock_forecast_side and forecast.side in {"home", "away"}:
        return quotes[forecast.side]
    home_probability = forecast.home_probability
    home_edge = home_probability - quotes["home"].ask
    away_edge = (1.0 - home_probability) - quotes["away"].ask
    return quotes["home"] if home_edge >= away_edge else quotes["away"]


def _planned_order(
    *,
    forecast: ForecastRow,
    quote: OutcomeQuote,
    probability: float,
    live_edge: float,
    notional_usdc: float,
) -> PlannedOrder:
    limit_price = _ceil_price(quote.ask)
    size = 0.0 if limit_price <= 0 else notional_usdc / limit_price
    return PlannedOrder(
        agent_id=forecast.agent_id,
        genome_id=forecast.genome_id,
        outcome=quote.label,
        token_id=quote.token_id,
        probability=round(probability, 4),
        ask=round(quote.ask, 4),
        live_edge=round(live_edge, 4),
        notional_usdc=round(notional_usdc, 6),
        size=round(size, 6),
        limit_price=limit_price,
        forecast_side=forecast.side,
        reason=forecast.decision_reason,
    )


def _post_orders(cfg: Config, orders: list[PlannedOrder]) -> None:
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY

    client = build_client(cfg)
    for order in orders:
        order_args = OrderArgs(
            price=order.limit_price,
            size=order.size,
            side=BUY,
            token_id=order.token_id,
        )
        print(f"\nSigning {order.agent_id} {order.outcome} BUY ~{order.notional_usdc:.4f} USDC...")
        signed = client.create_order(order_args)
        print("Posting order (GTC)...")
        response = client.post_order(signed, OrderType.GTC)
        print(f"CLOB response for {order.agent_id}: {response}")


def _resolve_forecasts_path(*, run_dir: str, forecasts: str) -> Path:
    if forecasts:
        path = Path(forecasts)
    elif run_dir:
        path = Path(run_dir) / "forecasts.csv"
    else:
        raise SystemExit("Pass --run-dir or --forecasts.")
    if not path.exists():
        raise SystemExit(f"Forecasts file not found: {path}")
    return path


def _read_forecasts(path: Path) -> list[ForecastRow]:
    rows: list[ForecastRow] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(
                ForecastRow(
                    agent_id=str(row.get("agent_id") or ""),
                    genome_id=str(row.get("genome_id") or ""),
                    home_probability=_float(row, "home_probability"),
                    side=str(row.get("side") or "pass"),
                    stake=_float(row, "stake"),
                    bankroll=_float(row, "bankroll"),
                    decision_reason=str(row.get("decision_reason") or ""),
                )
            )
    return rows


def _resolve_ask(cfg: Config, token_id: str, provided: float | None) -> float:
    if provided is not None:
        return _validate_price(provided, label=f"provided ask for {token_id}")
    params = urllib.parse.urlencode({"token_id": token_id, "side": "sell"})
    data = _get_json(f"{cfg.clob_host}/price?{params}")
    return _validate_price(float(data["price"]), label=f"live ask for {token_id}")


def _get_json(url: str, *, timeout: int = 15) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}")
    return payload


def _validate_price(value: float, *, label: str) -> float:
    if not 0.0 < value < 1.0:
        raise SystemExit(f"{label} must be between 0 and 1, got {value}.")
    return value


def _ceil_price(value: float, *, tick: float = 0.001) -> float:
    return round(min(0.999, math.ceil(value / tick) * tick), 3)


def _float(row: dict, key: str) -> float:
    raw = row.get(key)
    if raw is None or str(raw).strip() == "":
        return 0.0
    return float(raw)


def _print_plan(plan: dict[str, Any]) -> None:
    print("Colony Polymarket trade plan")
    print(f"  forecasts:       {plan['source_forecasts']}")
    print(f"  max agents:      {plan['max_agents']}")
    print(f"  max total USDC:  {plan['max_total_usdc']}")
    print(f"  min live edge:   {plan['min_live_edge']:.2%}")
    print("  quotes:")
    for side, quote in plan["quotes"].items():
        print(f"    {side}: ask={quote['ask']:.4f} token_id={quote['token_id']}")
    if not plan["orders"]:
        print("  orders: none")
        return
    print("  orders:")
    for order in plan["orders"]:
        print(
            "    "
            f"{order['agent_id']} -> BUY {order['outcome']} "
            f"edge={order['live_edge']:+.2%} "
            f"p={order['probability']:.2%} ask={order['ask']:.2%} "
            f"notional={order['notional_usdc']:.4f} size={order['size']:.4f}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
