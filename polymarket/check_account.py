"""Inspect the trading account: address, derived API creds, USDC balance + allowances.

Read-only by default. Pass --approve to send the one-time on-chain allowance
transaction that lets the Polymarket Exchange spend your USDC.e (costs a little
MATIC/POL in gas). You need this allowance before a BUY order can settle.

    python polymarket/check_account.py            # read-only
    python polymarket/check_account.py --approve  # set USDC (collateral) allowance
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_config  # noqa: E402
from pm_client import build_client  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Polymarket trading account.")
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Send the on-chain USDC (collateral) allowance approval. Costs gas.",
    )
    args = parser.parse_args()

    cfg = get_config()
    client = build_client(cfg)

    from py_clob_client.clob_types import BalanceAllowanceParams, AssetType

    print(f"Trading address: {client.get_address()}")
    print(f"Signature type:  {cfg.signature_type}"
          + (f"  funder: {cfg.funder_address}" if cfg.signature_type != 0 else ""))

    if not cfg.has_api_creds:
        creds = client.create_or_derive_api_creds()
        print("\nDerived L2 API credentials (paste into polymarket/.env to reuse):")
        print(f"  POLYMARKET_API_KEY={creds.api_key}")
        print(f"  POLYMARKET_API_SECRET={creds.api_secret}")
        print(f"  POLYMARKET_API_PASSPHRASE={creds.api_passphrase}")

    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=cfg.signature_type)

    if args.approve:
        print("\nSending USDC (collateral) allowance approval transaction...")
        result = client.update_balance_allowance(params)
        print(f"  result: {result}")

    balance = client.get_balance_allowance(params)
    print("\nUSDC.e balance / allowance (raw, 6 decimals):")
    print(f"  {balance}")
    print("\n  (balance is in micro-USDC: divide by 1_000_000 for USDC.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
