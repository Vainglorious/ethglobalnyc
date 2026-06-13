#!/usr/bin/env python3
"""Settle a Colony population state from a run forecast artifact."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Literal

from colony_harness.agent import AntAgent
from colony_harness.population import agent_to_state, load_population_state


Winner = Literal["home", "away"]


def _read_forecasts(run_dir: Path) -> dict[str, dict[str, Any]]:
    path = run_dir / "forecasts.csv"
    if not path.exists():
        raise FileNotFoundError(f"Forecast artifact not found: {path}")
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["agent_id"]: row for row in csv.DictReader(handle)}


def _float(row: dict[str, Any], key: str, fallback: float = 0.0) -> float:
    try:
        return float(row.get(key) or fallback)
    except (TypeError, ValueError):
        return fallback


def _settle_agent(
    agent: AntAgent,
    forecast: dict[str, Any],
    *,
    winner: Winner,
    accuracy_alpha: float,
    payout_multiple: float,
) -> dict[str, Any]:
    actual_home = 1.0 if winner == "home" else 0.0
    home_probability = _float(forecast, "home_probability")
    brier_score = (home_probability - actual_home) ** 2
    forecast_score = 1.0 - brier_score
    old_accuracy = agent.accuracy
    agent.accuracy = round((1.0 - accuracy_alpha) * agent.accuracy + accuracy_alpha * forecast_score, 4)

    side = str(forecast.get("side") or "pass")
    stake = _float(forecast, "stake")
    bankroll_before = agent.bankroll
    bankroll_delta = 0.0
    if side in {"home", "away"}:
        bankroll_delta = stake * payout_multiple if side == winner else -stake
        agent.bankroll = round(max(0.0, agent.bankroll + bankroll_delta), 4)

    settlement = {
        "winner": winner,
        "side": side,
        "stake": round(stake, 4),
        "home_probability": round(home_probability, 4),
        "forecast_score": round(forecast_score, 4),
        "accuracy_before": round(old_accuracy, 4),
        "accuracy_after": agent.accuracy,
        "bankroll_before": round(bankroll_before, 4),
        "bankroll_delta": round(bankroll_delta, 4),
        "bankroll_after": agent.bankroll,
        "correct_side": side == winner if side in {"home", "away"} else None,
    }
    agent.last_settlement = settlement
    return settlement


def settle_population(
    agents: list[AntAgent],
    *,
    forecasts: dict[str, dict[str, Any]],
    winner: Winner,
    accuracy_alpha: float,
    payout_multiple: float,
) -> tuple[list[AntAgent], dict[str, Any]]:
    settlements = []
    for agent in agents:
        forecast = forecasts.get(agent.agent_id)
        if not forecast:
            continue
        settlements.append(
            {
                "agent_id": agent.agent_id,
                "genome_id": agent.genome_id,
                **_settle_agent(
                    agent,
                    forecast,
                    winner=winner,
                    accuracy_alpha=accuracy_alpha,
                    payout_multiple=payout_multiple,
                ),
            }
        )

    bets = [row for row in settlements if row["side"] in {"home", "away"}]
    correct_bets = [row for row in bets if row["correct_side"]]
    summary = {
        "winner": winner,
        "agents_settled": len(settlements),
        "bets": len(bets),
        "correct_bets": len(correct_bets),
        "accuracy_alpha": accuracy_alpha,
        "payout_multiple": payout_multiple,
        "total_bankroll_delta": round(sum(row["bankroll_delta"] for row in settlements), 4),
        "avg_forecast_score": round(
            sum(row["forecast_score"] for row in settlements) / len(settlements),
            4,
        )
        if settlements
        else 0.0,
        "settlements": settlements,
    }
    return agents, summary


def _population_payload(agents: list[AntAgent], *, seed: int, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "seed": seed,
        "note": "settled population state",
        "population_size": len(agents),
        "settlement": summary,
        "agents": [agent_to_state(agent) for agent in agents],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population-state", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--winner", choices=["home", "away"], required=True)
    parser.add_argument("--accuracy-alpha", type=float, default=0.2)
    parser.add_argument("--payout-multiple", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 0.0 <= args.accuracy_alpha <= 1.0:
        raise SystemExit("--accuracy-alpha must be in [0, 1]")
    if args.payout_multiple < 0.0:
        raise SystemExit("--payout-multiple must be non-negative")

    agents = load_population_state(args.population_state)
    forecasts = _read_forecasts(args.run_dir)
    settled_agents, summary = settle_population(
        agents,
        forecasts=forecasts,
        winner=args.winner,
        accuracy_alpha=args.accuracy_alpha,
        payout_multiple=args.payout_multiple,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(_population_payload(settled_agents, seed=args.seed, summary=summary), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        "Settled population: "
        f"winner={summary['winner']} agents={summary['agents_settled']} "
        f"bets={summary['bets']} correct_bets={summary['correct_bets']} "
        f"bankroll_delta={summary['total_bankroll_delta']} out={args.out}"
    )


if __name__ == "__main__":
    main()
