"""Swap native USDC -> USDC.e on Polygon (Uniswap v3) to get Polymarket collateral.

The treasury was funded with native USDC, but Polymarket settles in USDC.e. This
swaps a small amount via the 0.01% USDC/USDC.e pool. Dry-run by default; pass
--execute to send real transactions.

    python polymarket/swap_to_usdce.py --amount 6            # dry run
    python polymarket/swap_to_usdce.py --amount 6 --execute  # real swap
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_config, ensure_tls_certs  # noqa: E402

USDC_NATIVE = "0x3c499c542cEF5E3811e1192ce70d8cc03d5c3359"
USDC_E = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ROUTER = "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"  # Uniswap SwapRouter02 (Polygon)
FEE = 100  # 0.01% tier — deepest USDC/USDC.e pool
RPCS = [
    "https://polygon-bor-rpc.publicnode.com",
    "https://polygon.drpc.org",
    "https://polygon-rpc.com",
]

ERC20_ABI = [
    {"name": "approve", "type": "function", "stateMutability": "nonpayable",
     "inputs": [{"name": "s", "type": "address"}, {"name": "a", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"name": "allowance", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"name": "balanceOf", "type": "function", "stateMutability": "view",
     "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
]
ROUTER_ABI = [{"name": "exactInputSingle", "type": "function", "stateMutability": "payable", "inputs": [
    {"name": "params", "type": "tuple", "components": [
        {"name": "tokenIn", "type": "address"}, {"name": "tokenOut", "type": "address"},
        {"name": "fee", "type": "uint24"}, {"name": "recipient", "type": "address"},
        {"name": "amountIn", "type": "uint256"}, {"name": "amountOutMinimum", "type": "uint256"},
        {"name": "sqrtPriceLimitX96", "type": "uint160"}]}],
    "outputs": [{"name": "amountOut", "type": "uint256"}]}]


def _raw(signed):
    return getattr(signed, "raw_transaction", None) or signed.rawTransaction


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--amount", type=float, default=6.0, help="USDC to swap")
    ap.add_argument("--slippage-bps", type=int, default=100, help="max slippage in bps (100=1%)")
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    ensure_tls_certs()
    cfg = get_config()
    if not cfg.private_key:
        raise SystemExit("POLYMARKET_PRIVATE_KEY not set")

    from web3 import Web3

    w3 = None
    for url in [cfg.rpc_url] + RPCS:
        try:
            cand = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 30, "headers": {"User-Agent": "Mozilla/5.0"}}))
            if cand.is_connected() and cand.eth.chain_id == 137:
                w3 = cand
                print(f"RPC: {url}")
                break
        except Exception:
            continue
    if w3 is None:
        raise SystemExit("No working Polygon RPC (set POLYGON_RPC_URL to a real endpoint).")

    acct = w3.eth.account.from_key(cfg.private_key)
    amount_in = int(round(args.amount * 1e6))
    min_out = amount_in * (10000 - args.slippage_bps) // 10000

    native = w3.eth.contract(address=Web3.to_checksum_address(USDC_NATIVE), abi=ERC20_ABI)
    usdce = w3.eth.contract(address=Web3.to_checksum_address(USDC_E), abi=ERC20_ABI)
    router = w3.eth.contract(address=Web3.to_checksum_address(ROUTER), abi=ROUTER_ABI)

    bal_native = native.functions.balanceOf(acct.address).call() / 1e6
    bal_usdce = usdce.functions.balanceOf(acct.address).call() / 1e6
    pol = w3.eth.get_balance(acct.address) / 1e18
    print(f"Wallet {acct.address}")
    print(f"  before: native USDC={bal_native:.4f}  USDC.e={bal_usdce:.4f}  POL={pol:.4f}")
    print(f"  plan: swap {args.amount} native USDC -> USDC.e (min out {min_out/1e6:.4f}, {args.slippage_bps}bps slip)")

    if not args.execute:
        print("\nDRY RUN — no transactions sent. Re-run with --execute.")
        return 0

    if bal_native < args.amount:
        raise SystemExit(f"insufficient native USDC ({bal_native} < {args.amount})")

    gas_price = int(w3.eth.gas_price * 1.3)
    nonce = w3.eth.get_transaction_count(acct.address)

    # 1) approve router for native USDC (if needed)
    allowance = native.functions.allowance(acct.address, Web3.to_checksum_address(ROUTER)).call()
    if allowance < amount_in:
        print("\n[1/2] approving native USDC to router...")
        tx = native.functions.approve(Web3.to_checksum_address(ROUTER), amount_in).build_transaction(
            {"from": acct.address, "nonce": nonce, "gas": 80000, "gasPrice": gas_price, "chainId": 137})
        signed = w3.eth.account.sign_transaction(tx, cfg.private_key)
        h = w3.eth.send_raw_transaction(_raw(signed))
        print(f"  approve tx: {h.hex()}")
        rc = w3.eth.wait_for_transaction_receipt(h, timeout=180)
        print(f"  approve status: {rc.status}")
        nonce += 1
    else:
        print("\n[1/2] approval already sufficient.")

    # 2) swap
    print("[2/2] swapping...")
    params = (Web3.to_checksum_address(USDC_NATIVE), Web3.to_checksum_address(USDC_E), FEE,
              acct.address, amount_in, min_out, 0)
    swap_fn = router.functions.exactInputSingle(params)
    try:
        gas_est = int(swap_fn.estimate_gas({"from": acct.address}) * 1.3)
    except Exception as exc:  # noqa: BLE001
        print(f"  gas estimate failed ({exc}); using 300000")
        gas_est = 300000
    tx = swap_fn.build_transaction(
        {"from": acct.address, "nonce": nonce, "gas": gas_est, "gasPrice": gas_price, "chainId": 137})
    signed = w3.eth.account.sign_transaction(tx, cfg.private_key)
    h = w3.eth.send_raw_transaction(_raw(signed))
    print(f"  swap tx: {h.hex()}")
    rc = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    print(f"  swap status: {rc.status}")

    after = usdce.functions.balanceOf(acct.address).call() / 1e6
    print(f"\n  after: USDC.e={after:.4f}  (gained {after - bal_usdce:.4f})")
    return 0 if rc.status == 1 else 1


if __name__ == "__main__":
    raise SystemExit(main())
