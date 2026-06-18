#!/usr/bin/env python3
"""Bounded USDC.e allowance for Polymarket direct CLOB (run by the USER, their shell).

Approves a SMALL, bounded amount (default 3 USDC.e) — NOT unlimited — to the
Polymarket exchange spenders so a tiny order can settle. Prereq for place_test_trade.py.
Reads POLYMARKET_PRIVATE_KEY from polymarket/.env. Uses a public Polygon RPC.

Usage (from repo root):
    ! python polymarket/approve_usdce.py            # approve 3 USDC.e
    ! python polymarket/approve_usdce.py 2.2        # approve a custom amount
"""
import os, sys
from web3 import Web3
from eth_account import Account

AMOUNT = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0   # USDC.e, bounded
RPC = os.environ.get("APPROVE_RPC", "https://polygon-bor-rpc.publicnode.com")

here = os.path.dirname(os.path.abspath(__file__))
env = {}
for line in open(os.path.join(here, ".env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
pk = env["POLYMARKET_PRIVATE_KEY"]
if not pk.startswith("0x"):
    pk = "0x" + pk

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"headers": {"User-Agent": "Mozilla/5.0"}, "timeout": 30}))
acct = Account.from_key(pk)
addr = acct.address
USDCe = Web3.to_checksum_address("0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
SPENDERS = [  # CTF Exchange, Neg-Risk Exchange, Neg-Risk Adapter (game-winner markets are neg-risk)
    "0xE111180000d2663C0091e4f400237545B87B996B",
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296",
    "0xe2222d279d744050d28e00520010520000310F59",
]
ERC20 = [
    {"constant": False, "inputs": [{"name": "s", "type": "address"}, {"name": "v", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True, "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]
c = w3.eth.contract(address=USDCe, abi=ERC20)
amt = int(AMOUNT * 1_000_000)
gp = int(w3.eth.gas_price * 1.4)
nonce = w3.eth.get_transaction_count(addr)
print(f"signer {addr} | bounded approve {AMOUNT} USDC.e to {len(SPENDERS)} spenders")
pending = []
for sp in SPENDERS:
    sp = Web3.to_checksum_address(sp)
    if c.functions.allowance(addr, sp).call() >= amt:
        print(f"  {sp} already >= {AMOUNT}; skip"); continue
    tx = c.functions.approve(sp, amt).build_transaction(
        {"from": addr, "nonce": nonce, "gas": 80000, "gasPrice": gp, "chainId": 137})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    print(f"  approve {sp} -> {h.hex()}"); pending.append((sp, h)); nonce += 1
for sp, h in pending:
    r = w3.eth.wait_for_transaction_receipt(h, timeout=180)
    print(f"  mined {sp}: status={r.status}")
print("allowances now:", {sp: c.functions.allowance(addr, Web3.to_checksum_address(sp)).call() / 1e6 for sp in SPENDERS})
