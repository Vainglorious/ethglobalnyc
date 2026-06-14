"""Timestamp-gate leak test (P0 — clickhouse/TODO.md).

Runs the gated dataset helpers against LIVE ClickHouse and FAILS if any returned
row is newer than the requested as_of. This is the test that must pass before the
knowledge plane can be trusted (one future row = the whole result is a lie).

    python clickhouse_api/test_gate.py
exit 0 = gate holds; non-zero = leak (do not ship).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ch  # noqa: E402


def _check_no_future(rows, ts_field, as_of) -> int:
    leaks = [r for r in rows if str(r.get(ts_field, ""))[:19] > as_of[:19]]
    if leaks:
        print(f"  LEAK: {len(leaks)} row(s) with {ts_field} > {as_of}, e.g. {leaks[0].get(ts_field)}")
    return len(leaks)


def main() -> int:
    failures = 0

    # pick a real market that has snapshots
    sample = ch.query(
        "SELECT polymarket_id, count() c, min(toString(captured_at)) lo, max(toString(captured_at)) hi "
        "FROM umalabs.market_snapshots GROUP BY polymarket_id ORDER BY c DESC LIMIT 1"
    )
    if not sample:
        print("no market_snapshots data to test against"); return 1
    pid = sample[0]["polymarket_id"]
    lo, hi = sample[0]["lo"], sample[0]["hi"]
    print(f"sample market {pid}: snapshots {lo} .. {hi}")

    # 1) as_of in the MIDDLE of the series -> must return only <= as_of, and FEWER than all
    mid = lo[:10] + " " + "12:00:00"  # noon of the first day — somewhere inside/early
    gated = ch.odds_as_of(pid, mid, limit=2000)
    allrows = ch.query(
        "SELECT toString(captured_at) captured_at FROM umalabs.market_snapshots "
        "WHERE polymarket_id = {pid:String} ORDER BY captured_at LIMIT 2000", {"pid": pid})
    f = _check_no_future(gated, "captured_at", mid)
    failures += f
    print(f"[odds] as_of={mid}: returned {len(gated)} of {len(allrows)} total rows; leaks={f}")
    if len(gated) > len(allrows):
        print("  FAIL: gated returned more rows than exist"); failures += 1

    # 2) as_of in the PAST (before any data) -> must return zero
    past = "2000-01-01 00:00:00"
    empty = ch.odds_as_of(pid, past, limit=10)
    if empty:
        print(f"  FAIL: as_of in far past returned {len(empty)} rows (expected 0)"); failures += 1
    else:
        print(f"[odds] as_of={past}: returned 0 rows (correct)")

    # 3) uma_events gate
    uma = ch.uma_events_as_of("2026-06-01 00:00:00", limit=500)
    f = _check_no_future(uma, "block_timestamp", "2026-06-01 00:00:00")
    failures += f
    print(f"[uma_events] as_of=2026-06-01: returned {len(uma)} rows; leaks={f}")

    print("\n" + ("GATE OK — no leaks." if failures == 0 else f"GATE FAILED — {failures} problem(s)."))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
