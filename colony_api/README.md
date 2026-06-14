# Colony API

Railway deploys this FastAPI wrapper around the Colony harness. The frontend can
use it to start a real agent run, stream status/events, and load the generated
JSONL artifacts.

Production API:

```text
https://ethglobalnyc-production.up.railway.app
```

## Health Check

```bash
curl https://ethglobalnyc-production.up.railway.app/health
```

Expected shape:

```json
{
  "ok": true,
  "service": "colony-api",
  "runs_root": "/data/runs",
  "run_demo_exists": true
}
```

## API Config

The frontend can inspect the backend contract with `GET /config`.

```bash
curl https://ethglobalnyc-production.up.railway.app/config
```

Important fields:

```json
{
  "defaults": {
    "agents": 200,
    "rooms": 12,
    "seed": 205,
    "voice_mode": "llm",
    "agent_wallets": true,
    "wallet_provider": "dynamic",
    "wallet_store": "colony/data/agent-wallets.dynamic.200.public.json"
  },
  "identity_fields": [
    "agent_id",
    "name",
    "ens_name",
    "wallet_address",
    "world_status",
    "world_access_tier",
    "genome_id",
    "lineage_id"
  ]
}
```

## Start A Demo Run

The frontend can create a run with `POST /runs/demo`.

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/runs/demo \
  -H "Content-Type: application/json" \
  -d '{"agents":200,"rooms":12,"seed":205,"voice_mode":"llm","agent_wallets":true,"wallet_provider":"dynamic","wallet_store":"colony/data/agent-wallets.dynamic.200.public.json"}'
```

Response:

```json
{
  "id": "run_20260613_232524_c0ac4d80",
  "status": "queued",
  "events_path": "/data/runs/run_.../events.jsonl"
}
```

Use `voice_mode: "llm"` for the deployed frontend interaction. Use
`voice_mode: "template"` only for cheap smoke tests or when OpenRouter/DeepSeek
variables are not configured in Railway.

The committed wallet store is sanitized:

```text
colony/data/agent-wallets.dynamic.200.public.json
```

It contains the 200 already-published Dynamic/ENS public addresses, but no raw
private keys and no Dynamic user metadata. It lets Railway reuse the same
`ant_0000` ... `ant_0199` wallet addresses and ENS names instead of minting new
wallets during a frontend demo click.

## Get Ants

For a quick frontend-to-backend smoke test, use `GET /ants`. This reads the
committed public wallet registry and does not require a completed run.

```bash
curl https://ethglobalnyc-production.up.railway.app/ants
```

Response shape:

```json
{
  "count": 200,
  "source": "colony/data/agent-wallets.dynamic.200.public.json",
  "agents": [
    {
      "agent_id": "ant_0000",
      "name": "ant-0000",
      "ens_name": "root-fable-0.colonny.eth",
      "wallet_address": "0x3fB467e269e4C0BfdeAA99086f7854d3590A078D",
      "wallet_provider": "dynamic"
    }
  ]
}
```

## Get KG

For a static KG smoke test, use `GET /kg/world-cup`. This serves the committed
World Cup tournament graph.

```bash
curl https://ethglobalnyc-production.up.railway.app/kg/world-cup
curl https://ethglobalnyc-production.up.railway.app/kg/world-cup/summary
```

The graph response includes convenience counts:

```json
{
  "graph_id": "tournament:world_cup_2026",
  "entity_count": 204,
  "relationship_count": 588,
  "entities": [],
  "relationships": []
}
```

## Agent Economy Demo

The demo has two real USDC rails with separate jobs:

- `x402_circle_gateway`: agent-to-agent services. A buyer ant pays a seller ant
  for KG/scout data, room summaries, or audits. The USDC goes to the seller ant
  through Circle Gateway.
- `ColonyForecastMarket`: forecast escrow. Ants stake USDC into the Arc contract,
  then the owner settles the match and correct voters claim winnings.

Inspect the rails:

```bash
curl https://ethglobalnyc-production.up.railway.app/x402/config
curl https://ethglobalnyc-production.up.railway.app/forecast/config
```

Run a real x402 demo payment:

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/x402/demo-payment \
  -H "Content-Type: application/json" \
  -d '{"buyer":"ant_0001","seller":"ant_0002","service":"finding_private"}'
```

Default x402 flow:

