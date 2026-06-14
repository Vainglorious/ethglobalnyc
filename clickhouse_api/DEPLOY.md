# clickhouse_api — Railway Deployment Guide

Goal: deploy `clickhouse_api` (FastAPI, the metered knowledge plane) to Railway as a
**second service** alongside the existing `colony_api`
(`https://ethglobalnyc-production.up.railway.app`). It's a containerized FastAPI app;
Railway builds it from `clickhouse_api/Dockerfile`.

## What you're deploying

- App: `clickhouse_api/main.py` (FastAPI), served by `uvicorn` on `$PORT`.
- It queries our ClickHouse Cloud instance over HTTPS (read-only) and serves the
  timestamp-gated, x402-metered endpoints. See `clickhouse_api/README.md`.
- Build: `clickhouse_api/Dockerfile` (python:3.11-slim → install reqs → uvicorn).

## 0. Prereqs
- Access to the Railway project (same one as `colony_api`) and this GitHub repo.
- The **ClickHouse password** — get it from Adil securely (it's NOT in git; the repo
  `clickhouse/.env` is gitignored, and `.dockerignore` now keeps it out of the image).

## 1. Create the service on Railway
1. Railway project → **New → GitHub Repo** → pick this repo (`Vainglorious/ethglobalnyc`).
2. In the service **Settings → Build**:
   - **Builder:** Dockerfile
   - **Dockerfile Path:** `clickhouse_api/Dockerfile`
   - **Root Directory:** repo root (leave blank / `/`). The Dockerfile's `COPY`
     paths (`clickhouse_api/…`, `clickhouse/…`) assume the **repo root is the build
     context** — do not set root dir to `clickhouse_api`.
3. **Settings → Networking:** enable a public domain (Generate Domain).
4. **Settings → Deploy → Healthcheck Path:** `/health`.

## 2. Environment variables (Service → Variables)

Secrets/config are read from env at runtime (the image does NOT contain any `.env`).

| Variable | Value | Required |
|---|---|---|
| `CLICKHOUSE_HOST` | `h919c97wno.us-east1.gcp.clickhouse.cloud` | yes |
| `CLICKHOUSE_USER` | `adil_hackathon_claude` | yes |
| `CLICKHOUSE_PASSWORD` | **(from Adil — set as a Railway secret)** | yes |
| `CLICKHOUSE_PORT` | `8443` | yes |
| `CH_API_CORS_ORIGINS` | `*` (or the frontend origin) | no |
| `CH_API_PAY_TO` | payout address for x402 (Polygon) | no (default 0x000…0) |
| `CH_API_ASSET_USDC` | `0x3c499c542cEF5E3811e1192ce70d8cc03d5c3359` | no |
| `CH_API_NETWORK` | `eip155:137` | no |
| `CH_API_BASE_PRICE_USDC` | `0.01` | no |
| `CH_API_PER_ROW_USDC` | `0.0002` | no |
| `CH_API_VERIFIED_DISCOUNT` | `0.5` | no |

- **`PORT`** is provided by Railway automatically; the Dockerfile's `CMD` uses
  `${PORT:-8009}`, so don't hardcode it.
- Do **not** add a `.env` file to the image — set everything here.

## 3. Deploy
Trigger a deploy (push to the connected branch, or "Deploy" in Railway). Railway
builds the Dockerfile and starts `uvicorn`.

## 4. Verify after deploy
Replace `<URL>` with the generated domain:

```bash
curl <URL>/health
# -> {"ok": true, "service": "clickhouse-api", "clickhouse": "reachable"}

curl "<URL>/config" | jq .

curl "<URL>/markets/search?q=Will%20France%20win&limit=2" | jq .

# gated query: 402 challenge without payment...
curl -i -X POST "<URL>/query" -H 'Content-Type: application/json' \
  -d '{"dataset":"odds","polymarket_id":"2508958","as_of_ts":"2026-06-13 12:00:00","limit":5}'
# ...200 with a stub payment header:
curl -X POST "<URL>/query" -H 'Content-Type: application/json' -H 'X-PAYMENT: 0xproof' \
  -d '{"dataset":"odds","polymarket_id":"2508958","as_of_ts":"2026-06-13 12:00:00","limit":5}' | jq .
```

`/health` returning `clickhouse: "reachable"` means the env vars are correct.

## Gotchas
- **Build context = repo root** (the Dockerfile copies both `clickhouse_api/` and
  `clickhouse/`). If Railway scopes the context to `clickhouse_api/`, the `COPY clickhouse`
  step fails — set Dockerfile Path, not Root Directory.
- **`/health` shows `reachable: <error>`** → `CLICKHOUSE_*` vars wrong/missing. The app
  starts fine even if ClickHouse is unreachable; `/health` is how you check.
- **Secrets:** since `.dockerignore` excludes `**/.env`, the in-repo `clickhouse/.env`
  fallback won't exist in the image — Railway env vars are the only source. (Good.)
- **Known status:** the x402 *verifier* is a STUB (any `X-PAYMENT` is accepted) and
  datasets are structured (not raw SQL). The timestamp gate is real — run
  `python clickhouse_api/test_gate.py` locally; it must print `GATE OK`.

## Reference
- Precedent: `colony_api/README.md` (the existing Railway FastAPI service + its Dockerfile).
- App details: `clickhouse_api/README.md`; data: `clickhouse/DATA_CATALOG.md`.
