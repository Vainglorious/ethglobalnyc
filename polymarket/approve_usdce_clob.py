#!/usr/bin/env python3
"""Bounded USDC.e allowance for DIRECT CLOB fills (run by the USER, your shell).

Approves a small, bounded amount (default 4 USDC.e) to the two exchange contracts
that py-clob-client actually SIGNS orders against on Polygon mainnet (so a matched
order can pull collateral). These differ from the older spenders approve_usdce.py
used. Source of truth: py_clob_client/config.py get_contract_config(137).

  CTF Exchange          0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E  (binary markets)
  NegRisk CTF Exchange  0xC5d563A36AE78145C45a50134d48A1215220f80a  (3-way game markets)

Usage (from repo root):
    ! python polymarket/approve_usdce_clob.py            # approve 4 USDC.e to both
    ! python polymarket/approve_usdce_clob.py 2.5        # custom amount
"""
import os, sys
from web3 import Web3
from eth_account import Account

AMOUNT = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
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
SPENDERS = [
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E",   # CTF Exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a",   # NegRisk CTF Exchange (game markets)
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
print(f"signer {addr} | bounded approve {AMOUNT} USDC.e to the 2 CLOB signing exchanges")
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