```text
ant_0001 -> ant_0002 via Circle Gateway
resource: kg:worldcup:brazil-morocco:private-scout-signal
price: 0.00012 USDC
```

Run the forecast contract demo:

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/forecast/demo-setup \
  -H "Content-Type: application/json" \
  -d '{"market_key":"worldcup:2026:brazil-morocco:demo-001"}'

curl -X POST https://ethglobalnyc-production.up.railway.app/forecast/settle \
  -H "Content-Type: application/json" \
  -d '{"market_key":"worldcup:2026:brazil-morocco:demo-001","winner":"Brazil"}'
```

Frontend `Run` now drives the same selected-fixture forecast rail end to end.
When the user clicks `Run`, the browser:

1. starts a public-data backend run with `POST /scouting/run` for the selected
   fixture in the dropdown, for example Germany vs Curaçao;
2. waits for that run's `forecast` events so stakes come from actual selected
   match ant decisions instead of the generic demo fixture;
3. creates a fresh Arc market key using the selected fixture plus the run id;
4. calls `POST /forecast/demo-setup` with that `run_id`, which signs ant wallet
   transactions and stakes their USDC into `ColonyForecastMarket`;
5. reads the selected winner from the UI, calls `POST /forecast/settle`, and
   claims payouts for the winning ant wallets.

The lifecycle pauses in the resolution phase while the Arc market is created,
staked, settled, and claimed. If the selected winner has no staked ants, the
frontend resolves to the side with the largest staked amount so the contract has
winners and the payout path can still be demonstrated.

The browser Colony Log is the transaction audit trail for the demo:

- `CHAIN` rows show the forecast smart contract address, market key, market id,
  create-market tx, each ant approve/stake tx, settle tx, claim tx, and Arc
  explorer URL.
- `X402` rows show the Circle Gateway payment rail, buyer/seller wallets,
  gateway transfer id, and receipt artifact paths for the manual `Buy KG` flow.

If no `CHAIN` transaction rows appear after the `Resolution` phase, the run did
not reach the smart-contract calls or the forecast API failed before signing.
In that case, the following `SYSTEM` row should contain the backend error.
The most common cause is missing forecast signing wallets: the deployed backend
needs `COLONY_API_FORECAST_WALLETS_JSON` or `COLONY_API_FORECAST_WALLET_STORE`
pointing to private-key ant wallets with Arc testnet USDC.

Required private env for deployed real payments:

```text
ARC_TREASURY_PRIVATE_KEY=...
FORECAST_MARKET_ADDRESS=0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87
COLONY_API_X402_WALLETS_JSON='{"wallets":{...}}'
COLONY_API_FORECAST_WALLETS_JSON='{"wallets":{...}}'
```

The committed Dynamic wallet registry is public-address only. Any endpoint that
signs x402 payments or contract stakes needs local/test private-key wallets via
those env vars or a configured private wallet-store path.

## Run Scouting

The frontend can start a public-data KG scouting run with `POST /scouting/run`.
By default this runs `colony/run_match.py` with public data and the DeepSeek
structured scouting agents enabled. The browser Scout control fills the request
from the selected World Cup group-stage fixture from June 14, 2026 onward, then
sends that fixture's `match` and `match_id`.

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/scouting/run \
  -H "Content-Type: application/json" \
  -d '{"match":"Germany vs Curaçao","match_id":"match:world_cup_2026:004:germany-curacao","data_mode":"public","include_deepseek_scout":true,"agents":20,"rooms":5,"seed":12,"voice_mode":"template"}'
```

When the run succeeds, fetch the generated KG artifacts:

```bash
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/kg
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/kg/manifest
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/scouting-audit
```

## Poll Run Status

```bash
curl https://ethglobalnyc-production.up.railway.app/runs/run_20260613_232524_c0ac4d80
```

When complete, the response includes links such as:

```json
{
  "status": "succeeded",
  "artifacts": {
    "events": "/runs/run_.../events",
    "stream": "/runs/run_.../stream",
    "summary": "/runs/run_.../artifacts/compact/.../summary.md",
    "decision": "/runs/run_.../artifacts/compact/.../decision.compact.json",
    "kg": "/runs/run_.../kg",
    "kg_manifest": "/runs/run_.../kg/manifest",
    "scouting_audit": "/runs/run_.../scouting-audit"
  }
}
```

## Stream Live Events

