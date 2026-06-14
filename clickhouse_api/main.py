"""clickhouse_api — the metered, timestamp-gated knowledge plane for Colony.

Exposes the ClickHouse corpus (Polymarket market catalog, odds time-series, UMA
resolution events) behind:
  - a TIMESTAMP GATE (ts <= as_of, server-enforced + re-checked) — the cardinal rule,
  - an x402 payment handshake (402 -> pay -> 200) so "thinking costs money",
  - a premium tier for verified lineages (Worldcoin humanId) — cheaper + higher caps.

This is the first buildable slice: structured datasets (not raw SQL), a STUBBED
x402 verifier (real Arc settlement check is TODO), and a real gate with a leak test
(test_gate.py). See clickhouse/README.md and clickhouse/DATA_CATALOG.md.
"""

from __future__ import annotations

import os
import uuid
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import ch

app = FastAPI(title="Colony ClickHouse API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CH_API_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"], allow_headers=["*"],
)

# --- x402 / pricing config -------------------------------------------------
PAY_TO = os.environ.get("CH_API_PAY_TO", "0x0000000000000000000000000000000000000000")
ASSET = os.environ.get("CH_API_ASSET_USDC", "0x3c499c542cEF5E3811e1192ce70d8cc03d5c3359")  # USDC (Polygon)
NETWORK = os.environ.get("CH_API_NETWORK", "eip155:137")
BASE_PRICE_USDC = float(os.environ.get("CH_API_BASE_PRICE_USDC", "0.01"))
PER_ROW_USDC = float(os.environ.get("CH_API_PER_ROW_USDC", "0.0002"))
VERIFIED_DISCOUNT = float(os.environ.get("CH_API_VERIFIED_DISCOUNT", "0.5"))  # verified pays 50%

GATED_DATASETS = {"odds", "uma_events"}      # require as_of + payment
DATASETS = {"markets", "odds", "uma_events"}


class QueryRequest(BaseModel):
    dataset: Literal["markets", "odds", "uma_events"]
    as_of_ts: str | None = Field(default=None, description="ISO or 'YYYY-MM-DD HH:MM:SS' UTC; required for gated datasets")
    polymarket_id: str | None = None
    q: str | None = None
    event_name: str | None = None
    limit: int = Field(default=200, ge=1, le=2000)
    ant_id: str | None = None


def _tier(human_id: str | None, lineage_tier: str | None) -> str:
    if (lineage_tier or "").lower() == "verified" or (human_id or "").startswith("0x"):
        return "verified"
    return "standard"


def _price(rows_estimate: int, tier: str) -> float:
    raw = BASE_PRICE_USDC + PER_ROW_USDC * max(rows_estimate, 1)
    if tier == "verified":
        raw *= VERIFIED_DISCOUNT
    return round(raw, 6)


def _payment_required(resource: str, price: float, tier: str) -> JSONResponse:
    """x402-shaped 402 response (the 'pay' challenge)."""
    return JSONResponse(
        status_code=402,
        content={
            "x402Version": 1,
            "error": "payment required",
            "accepts": [{
                "scheme": "exact",
                "network": NETWORK,
                "maxAmountRequired": str(price),
                "asset": ASSET,
                "payTo": PAY_TO,
                "resource": resource,
                "description": f"Colony knowledge-plane query ({tier} tier)",
                "nonce": uuid.uuid4().hex,
            }],
        },
    )


@app.get("/health")
def health():
    try:
        ok = ch.ping()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "service": "clickhouse-api", "clickhouse": str(exc)}
    return {"ok": bool(ok), "service": "clickhouse-api", "clickhouse": "reachable"}


@app.get("/config")
def config():
    return {
        "service": "clickhouse-api",
        "datasets": sorted(DATASETS),
        "gated_datasets": sorted(GATED_DATASETS),
        "timestamp_gate": "every gated query enforces <ts> <= as_of_ts (SQL + re-checked); see test_gate.py",
        "pricing": {"base_usdc": BASE_PRICE_USDC, "per_row_usdc": PER_ROW_USDC,
                    "verified_discount": VERIFIED_DISCOUNT, "asset": ASSET, "network": NETWORK, "pay_to": PAY_TO},
        "tiers": {"standard": "default", "verified": "Worldcoin-verified lineage (humanId) -> discount + higher caps"},
        "x402": "send header 'X-PAYMENT' with a settlement proof; absent -> 402 challenge (STUB verifier for now)",
    }


@app.get("/markets/search")
def markets_search(q: str, limit: int = 20):
    """Catalog search — not time-series, not gated, free (discovery)."""
    try:
        return {"count": None, "rows": ch.search_markets(q, min(limit, 100))}
    except ch.ClickHouseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/query")
def run_query(
    body: QueryRequest,
    request: Request,
    x_payment: str | None = Header(default=None),
    x_human_id: str | None = Header(default=None),
    x_lineage_tier: str | None = Header(default=None),
):
    tier = _tier(x_human_id, x_lineage_tier)

    # ungated discovery dataset
    if body.dataset == "markets":
        rows = _safe(lambda: ch.search_markets(body.q or "", body.limit))
        return {"dataset": "markets", "tier": tier, "gated": False, "count": len(rows), "rows": rows}

    # gated datasets require as_of_ts (the timestamp gate) + payment
    if not body.as_of_ts:
        raise HTTPException(status_code=400, detail=f"as_of_ts is required for gated dataset '{body.dataset}'")

    resource = f"/query/{body.dataset}"
    price = _price(body.limit, tier)
    if not x_payment:
        return _payment_required(resource, price, tier)
    # STUB: any non-empty X-PAYMENT is accepted. TODO: verify Arc/x402 settlement.
    receipt = {"paid": price, "asset": ASSET, "network": NETWORK, "proof": x_payment[:16] + "…", "verified": "stub"}

    if body.dataset == "odds":
        if not body.polymarket_id:
            raise HTTPException(status_code=400, detail="polymarket_id required for dataset 'odds'")
        rows = _safe(lambda: ch.odds_as_of(body.polymarket_id, body.as_of_ts, body.limit))
    elif body.dataset == "uma_events":
        rows = _safe(lambda: ch.uma_events_as_of(body.as_of_ts, body.limit, body.event_name))
    else:  # pragma: no cover
        raise HTTPException(status_code=400, detail="unknown dataset")

    return {"dataset": body.dataset, "tier": tier, "gated": True, "as_of_ts": body.as_of_ts,
            "count": len(rows), "rows": rows, "payment": receipt}


def _safe(fn):
    try:
        return fn()
    except ch.GateLeakError as exc:
        # the gate caught a future row — fail closed, never serve it
        raise HTTPException(status_code=500, detail=f"timestamp gate violation blocked: {exc}")
    except ch.ClickHouseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
