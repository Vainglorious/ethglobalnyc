#!/usr/bin/env python3
"""
ONE-COMMAND $2 BET — Belgium vs. IR Iran  (World Cup, Group G, 2026-06-21 19:00 UTC).
Built for last-~5-minutes execution: pick a side, run one command, it fires + records.

USAGE (run from repo root)
  # 1) See live odds for all three sides (NO bet) — use this to choose:
  polygun/.venv/bin/python3 polygun/bet_bel_irn.py --show

  # 2) DRY RUN a side (navigates the PolyGun bot, stops BEFORE spending):
  polygun/.venv/bin/python3 polygun/bet_bel_irn.py belgium

  # 3) FIRE for real ($2) and record to predictions.json:
  polygun/.venv/bin/python3 polygun/bet_bel_irn.py belgium --go
  polygun/.venv/bin/python3 polygun/bet_bel_irn.py iran   --go
  polygun/.venv/bin/python3 polygun/bet_bel_irn.py draw   --go --amount 2

SIDES: belgium | iran | draw   (each is "Buy Yes" on that outcome's market)
SAFETY: without --go it does a dry run (no money). --go is required to spend.
"""
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))          # polygun/
REPO = os.path.dirname(HERE)
PG_PY = os.path.join(HERE, ".venv", "bin", "python3")      # telethon venv (pg.py)
PM_PY = os.path.join(REPO, "polymarket", ".venv", "bin", "python3")  # has certifi

# Resolved 2026-06-21 from Gamma event fifwc-bel-irn-2026-06-21 ("Belgium vs. IR Iran").
MARKETS = {
    "belgium": 1897168,   # Will Belgium win on 2026-06-21?
    "iran":    1897173,   # Will IR Iran win on 2026-06-21?
    "draw":    1897171,   # Will Belgium vs. IR Iran end in a draw?
}
LABEL = {"belgium": "Belgium", "iran": "IR Iran", "draw": "Draw"}


def curl_json(url):
    out = subprocess.run(["curl", "-s", "--max-time", "20", "-A", "Mozilla/5.0", url],
                         capture_output=True, text=True).stdout
    try:
        return json.loads(out)
    except Exception:
        return None


def market_state(mid):
    """Return (closed, bestBid, bestAsk) for a Gamma market id."""
    m = curl_json(f"https://gamma-api.polymarket.com/markets/{mid}")
    if isinstance(m, list):
        m = m[0] if m else {}
    if not m:
        return None
    return (m.get("closed"), m.get("bestBid"), m.get("bestAsk"))


def show():
    print("Belgium vs. IR Iran — live market (Yes = that outcome happens)\n")
    print(f"  {'SIDE':8} {'market':9} {'bid':>6} {'ask':>6}  status")
    for side, mid in MARKETS.items():
        st = market_state(mid)
        if not st:
            print(f"  {LABEL[side]:8} {mid:<9}   (lookup failed)"); continue
        closed, bid, ask = st
        tag = "CLOSED/RESOLVED" if closed else "open"
        print(f"  {LABEL[side]:8} {mid:<9} {str(bid):>6} {str(ask):>6}  {tag}")
    print("\n  Read it like this: the 'ask' is roughly the implied probability + what you")
    print("  pay per share. Bet the side whose TRUE chance (from the live score/state) you")
    print("  think is HIGHER than its ask. See the cheat-sheet in the script header / notes.")


def certifi_path():
    try:
        out = subprocess.run([PM_PY, "-c", "import certifi;print(certifi.where())"],
                             capture_output=True, text=True).stdout.strip()
        return out or None
    except Exception:
        return None


def fire(side, amount, go):
    mid = MARKETS[side]
    st = market_state(mid)
    if st:
        closed, bid, ask = st
        if closed:
            print(f"!! {LABEL[side]} market {mid} is CLOSED/RESOLVED — not betting.")
            return 2
        print(f"{LABEL[side]} (market {mid})  live ask={ask} bid={bid}  -> ${amount} buy")
    # Build the pg.py buy command. --confirm makes it actually fire; without it pg.py
    # safely stops before sending the amount (dry run).
    cmd = [PG_PY, "pg.py", "buy", "--market", str(mid), "--side", "yes",
           "--amount", str(amount)]
    if go:
        cmd.append("--confirm")
    print(f"\n>>> {'FIRING' if go else 'DRY RUN'}: {' '.join(cmd)}\n")
    # Stream pg.py output live (so you see navigation + fill in real time) while
    # also capturing it to pull the tx hash out afterward.
    proc = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1)
    captured = []
    for line in proc.stdout:
        sys.stdout.write(line); sys.stdout.flush()
        captured.append(line)
    proc.wait()
    full = "".join(captured)
    if "Server closed the connection" in full or "VERIFICATION" in full:
        print("\n!! Telegram connection wobble. If NOTHING filled, just re-run. If it "
              "MIGHT have fired, CHECK PolygonScan for 0xe9E3…3AA9 BEFORE re-running "
              "(avoids a double-bet).")
    if not go:
        print("\n(DRY RUN complete — no money spent. Re-run with --go to fire.)")
        return 0
    # Parse tx hash and record it.
    m = re.search(r"0x[0-9a-fA-F]{64}", full)
    if not m:
        print("\n!! Fired but no tx hash found in output — VERIFY on PolygonScan before any retry.")
        return 1
    tx = m.group(0)
    print(f"\nfilled tx: {tx}\nrecording to predictions.json ...")
    env = dict(os.environ)
    cp = certifi_path()
    if cp:
        env["SSL_CERT_FILE"] = cp; env["REQUESTS_CA_BUNDLE"] = cp
    rec = subprocess.run([PG_PY, "record_trade.py", tx, "--market", str(mid),
                          "--execution-layer", "polygun"],
                         cwd=HERE, capture_output=True, text=True, env=env)
    print(rec.stdout[-600:] or rec.stderr[-400:])
    return 0


def main():
    ap = argparse.ArgumentParser(description="One-command Belgium/Iran/Draw $2 bet")
    ap.add_argument("side", nargs="?", choices=list(MARKETS), help="belgium | iran | draw")
    ap.add_argument("--show", action="store_true", help="show live odds, no bet")
    ap.add_argument("--go", action="store_true", help="actually fire (default = dry run)")
    ap.add_argument("--amount", type=float, default=2.0, help="USD to spend (default 2)")
    a = ap.parse_args()
    if a.show or not a.side:
        show()
        if not a.side:
            print("\nThen: bet_bel_irn.py <belgium|iran|draw> --go")
        return 0
    return fire(a.side, a.amount, a.go)


if __name__ == "__main__":
    sys.exit(main())
