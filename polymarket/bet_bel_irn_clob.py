#!/usr/bin/env python3
"""
ONE-COMMAND $2 BET via DIRECT POLYMARKET CLOB — Belgium vs. IR Iran (2026-06-21 19:00 UTC).
Self-custody path (treasury 0xcc16…, USDC.e on Polygon). Mirror of polygun/bet_bel_irn.py
but signs + posts the order itself instead of going through PolyGun.

PREREQUISITES (one-time — see polymarket/CLOB_SETUP.md):
  1. Toronto/Canada egress (tunnel ON) — clears Polymarket's US geoblock.
  2. LATEST py-clob-client:  pip install -U "git+https://github.com/Polymarket/py-clob-client.git"
     (the PyPI 0.34.6 build emits an order the server rejects: "invalid order version".)
  3. USDC.e allowance to the SIGNING exchanges (CTF 0x4bFb… + NegRisk-CTF 0xC5d5…):
     python polymarket/approve_usdce_clob.py    (bounded; run by YOU, your shell)

USAGE (run from repo root)
  # live odds for all three sides (NO bet):
  polymarket/.venv/bin/python3 polymarket/bet_bel_irn_clob.py --show
  # DRY RUN a side (build + sign the order, do NOT post — no money):
  polymarket/.venv/bin/python3 polymarket/bet_bel_irn_clob.py belgium
  # FIRE for real ($2) + record as execution_layer=polymarket-clob:
  polymarket/.venv/bin/python3 polymarket/bet_bel_irn_clob.py belgium --go

SIDES: belgium | iran | draw   (each = BUY Yes on that outcome's CLOB token)
"""
import argparse, json, os, ssl, subprocess, sys, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import certifi
from config import get_config

CTX = ssl.create_default_context(cafile=certifi.where())

# CLOB YES tokens, resolved 2026-06-21 from Gamma event fifwc-bel-irn-2026-06-21.
TOKENS = {
    "belgium": "73247571006255574285385183553023235681702880602976519365262465179094676130340",
    "iran":    "107259278816298402654822103861927486042412499982187590917424237525323082866574",
    "draw":    "65206879169809471684171181962606426355936771076631263853333189016369249957120",
}
LABEL = {"belgium": "Belgium", "iran": "IR Iran", "draw": "Draw"}
NEG_RISK = True   # the 3-way game-winner event is neg-risk


def book(token):
    u = f"https://clob.polymarket.com/book?token_id={token}"
    try:
        b = json.load(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "M"}), context=CTX, timeout=20))
    except Exception as e:
        return None
    asks = sorted(b.get("asks", []), key=lambda x: float(x["price"]))
    bids = sorted(b.get("bids", []), key=lambda x: float(x["price"]), reverse=True)
    return {"ask": float(asks[0]["price"]) if asks else None,
            "bid": float(bids[0]["price"]) if bids else None,
            "ask_size": float(asks[0]["size"]) if asks else 0}


def show():
    print("Belgium vs. IR Iran — DIRECT CLOB book (Yes side)\n")
    print(f"  {'SIDE':8} {'bid':>6} {'ask':>6} {'ask_size':>11}")
    for side, tok in TOKENS.items():
        b = book(tok)
        if not b:
            print(f"  {LABEL[side]:8}  (book lookup failed)"); continue
        print(f"  {LABEL[side]:8} {str(b['bid']):>6} {str(b['ask']):>6} {b['ask_size']:>11.0f}")
    print("\n  Bet the side whose true chance (from the live score) exceeds its ask.")
    print("  NB: a near-certain winner often shows ask=None / 0 size = UNBUYABLE at the close.")


def fire(side, amount, go):
    from py_clob_client.clob_types import OrderArgs, OrderType, PartialCreateOrderOptions
    from py_clob_client.order_builder.constants import BUY
    from pm_client import build_client

    tok = TOKENS[side]
    b = book(tok)
    if not b or not b["ask"]:
        print(f"!! {LABEL[side]}: no asks on the book — UNBUYABLE right now (can't market-buy).")
        return 2
    # marketable limit: cross the best ask (round up to the 0.01 tick), size to spend ~amount
    price = min(0.99, (int(b["ask"] * 100 + 0.999)) / 100.0)
    size = round(amount / price, 2)
    print(f"{LABEL[side]} CLOB  ask={b['ask']}  -> BUY {size} @ {price}  (~${price*size:.2f}) neg_risk={NEG_RISK}")

    cfg = get_config(test=False)
    client = build_client(cfg)
    args = OrderArgs(price=price, size=size, side=BUY, token_id=tok)
    print("signing order (neg_risk)…")
    signed = client.create_order(args, PartialCreateOrderOptions(neg_risk=NEG_RISK))
    if not go:
        print("DRY RUN — order built + signed, NOT posted. Re-run with --go to fire.")
        return 0
    print("posting (GTC)…")
    try:
        resp = client.post_order(signed, OrderType.GTC)
    except Exception as e:
        msg = str(e)
        print("POST failed:", msg)
        if "order version" in msg:
            print(">> Upgrade the client (prereq #2): pip install -U "
                  '"git+https://github.com/Polymarket/py-clob-client.git"')
        return 1
    print("CLOB response:", resp)
    txid = (resp or {}).get("transactionsHashes") or (resp or {}).get("orderID")
    print(f"\n   record it:  python polygun/record_trade.py <txhash> --market <id> "
          f"--execution-layer polymarket-clob   (CLOB fills settle on-chain; grab the hash)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="One-command Belgium/Iran/Draw $2 bet via direct CLOB")
    ap.add_argument("side", nargs="?", choices=list(TOKENS))
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--go", action="store_true", help="actually post (default = dry run)")
    ap.add_argument("--amount", type=float, default=2.0)
    a = ap.parse_args()
    if a.show or not a.side:
        show()
        if not a.side:
            print("\nThen: bet_bel_irn_clob.py <belgium|iran|draw> --go")
        return 0
    return fire(a.side, a.amount, a.go)


if __name__ == "__main__":
    sys.exit(main())
