# clickhouse_api — the metered knowledge plane

FastAPI service that exposes the Colony ClickHouse corpus (Polymarket catalog, odds
time-series, UMA resolution events) behind the three rules from `clickhouse/README.md`:

1. **Timestamp gate (cardinal rule):** every gated query enforces `<ts> <= as_of_ts`
   in SQL **and** re-checks every returned row in Python. One future row = the whole
   result is a lie. Proven by `test_gate.py`.
2. **x402 metering:** gated queries return **402 → pay → 200** so thinking costs money.
3. **Premium tier:** Worldcoin-verified lineages (a `humanId`) get a discount + higher caps.

> Status: first buildable slice. Datasets are **structured** (not raw SQL — no injection
> surface; inputs are bound as ClickHouse `param_*`). The x402 verifier is a **STUB**
> (any `X-PAYMENT` header is accepted) — real Arc/x402 settlement verification is the TODO.
> The timestamp gate is **real** and tested.

## Live deployment (Railway)

```
https://ethglobalnyc-production-5ce3.up.railway.app
```

Verify (read-only — judges can run these):
```bash
B=https://ethglobalnyc-production-5ce3.up.railway.app
curl -s "$B/health"    # {"ok":true,"service":"clickhouse-api","clickhouse":"reachable"}
curl -s "$B/config"    # datasets, timestamp gate, pricing, verified-tier discount
curl -s "$B/markets/search?q=Will%20France%20win&limit=2"
# x402 gate: 402 without payment, 200 with a stub proof + verified Worldcoin tier:
curl -i -s -X POST "$B/query" -H 'Content-Type: application/json' \
  -d '{"dataset":"odds","polymarket_id":"2508958","as_of_ts":"2026-06-13 12:00:00","limit":3}' | head -1
curl -s -X POST "$B/query" -H 'Content-Type: application/json' -H 'X-PAYMENT: 0xproof' \
  -H 'X-Human-Id: 0x41e49b485e4b3e568ab23e28820f5c0be5135ec3322786f9d492ec8276608f0' \
  -d '{"dataset":"uma_events","as_of_ts":"2026-06-14 23:59:59","limit":3}'
```

Deployed as a self-contained service: Railway **Root Directory = `clickhouse_api`**,
build pinned by `clickhouse_api/railway.toml`, `CLICKHOUSE_*` set as Railway Variables
(no `.env` in the image). Full steps + gotchas in `DEPLOY.md`.

## Run locally

```bash
python3 -m venv clickhouse_api/.venv
clickhouse_api/.venv/bin/pip install -r clickhouse_api/requirements.txt
# creds: reads CLICKHOUSE_* from env, else falls back to repo clickhouse/.env
clickhouse_api/.venv/bin/uvicorn main:app --app-dir clickhouse_api --port 8009
# gate leak test (run this before trusting any result):
clickhouse_api/.venv/bin/python clickhouse_api/test_gate.py
```

## Endpoints

| Method | Path | Gated? | Notes |
|---|---|---|---|
| GET | `/health` | no | service + ClickHouse reachability |
| GET | `/config` | no | datasets, pricing, tiers, gate description |
| GET | `/markets/search?q=&limit=` | no | catalog lookup → name/outcome/token_id/condition_id/price/volume |
| POST | `/query` | yes (odds, uma_events) | the metered, timestamp-gated query |

### `POST /query`
```json
{ "dataset": "odds|uma_events|markets",
  "as_of_ts": "2026-06-13 12:00:00",   // required for gated datasets (ISO/space UTC)
  "polymarket_id": "2508958",          // dataset=odds
  "event_name": "Settle",              // dataset=uma_events (optional)
  "q": "France",                       // dataset=markets
  "limit": 200 }
```
Headers:
- `X-PAYMENT: <proof>` — settlement proof. Absent on a gated dataset → **402** with an
  x402 `accepts` challenge (`maxAmountRequired`, `payTo`, `asset`, `network`, `nonce`).
- `X-Lineage-Tier: verified` **or** `X-Human-Id: 0x…` — marks the caller as a verified
  lineage → discounted price + (future) higher caps.

Gated datasets:
- **odds** → `umalabs.market_snapshots` for one `polymarket_id`, only `captured_at <= as_of_ts`.
- **uma_events** → `umalabs.uma_oo_v2_events_decoded`, only `block_timestamp <= as_of_ts`.

### Example
```bash
B=http://127.0.0.1:8009
curl "$B/markets/search?q=Will%20France%20win&limit=2"
# 402 challenge:
curl -X POST "$B/query" -H 'Content-Type: application/json' \
  -d '{"dataset":"odds","polymarket_id":"2508958","as_of_ts":"2026-06-13 12:00:00","limit":5}'
# paid (stub) + verified tier:
curl -X POST "$B/query" -H 'Content-Type: application/json' \
  -H 'X-PAYMENT: 0xproof' -H 'X-Lineage-Tier: verified' \
  -d '{"dataset":"odds","polymarket_id":"2508958","as_of_ts":"2026-06-13 12:00:00","limit":5}'
```

## Pricing (env-tunable)
`price = base + per_row*limit`, halved for verified. Defaults: `CH_API_BASE_PRICE_USDC=0.01`,
`CH_API_PER_ROW_USDC=0.0002`, `CH_API_VERIFIED_DISCOUNT=0.5`, `CH_API_PAY_TO`, `CH_API_ASSET_USDC`,
`CH_API_NETWORK=eip155:137`, `CH_API_CORS_ORIGINS=*`.

## How it fits Colony
- Ants' `query_budget` gene → real USDC debits here (the x402 gate makes thinking cost money).
- Verified lineages (Worldcoin `humanId`) → the premium tier (cheaper/more data).
- The timestamp gate is what makes the replay engine honest (no lookahead leakage).

## TODO (next)
- [ ] Replace the STUB x402 verifier with real Arc/x402 settlement verification.
- [ ] Persist nonces / usage per (resource, humanId); free-trial + paid policy.
- [ ] More datasets (resolved outcomes join, beat-the-market odds-vs-result).
- [ ] Deploy (Dockerfile included) — Railway, like colony_api.
