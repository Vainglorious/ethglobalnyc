"""Read-only Polymarket connectivity smoke test.

No private key, no credentials, no orders, no money. It only reads the PUBLIC
CLOB + Gamma endpoints to prove we can reach Polymarket and pull live market data,
and it surfaces a real tradable token_id + current prices you can paste into
.env.test (PM_TEST_TOKEN_ID) for the eventual test trade.

    python polymarket/connectivity_check.py
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_config  # noqa: E402

USER_AGENT = "ColonyPolymarket/0.1 (read-only connectivity check)"


def _get(url: str, *, timeout: int = 15):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _first_tradable_token(gamma_host: str) -> tuple[str, str, str] | None:
    """Find a live tradable outcome via Gamma. Returns (question, outcome, token_id).

    Gamma returns active markets directly (the CLOB /markets first page is mostly
    resolved markets), and each carries its CLOB token ids + outcome labels as
    JSON-encoded strings.
    """
    params = urllib.parse.urlencode(
        {"closed": "false", "active": "true", "limit": "40", "order": "volume", "ascending": "false"}
    )
    markets = _get(f"{gamma_host}/markets?{params}")
    if isinstance(markets, dict):
        markets = markets.get("data", [])
    for market in markets:
        if market.get("acceptingOrders") is False:
            continue
        token_ids = _maybe_json(market.get("clobTokenIds"))
        outcomes = _maybe_json(market.get("outcomes"))
        if not token_ids:
            continue
        outcome = outcomes[0] if outcomes else "?"
        return str(market.get("question", "(no question)")), str(outcome), str(token_ids[0])
    return None


def _maybe_json(value):
    """Gamma encodes list fields as JSON strings; decode defensively."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            return json.loads(value)
        except Exception:  # noqa: BLE001
            return []
    return []


def main() -> int:
    cfg = get_config()
    print(f"CLOB host:  {cfg.clob_host}")
    print(f"Gamma host: {cfg.gamma_host}")
    print(f"Chain id:   {cfg.chain_id}\n")

    ok = True

    # 1) CLOB liveness.
    try:
        server_time = _get(f"{cfg.clob_host}/time")
        print(f"[ok]  CLOB /time -> {server_time}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"[FAIL] CLOB /time: {exc}")

    # 2) Gamma market discovery (human-readable).
    try:
        params = urllib.parse.urlencode({"closed": "false", "limit": "3", "order": "volume"})
        gamma_markets = _get(f"{cfg.gamma_host}/markets?{params}")
        sample = gamma_markets if isinstance(gamma_markets, list) else gamma_markets.get("data", [])
        print(f"[ok]  Gamma /markets -> {len(sample)} markets, e.g.:")
        for market in sample[:3]:
            print(f"        - {market.get('question', '(no question)')}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"[FAIL] Gamma /markets: {exc}")

    # 3) Pick a live tradable token and read its order book / prices on the CLOB.
    try:
        found = _first_tradable_token(cfg.gamma_host)
        if not found:
            print("[warn] No active order-accepting market found.")
        else:
            question, outcome, token_id = found
            print("\n[ok]  Found a tradable outcome token:")
            print(f"        market:   {question}")
            print(f"        outcome:  {outcome}")
            print(f"        token_id: {token_id}")

            midpoint = _get(f"{cfg.clob_host}/midpoint?token_id={token_id}")
            best_bid = _get(f"{cfg.clob_host}/price?token_id={token_id}&side=buy")
            best_ask = _get(f"{cfg.clob_host}/price?token_id={token_id}&side=sell")
            print(f"        midpoint: {midpoint.get('mid')}  "
                  f"best_bid: {best_bid.get('price')}  best_ask: {best_ask.get('price')}")
            print(f"\n  -> Paste this into polymarket/.env.test:  PM_TEST_TOKEN_ID={token_id}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"[FAIL] live price read: {exc}")

    print("\n" + ("Connectivity OK — public Polymarket API reachable." if ok
                   else "Connectivity FAILED — see errors above."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
