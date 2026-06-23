# Handover — add `GET /worldcup/feed` to `colony_api`

**Owner:** colony_api dev · **Requested by:** Adil · **Date:** 2026-06-23
**File to edit:** `colony_api/main.py` (FastAPI app). No frontend work in this ticket.

## Request
Add **one new read-only endpoint** that returns everything the World Cup predictions page
needs in a single response, plus an authoritative timestamp. The frontend currently stitches
this together from three static files; we want a live source.

```
GET /worldcup/feed   ->  200 application/json
```

### Response shape (contract — please match exactly)
```json
{
  "as_of": "2026-06-23T18:30:00Z",        // server time, ISO-8601 UTC. THE important field.
  "games":       [ /* see Games below */ ],
  "predictions": { /* contents of repo-root predictions.json, passthrough */ },
  "simulated":   { /* contents of repo-root simulatedtransactions.json, passthrough */ },
  "source": {
    "kg": "colony/data/world_cup_kg.json",
    "predictions": "predictions.json",
    "simulated": "simulatedtransactions.json"
  }
}
```

### Games array — ⚠️ key requirement
Reuse the existing KG walk in `_forecast_games_from_kg()` (colony_api/main.py:2966) BUT
**do not skip matches that already have a score.** The current function does
`if score not in (None, "", {}): continue` — we need the opposite: include played games
**with their `score`** so the FE can show results + settled/open state.

- Please add a **new helper** (e.g. `_worldcup_all_matches()`) rather than changing
  `_forecast_games_from_kg()` — other endpoints rely on its "upcoming only" behavior.
- Keep the **same per-game field shape and the same sort** (`date`, then `time`, then
  `name`) the existing helper produces:

```json
{
  "match_id": "match:world_cup_2026:NNN:...",
  "name": "Panama vs Croatia",
  "home_team": "Panama",
  "away_team": "Croatia",
  "market_type": "three_way",          // "three_way" if it has a group, else "binary"
  "date": "2026-06-23",
  "time": "19:00 UTC-4",
  "stage": "Matchday 3",
  "group": "Group L",
  "venue": "...",
  "score": { "ft": [1,0], "ht": [0,0] }  // null/absent if not yet played
}
```
(You can drop `previous_test_data` / `has_previous_test_data` for this endpoint — the page
doesn't use them.)

### predictions / simulated
Plain passthrough of the two repo-root JSON files, parsed and embedded:
- `predictions.json`  (real on-chain trades — `{ description, venue, wallets, settlement_token, trades:[...] }`)
- `simulatedtransactions.json`

Read from `REPO_ROOT` (constant already exists: `REPO_ROOT = Path(__file__).resolve().parents[1]`).
If a file is missing, return `null` for that key rather than 500.

## Constraints
- **Read-only, public, no auth, no x402.** Must be judge-runnable like `/health` and `/config`.
- Respect existing **CORS** setup (the app already adds `CORSMiddleware`).
- No new dependencies. Pure stdlib `json` + existing `Path` constants.
- Don't modify `/forecast/games`, `/kg/world-cup`, or `_forecast_games_from_kg()`.
- Add the endpoint to the `/config` endpoints listing for discoverability (optional but nice).

## Acceptance
- `curl $API/worldcup/feed` returns 200 with all four top-level keys populated.
- `games` includes **both** played (with `score`) and unplayed matches, sorted by date/time/name.
- `as_of` is current server UTC time on each request.
- `predictions` and `simulated` match the current repo-root file contents.
- Existing endpoints unchanged; deploy is the standard Railway deploy.

## Reference (context only — no action needed)
- Existing fixture endpoint: `GET /forecast/games` (colony_api/main.py:3304).
- Existing KG endpoints: `GET /kg/world-cup`, `GET /kg/world-cup/summary`.
- Background/why: `notes/2026-06-23-colony-worldcup-feed.md`.
