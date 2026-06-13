"""Append a trade to the root predictions.json using HARD on-chain data.

Given a Polygon tx hash, this fetches the receipt + block timestamp, decodes the
outcome shares (ERC1155) and pUSD spent/fee, and appends an enriched record to
../predictions.json. Idempotent: if the tx is already recorded, it does nothing.

    python polygun/record_trade.py <tx_hash> --market 1897048 --side yes \
        --placed-by claude --method auto --event "Qatar vs. Switzerland (Jun 13)" \
        --market-question "Will Switzerland win on 2026-06-13?" --note "Bet 2 (in-play)"
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "predictions.json"
RPC = "https://polygon-bor-rpc.publicnode.com"
HEADERS = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}

SINGLE = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"  # ERC1155 TransferSingle
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # ERC20 Transfer
PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
POLYGUN_ADDR = "e9e32ca24aa1ef725f650b5489281fe621363aa9"


def _tls():
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass


def _rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["result"]


def decode_trade(tx: str) -> dict:
    rc = _rpc("eth_getTransactionReceipt", [tx])
    blk = _rpc("eth_getBlockByNumber", [rc["blockNumber"], False])
    ts = datetime.datetime.fromtimestamp(int(blk["timestamp"], 16), datetime.timezone.utc)
    shares = token = None
    outflows = []
    for lg in rc["logs"]:
        t0 = lg["topics"][0]
        if t0 == SINGLE:
            token = int(lg["data"][2:][:64], 16)
            shares = int(lg["data"][2:][64:128], 16) / 1e6
        elif t0 == TRANSFER and lg["address"].lower() == PUSD:
            frm = "0x" + lg["topics"][1][-40:]
            amt = int(lg["data"], 16) / 1e6
            # only count pUSD LEAVING our wallet (avoids internal split/merge
            # transfers on neg-risk multi-outcome markets). For neg-risk there's
            # usually one all-in outflow (stake+fee); for binary markets two
            # (stake to maker + fee).
            if POLYGUN_ADDR in frm.lower():
                outflows.append(amt)
    outflows.sort(reverse=True)
    spent = outflows[0] if outflows else None
    fee = outflows[1] if len(outflows) > 1 else None
    return {
        "ts_utc": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "filled" if int(rc["status"], 16) == 1 else "failed",
        "block": int(rc["blockNumber"], 16),
        "outcome_token_id": str(token) if token is not None else None,
        "shares": shares,
        "pusd_to_maker": spent,
        "pusd_fee": fee,
        "pusd_total": round((spent or 0) + (fee or 0), 6) if spent is not None else None,
        "avg_price": round(spent / shares, 4) if spent and shares else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tx_hash")
    ap.add_argument("--action", default="buy", choices=["buy", "sell"])
    ap.add_argument("--market", type=int, default=None, help="PolyGun market id")
    ap.add_argument("--side", default="yes")
    ap.add_argument("--placed-by", default="claude")
    ap.add_argument("--method", default="auto", choices=["auto", "manual"])
    ap.add_argument("--event", default=None)
    ap.add_argument("--market-question", default=None)
    ap.add_argument("--outcome", default=None)
    ap.add_argument("--bet-phase", default=None)
    ap.add_argument("--note", default=None)
    args = ap.parse_args()

    _tls()
    data = json.loads(LEDGER.read_text()) if LEDGER.exists() else {"trades": []}
    trades = data.setdefault("trades", [])
    if any(t.get("tx_hash", "").lower() == args.tx_hash.lower() for t in trades):
        print(f"already recorded: {args.tx_hash}")
        return 0

    onchain = decode_trade(args.tx_hash)
    rec = {"id": max([t.get("id", 0) for t in trades], default=0) + 1,
           "ts_utc": onchain["ts_utc"], "action": args.action,
           "placed_by": args.placed_by, "method": args.method}
    if args.bet_phase:
        rec["bet_phase"] = args.bet_phase
    if args.event:
        rec["event"] = args.event
    if args.market_question:
        rec["market_question"] = args.market_question
    if args.outcome:
        rec["outcome"] = args.outcome
    rec["side"] = args.side
    if args.market:
        rec["polygun_market_id"] = args.market
    rec.update({k: onchain[k] for k in ("outcome_token_id", "shares", "avg_price",
                                        "pusd_to_maker", "pusd_fee", "pusd_total",
                                        "status", "tx_hash" if False else "block")})
    rec["tx_hash"] = args.tx_hash
    if args.note:
        rec["note"] = args.note

    trades.append(rec)
    LEDGER.write_text(json.dumps(data, indent=2) + "\n")
    print(f"recorded trade #{rec['id']}: {args.action} {rec.get('shares')} shares @ "
          f"{rec.get('avg_price')} | {args.tx_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
