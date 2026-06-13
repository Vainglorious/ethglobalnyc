"""Place ONE tiny test order against Polymarket to prove we can execute.

SAFETY MODEL (three independent guards):
  1. PM_DRY_RUN defaults to true -> the order is built + printed but NEVER posted.
  2. Even with PM_DRY_RUN=false, you must also pass --execute on the CLI.
  3. The USDC notional is hard-capped by PM_MAX_TEST_USDC; over-cap orders abort.

Polymarket is MAINNET. A real execution spends real USDC.e. Configure the order
in polymarket/.env.test (token id, side, price, size).

    python polymarket/place_test_trade.py             # dry run (safe, default)
    python polymarket/place_test_trade.py --execute   # only fires if PM_DRY_RUN=false
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_config  # noqa: E402
from pm_client import build_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Place a tiny Polymarket test order.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually post the order. Requires PM_DRY_RUN=false in .env.test as well.",
    )
    args = parser.parse_args()

    cfg = get_config(test=True)

    # --- validate the order config before touching the network -----------------
    errors = []
    if not cfg.test_token_id:
        errors.append("PM_TEST_TOKEN_ID is empty (run connectivity_check.py to get one).")
    if cfg.test_side not in {"BUY", "SELL"}:
        errors.append(f"PM_TEST_SIDE must be BUY or SELL, got {cfg.test_side!r}.")
    if not (0.0 < cfg.test_price < 1.0):
        errors.append(f"PM_TEST_PRICE must be in (0,1), got {cfg.test_price}.")
    if cfg.test_size <= 0:
        errors.append(f"PM_TEST_SIZE must be > 0, got {cfg.test_size}.")
    if errors:
        print("Invalid test-trade config:")
        for err in errors:
            print(f"  - {err}")
        return 1

    notional = cfg.test_price * cfg.test_size  # USDC at risk for a BUY
    print("Planned test order:")
    print(f"  token_id: {cfg.test_token_id}")
    print(f"  side:     {cfg.test_side}")
    print(f"  price:    {cfg.test_price}")
    print(f"  size:     {cfg.test_size} shares")
    print(f"  notional: ~{notional:.4f} USDC   (cap: {cfg.max_test_usdc} USDC)")

    if cfg.test_side == "BUY" and notional > cfg.max_test_usdc:
        print(f"\nABORT: notional {notional:.4f} exceeds PM_MAX_TEST_USDC={cfg.max_test_usdc}.")
        return 1

    will_execute = args.execute and not cfg.dry_run
    if not will_execute:
        reason = []
        if cfg.dry_run:
            reason.append("PM_DRY_RUN=true")
        if not args.execute:
            reason.append("--execute not passed")
        print(f"\nDRY RUN ({', '.join(reason)}). No order posted.")
        print("To execute for real: set PM_DRY_RUN=false in polymarket/.env.test AND pass --execute.")
        return 0

    # --- live execution path ---------------------------------------------------
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY, SELL

    client = build_client(cfg)
    side = BUY if cfg.test_side == "BUY" else SELL
    order_args = OrderArgs(
        price=cfg.test_price,
        size=cfg.test_size,
        side=side,
        token_id=cfg.test_token_id,
    )
    print("\nSigning order...")
    signed = client.create_order(order_args)
    print("Posting order (GTC)...")
    response = client.post_order(signed, OrderType.GTC)
    print(f"\nCLOB response: {response}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
