"""Track the UMA resolution cycle for the Qatar vs Switzerland markets.

Polls ClickHouse on a loop and logs a timeline so we can LEARN how a Polymarket
market settles via UMA Optimistic Oracle V2 (RequestPrice -> ProposePrice ->
[DisputePrice] -> Settle), which is the basis for the Bet-3 arbitrage edge.

Watches two things each poll:
  1. Match market prices (winner + O/U 2.5) from default_v3.polymarket_markets_all
     — near-live; resolution shows as price -> 1.0/0.0 and closed=true.
  2. umalabs.uma_oo_v2_events_decoded — new RequestPrice/Propose/Dispute/Settle.

Appends to clickhouse/uma_cycle_log.tsv and prints. Handles the cluster's
intermittent MEMORY_LIMIT_EXCEEDED with retries.

    python clickhouse/track_uma.py --interval 90 --max-minutes 30
"""

from __future__ import annotations

import argparse
import datetime
import os
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "uma_cycle_log.tsv"

# markets to watch (token_id -> label) — point lookups are light on the big table
TOKENS = {
    "66066640081366099233010777058886646300763486736056057848435195209438713673265": "WIN_Switzerland",
    "806961490044622937807145878629353199231499772082061646712921630323183428570": "OU2.5_Under",
    "54614601139630243784954147924158345636800070313383972710283600656556101162488": "OU2.5_Over",
}


def load_env():
    for line in (HERE / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def ch(query: str, retries: int = 4):
    host = os.environ["CLICKHOUSE_HOST"]
    auth = f'{os.environ["CLICKHOUSE_USER"]}:{os.environ["CLICKHOUSE_PASSWORD"]}'
    body = (query + " SETTINGS max_memory_usage=2000000000, max_threads=2").encode()
    import base64
    hdr = {"Authorization": "Basic " + base64.b64encode(auth.encode()).decode()}
    for _ in range(retries):
        try:
            req = urllib.request.Request(f"https://{host}:8443/", data=body, headers=hdr)
            with urllib.request.urlopen(req, timeout=40) as r:
                out = r.read().decode()
            if "MEMORY_LIMIT_EXCEEDED" in out:
                import time
                time.sleep(3)
                continue
            return out.strip()
        except Exception as exc:  # noqa: BLE001
            import time
            time.sleep(3)
            last = str(exc)
    return f"ERR {last if 'last' in dir() else 'retry-exhausted'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=90)
    ap.add_argument("--max-minutes", type=int, default=30)
    args = ap.parse_args()

    load_env()
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass

    if not LOG.exists():
        LOG.write_text("ts_utc\tkind\tdetail\n")

    def log(kind, detail):
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"{now}\t{kind}\t{detail}"
        with LOG.open("a") as f:
            f.write(line + "\n")
        print(line, flush=True)

    token_list = ",".join(f"'{t}'" for t in TOKENS)
    import time
    deadline = time.monotonic() + args.max_minutes * 60
    prev_uma = None
    log("start", f"watching {len(TOKENS)} markets, interval={args.interval}s")

    while True:
        # 1) match prices / resolution
        rows = ch(f"SELECT token_id, outcome, round(outcome_price,3), closed "
                  f"FROM default_v3.polymarket_markets_all WHERE token_id IN ({token_list}) FORMAT TSV")
        resolved = False
        if rows and not rows.startswith("ERR"):
            parts = []
            for ln in rows.splitlines():
                tok, outcome, price, closed = (ln.split("\t") + ["", "", "", ""])[:4]
                label = TOKENS.get(tok, tok[:8])
                parts.append(f"{label}={price}({'closed' if closed in ('1','true') else 'open'})")
                if closed in ("1", "true") or price in ("1", "0"):
                    resolved = True
            log("prices", " ".join(parts))
        else:
            log("prices", rows or "no rows")

        # 2) UMA oracle activity (small table)
        uma = ch("SELECT event_name, count(), toString(max(block_timestamp)) "
                 "FROM umalabs.uma_oo_v2_events_decoded GROUP BY event_name ORDER BY event_name FORMAT TSV")
        if uma and not uma.startswith("ERR"):
            summary = " ".join(ln.replace("\t", ":") for ln in uma.splitlines())
            if summary != prev_uma:
                log("uma_change", summary)
                prev_uma = summary
            else:
                log("uma", "no change")
        else:
            log("uma", uma or "no rows")

        if resolved:
            log("RESOLVED", "a watched market hit closed/1.0/0.0 — resolution detected")
            break
        if time.monotonic() >= deadline:
            log("timeout", f"stopped after {args.max_minutes} min")
            break
        time.sleep(args.interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