`GET /runs/{run_id}/stream` uses Server-Sent Events.

```js
const apiUrl = 'https://ethglobalnyc-production.up.railway.app'
const source = new EventSource(`${apiUrl}/runs/${runId}/stream`)

source.addEventListener('status', (event) => {
  const run = JSON.parse(event.data)
  console.log('run status', run.status)
})

source.addEventListener('colony_event', (event) => {
  const colonyEvent = JSON.parse(event.data)
  console.log('colony event', colonyEvent.event_type, colonyEvent)
})

source.addEventListener('done', () => {
  source.close()
})
```

For `POST /scouting/run`, the stream also emits real KG events from the
generated `world_graph.json` once the scouting subprocess has produced the run
artifacts. The frontend passes these into the KG overlay and the bottom log
terminal: `kg_entity` events appear as `KG` rows for new or updated nodes,
`kg_relationship` events appear as linked-node rows, and `kg_stage`,
`kg_manifest`, and `scouting_audit` events appear as `SCOUT` progress rows.

```js
source.addEventListener('colony_event', (event) => {
  const kgEvent = JSON.parse(event.data)
  if (kgEvent.event_type === 'kg_entity') {
    renderNode(kgEvent.entity)
  }
  if (kgEvent.event_type === 'kg_relationship') {
    renderEdge(kgEvent.relationship)
  }
})
```

Scouting stream event types:

- `kg_stage`: queued, running, graph-built, relationship-building, complete.
- `kg_entity`: one actual entity from the run graph.
- `kg_relationship`: one actual relationship from the run graph.
- `kg_manifest`: the generated `kg_manifest.json` payload.
- `scouting_audit`: the generated `scouting_audit.json` payload plus readiness flags.

The KG stream is real run output, not a fake progress animation. It currently
streams after the scout process writes `world_graph.json`; instrumenting the
individual scout modules would let the graph grow during source collection too.
To keep the demo readable before that deeper backend refactor, the frontend
progressively replays the completed scouting KG artifact in small chunks when
the final graph arrives, so nodes and links appear over time instead of all in
one frame.

Run artifacts are stored under `COLONY_API_RUNS_DIR` when that env var is set,
otherwise under `colony/runs/api` in the running container. A scout such as
Netherlands vs Japan therefore remains available through `/runs/{run_id}/kg`,
`/kg/manifest`, and `/scouting-audit` while that run directory persists. It is
not yet copied into a database or durable object store, so Railway restarts or
deploys can remove it unless a persistent volume is mounted at that runs path.

## Scouting Artifact Storage

Each Scout click creates one run directory keyed by the returned `run_id`, for
example `scout_20260614_023208_27d8138`. The directory holds:

- `metadata.json`: request metadata, status, command, match name, and artifact paths.
- `events.jsonl`: streaming/status events when the run emits them.
- `stdout.log` / `stderr.log`: subprocess logs.
- `compact/.../world_graph.json`: the generated scouting KG.
- `compact/.../kg_manifest.json`: KG validation/readiness metadata.
- `compact/.../scouting_audit.json`: coverage and evidence-quality audit.

To inspect a stored scout run:

```bash
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/events
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/kg
```

The frontend's `Get KG` button first searches `/runs` for the latest successful
scouting run whose `match` or `match_id` matches the selected fixture, then loads
`/runs/{run_id}/kg`. If no stored scout KG exists, it falls back to the committed
tournament graph at `/kg/world-cup` and scopes that graph to the selected fixture
and its two teams. That fallback is intentionally small; run `Scout` first when
you need generated player, club, and evidence context for that fixture.

## Reproduce An Ant

The frontend inspector can create a child ant from the selected parent with
`POST /ants/reproduce`. The backend mutates a deterministic parent personality
genome, creates or reuses a wallet, records ENS-style child metadata under the
runs directory, and optionally funds the child wallet.

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/ants/reproduce \
  -H "Content-Type: application/json" \
  -d '{"parent_agent_id":"ant_0001","wallet_provider":"local","fund_wallet":false}'
