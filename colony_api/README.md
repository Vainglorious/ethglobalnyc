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

## Start A Demo Run

The frontend can create a run with `POST /runs/demo`.

```bash
curl -X POST https://ethglobalnyc-production.up.railway.app/runs/demo \
  -H "Content-Type: application/json" \
  -d '{"agents":20,"rooms":4,"seed":42,"voice_mode":"template"}'
```

Response:

```json
{
  "id": "run_20260613_232524_c0ac4d80",
  "status": "queued",
  "events_path": "/data/runs/run_.../events.jsonl"
}
```

Use `voice_mode: "template"` for cheap smoke tests. Use `voice_mode: "llm"` only
after the OpenRouter/DeepSeek variables are configured in Railway.

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
    "decision": "/runs/run_.../artifacts/compact/.../decision.compact.json"
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

The current first integration streams transport/status immediately. Most domain
events arrive when `run_demo.py` writes `events.jsonl` at the end of the harness
run. A later harness refactor can emit room/forecast events during `run_round()`.

## Frontend Interaction

The deployed frontend reads the backend URL from:

```text
frontend/public/config.js
```

```js
window.DN_CONFIG = window.DN_CONFIG || {
  API_URL: 'https://ethglobalnyc-production.up.railway.app',
}
```

The interaction code lives in:

```text
frontend/public/dinasty/databridge.js
frontend/public/dinasty/hud.js
```

Frontend flow:

1. `databridge.js` loads the latest successful backend run from `GET /runs`.
2. The `Run agents` button calls `POST /runs/demo`.
3. The browser listens to `GET /runs/{run_id}/stream`.
4. When events arrive, the frontend seeds colony stats and the thought ticker.
5. If the backend is unavailable, the frontend falls back to `/data/demo.jsonl`.

Minimal browser-side call:

```js
async function startRun() {
  const apiUrl = window.DN_CONFIG.API_URL
  const response = await fetch(`${apiUrl}/runs/demo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agents: 20,
      rooms: 4,
      voice_mode: 'template',
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
```

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
