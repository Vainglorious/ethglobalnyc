"""ClickHouse HTTP client for clickhouse_api — read-only, parameterized, gated.

Reads credentials from env (CLICKHOUSE_*), falling back to repo clickhouse/.env.
All user inputs go through ClickHouse server-side query parameters ({name:Type} +
param_<name>) — never string-formatted into SQL — so there's no injection surface.

THE TIMESTAMP GATE (cardinal rule, clickhouse/README.md): every time-series query
filters `<ts> <= as_of` IN SQL, and `assert_gated()` re-checks every returned row
in Python (defense in depth). One leaked future row makes the whole product a lie.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    p = REPO_ROOT / "clickhouse" / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if not os.environ.get("SSL_CERT_FILE"):
        try:
            import certifi
            os.environ["SSL_CERT_FILE"] = certifi.where()
        except Exception:
            pass


_load_env()
HOST = os.environ.get("CLICKHOUSE_HOST", "")
USER = os.environ.get("CLICKHOUSE_USER", "")
PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")
PORT = os.environ.get("CLICKHOUSE_PORT", "8443")


class ClickHouseError(Exception):
    pass


class GateLeakError(Exception):
    """Raised if a returned row violates the timestamp gate. Should NEVER happen."""


def query(sql: str, params: dict | None = None, *, timeout: int = 30) -> list[dict]:
    """Run a read-only query and return rows as dicts. `params` are bound via
    ClickHouse server-side parameters (param_<name>), not string interpolation."""
    if not HOST or not PASSWORD:
        raise ClickHouseError("ClickHouse credentials not configured (CLICKHOUSE_*).")
    qs = {f"param_{k}": str(v) for k, v in (params or {}).items()}
    qs.update({"max_memory_usage": "2000000000", "max_threads": "2",
               "max_execution_time": str(timeout)})
    url = f"https://{HOST}:{PORT}/?" + urllib.parse.urlencode(qs)
    body = (sql.strip().rstrip(";") + "\nFORMAT JSONEachRow").encode("utf-8")
    auth = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Authorization": "Basic " + auth,
                                          "Content-Type": "text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ClickHouseError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")
    except Exception as exc:  # noqa: BLE001
        raise ClickHouseError(str(exc))
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def assert_gated(rows: list[dict], ts_field: str, as_of: str) -> list[dict]:
    """Defense-in-depth: raise if any row's ts_field is newer than as_of."""
    for row in rows:
        val = str(row.get(ts_field, ""))
        # lexical compare works for ISO 'YYYY-MM-DD HH:MM:SS[.fff]'
        if val and val[:19] > as_of[:19]:
            raise GateLeakError(f"gate leak: {ts_field}={val} > as_of={as_of}")
    return rows


# --- structured datasets ---------------------------------------------------

def search_markets(q: str, limit: int = 20) -> list[dict]:
    """Catalog lookup (no time-series, not gated). name -> token_id/condition_id/price."""
    sql = """
        SELECT question, outcome, round(outcome_price, 4) AS price,
               token_id, condition_id, round(volume, 2) AS volume, active, closed
        FROM default_v3.polymarket_markets_all
        WHERE positionCaseInsensitive(question, {q:String}) > 0
        ORDER BY volume DESC
        LIMIT {limit:UInt32}
    """
    return query(sql, {"q": q, "limit": limit})


def odds_as_of(polymarket_id: str, as_of: str, limit: int = 500) -> list[dict]:
    """GATED odds time-series: only snapshots with captured_at <= as_of."""
    sql = """
        SELECT polymarket_id, captured_at, price_yes, price_no, volume, liquidity
        FROM umalabs.market_snapshots
        WHERE polymarket_id = {pid:String}
          AND captured_at <= parseDateTime64BestEffort({as_of:String}, 3, 'UTC')
        ORDER BY captured_at
        LIMIT {limit:UInt32}
    """
    rows = query(sql, {"pid": polymarket_id, "as_of": as_of, "limit": limit})
    return assert_gated(rows, "captured_at", as_of)


def uma_events_as_of(as_of: str, limit: int = 200, event_name: str | None = None) -> list[dict]:
    """GATED UMA Optimistic-Oracle events: only block_timestamp <= as_of."""
    sql = """
        SELECT block_timestamp, event_name,
               contract_address, transaction_hash, topic1, topic2
        FROM umalabs.uma_oo_v2_events_decoded
        WHERE block_timestamp <= parseDateTimeBestEffort({as_of:String})
          AND ({ev:String} = '' OR event_name = {ev:String})
        ORDER BY block_timestamp DESC
        LIMIT {limit:UInt32}
    """
    rows = query(sql, {"as_of": as_of, "limit": limit, "ev": event_name or ""})
    return assert_gated(rows, "block_timestamp", as_of)


def ping() -> bool:
    return query("SELECT 1 AS ok")[0].get("ok") == 1