```

The response returns the `parent`, the created `child`, the wallet store used,
and the `child_ants.json` source path. `GET /ants` includes these children after
creation so the frontend can attach them to the visible colony.

For `POST /runs/demo`, the first integration streams transport/status
immediately. Most domain events arrive when `run_demo.py` writes `events.jsonl`
at the end of the harness run. A later harness refactor can emit room/forecast
events during `run_round()`.

## Agents And Rooms

The frontend can fetch ant identity and debate-room structure directly without
parsing raw JSONL.

```bash
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/agents
curl https://ethglobalnyc-production.up.railway.app/runs/{run_id}/rooms
```

`GET /runs/{run_id}/agents` returns every `agent_record`, including ENS and
wallet identity fields:

```json
{
  "run_id": "run_...",
  "count": 200,
  "agents": [
    {
      "agent_id": "ant_0000",
      "name": "ant-0000",
      "ens_name": "root-fable-0.colonny.eth",
      "wallet_address": "0x3fB467e269e4C0BfdeAA99086f7854d3590A078D",
      "genome_id": "genome_...",
      "world_status": "unverified",
      "world_access_tier": "standard",
      "latest_forecast": {
        "side": "draw",
        "stake": 2.4
      }
    }
  ]
}
```

`GET /runs/{run_id}/rooms` returns each `debate_room`, including participants,
representatives, stance, evidence focus, synthesis, and claims.

## Frontend Interaction

The deployed frontend reads the backend URL from:

```text
frontend/public/config.js
```

```js
window.DN_CONFIG = window.DN_CONFIG || {
  API_URL: 'https://ethglobalnyc-production.up.railway.app',
  RUN: {
    agents: 200,
    rooms: 12,
    seed: 205,
    voice_mode: 'llm',
    agent_wallets: true,
    wallet_provider: 'dynamic',
    wallet_store: 'colony/data/agent-wallets.dynamic.200.public.json',
  },
}
```

The interaction code lives in:

```text
frontend/public/dinasty/databridge.js
frontend/public/dinasty/hud.js
```

Frontend flow:

1. `databridge.js` loads the latest successful backend run from `GET /runs`.
2. The `Get ants` button calls `GET /ants` and binds wallet/ENS identity to visible ants.
3. The `Get KG` button calls `GET /kg/world-cup` and renders the static tournament KG.
4. The `Run scouting` button calls `POST /scouting/run`, listens to `GET /runs/{run_id}/stream`, and renders streamed KG entities/relationships.
5. The `Run LLM agents` button calls `POST /runs/demo`.
6. When demo events arrive, the frontend seeds colony stats and the thought ticker.
7. If the backend is unavailable, the frontend falls back to `/data/demo.jsonl`.

Minimal browser-side call:

```js
async function startRun() {
  const apiUrl = window.DN_CONFIG.API_URL
  const response = await fetch(`${apiUrl}/runs/demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agents: 200,
      rooms: 12,
      seed: 205,
      voice_mode: 'llm',
      agent_wallets: true,
      wallet_provider: 'dynamic',
      wallet_store: 'colony/data/agent-wallets.dynamic.200.public.json',
    }),
  })
  const run = await response.json()
  return run.id
}
```

## Railway Variables

Required for the API:

```env
COLONY_API_RUNS_DIR=/data/runs
COLONY_API_CORS_ORIGINS=*
COLONY_API_DEFAULT_AGENTS=200
COLONY_API_DEFAULT_ROOMS=12
COLONY_API_DEFAULT_SEED=205
COLONY_API_DEFAULT_VOICE_MODE=llm
COLONY_API_DEFAULT_AGENT_WALLETS=true
COLONY_API_DEFAULT_WALLET_PROVIDER=dynamic
COLONY_API_DEFAULT_WALLET_STORE=colony/data/agent-wallets.dynamic.200.public.json
```

The sanitized wallet store already contains `ant_0000` through `ant_0199`, so
those defaults reuse the existing Dynamic wallet addresses and deterministic ENS
names. Dynamic API variables are only needed when creating additional wallets.

Required for LLM mode:

```env
COLONY_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
COLONY_LLM_BASE_URL=https://openrouter.ai/api/v1
COLONY_LLM_MODEL=deepseek/deepseek-v4-flash
COLONY_LLM_TIMEOUT_SECONDS=30
OPENROUTER_APP_TITLE=Colony Harness
OPENROUTER_HTTP_REFERER=https://ethglobalnyc-production.up.railway.app
COLONY_DEEPSEEK_API_KEY=...
COLONY_DEEPSEEK_BASE_URL=https://openrouter.ai/api/v1
COLONY_DEEPSEEK_MODEL=deepseek/deepseek-v4-flash
```
