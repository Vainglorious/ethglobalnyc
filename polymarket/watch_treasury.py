"""Watch the treasury wallet for incoming USDC and report when it arrives.

Polls the on-chain balance of the treasury for both USDC.e (bridged) and native
USDC, and exits as soon as either increases above the starting baseline (i.e. a
withdrawal/transfer lands). Useful for waiting on a PolyGun withdrawal.

    python polymarket/watch_treasury.py
    python polymarket/watch_treasury.py --address 0x.. --interval 20 --max-minutes 40
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import ensure_tls_certs  # noqa: E402

RPC = "https://polygon-bor-rpc.publicnode.com"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0", "Accept": "application/json"}
TOKENS = {
    "USDC.e": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
    "USDC.native": "0x3c499c542cEF5E3811e1192ce70d8cc03d5c3359",
}
DEFAULT_TREASURY = "0xcc16bEC342794f35a32d4Ba2c76BF9D759C131eB"


def _rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())["result"]


def _balances(addr: str) -> dict[str, float]:
    padded = addr[2:].lower().rjust(64, "0")
    out = {}
    for label, contract in TOKENS.items():
        raw = _rpc("eth_call", [{"to": contract, "data": "0x70a08231" + padded}, "latest"])
        out[label] = int(raw, 16) / 1e6
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch a wallet for incoming USDC.")
    parser.add_argument("--address", default=DEFAULT_TREASURY)
    parser.add_argument("--interval", type=int, default=20, help="seconds between polls")
    parser.add_argument("--max-minutes", type=int, default=40, help="give up after this long")
    args = parser.parse_args()

    ensure_tls_certs()
    addr = args.address

    base = _balances(addr)
    print(f"Watching {addr}", flush=True)
    print(f"  baseline: USDC.e={base['USDC.e']:.6f}  native={base['USDC.native']:.6f}", flush=True)

    deadline = time.monotonic() + args.max_minutes * 60
    polls = 0
    while time.monotonic() < deadline:
        time.sleep(args.interval)
        polls += 1
        try:
            now = _balances(addr)
        except Exception as exc:  # noqa: BLE001
            print(f"  [poll {polls}] rpc error: {exc}", flush=True)
            continue

        d_bridged = now["USDC.e"] - base["USDC.e"]
        d_native = now["USDC.native"] - base["USDC.native"]
        if d_bridged > 1e-6 or d_native > 1e-6:
            print("\n*** FUNDS ARRIVED ***", flush=True)
            if d_bridged > 1e-6:
                print(f"  +{d_bridged:.6f} USDC.e   -> now {now['USDC.e']:.6f}", flush=True)
            if d_native > 1e-6:
                print(f"  +{d_native:.6f} native USDC -> now {now['USDC.native']:.6f}", flush=True)
            return 0

        if polls % 5 == 0:
            print(f"  [poll {polls}] no change yet "
                  f"(USDC.e={now['USDC.e']:.4f} native={now['USDC.native']:.4f})", flush=True)

    print(f"\nTimed out after {args.max_minutes} min with no incoming funds.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
