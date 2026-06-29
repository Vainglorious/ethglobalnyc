# Handover — refresh the World Cup KG + redeploy colony_api

**Owner:** colony_api / backend dev · **Requested by:** Adil · **Date:** 2026-06-28
**TL;DR:** The committed World Cup knowledge graph went stale (built once on Jun 13, never
re-fetched). It's been rebuilt locally from live OpenFootball. We need that refreshed file
committed and `colony_api` redeployed so the live `/forecast/games` endpoint serves it — and
ideally a scheduled refresh so it never goes stale again.

## Why this matters
Two FE surfaces read World Cup data from **different sources**:

| Surface | Data source | State |
|---|---|---|
| World Cup overlay page (predictions) | static `frontend/public/data/worldcup-games.json` | ✅ already refreshed locally |
| Main-scene **Game** dropdown (`#forecast-game`) | **live** `colony_api GET /forecast/games` | ❌ STALE until redeploy |

The dropdown loads from the deployed backend (`databridge.js → /forecast/games`), which reads
the backend's own copy of `colony/data/world_cup_kg.json`. That deployed copy still has only
**4 match results** (Jun 11–12) and unresolved knockout placeholders, so the dropdown lists
already-played group games as "upcoming" and shows bracket slots like `1C vs 2F`.

## Root cause
`colony/build_kg.py` was run once on Jun 13 and committed. It caches the OpenFootball source
and only re-fetches with `--force-refresh`, so it never updated. Meanwhile OpenFootball filled
in 73 results + the resolved Round-of-32 bracket.

Source chain:
```
OpenFootball 2026 (GitHub) → colony/colony_harness/tournament_graph.py
  https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json
    → colony/data/world_cup_kg.json  (committed; served by colony_api)
```

## What to do

### 1. Rebuild the KG from live OpenFootball (already done locally — just verify/commit)
```
PYTHONPATH=colony python3 colony/build_kg.py --force-refresh
```
This rewrites `colony/data/world_cup_kg.json` (and `world_cup_kg.summary.md`). Result should
be **104 match entities, 73 scored** (was 4), with R32 resolved to real teams
(e.g. Brazil vs Japan, Germany vs Paraguay on 2026-06-29). ~16 later-round fixtures stay as
placeholders — correct, they're genuinely undecided.

Commit the regenerated `colony/data/world_cup_kg.json` + `colony/data/world_cup_kg.summary.md`.

### 2. Redeploy colony_api
Standard Railway deploy of `colony_api` so `GET /forecast/games` and `/kg/world-cup` serve the
new file. (The endpoint already skips scored games, so post-refresh it will correctly return
only genuinely-upcoming fixtures.)

Verify after deploy:
```
curl https://ethglobalnyc-production.up.railway.app/forecast/games | jq '.count, .games[0].name'
```
Expect a smaller count (scored games filtered out) and the first game to be a real upcoming
fixture, not a past group game / placeholder.

### 3. (Recommended) Automate the refresh so it never goes stale again
Add a scheduled job — Railway cron or a GitHub Action — that runs on a daily/hourly cadence:
```
PYTHONPATH=colony python3 colony/build_kg.py --force-refresh
# commit the changed KG (or write it to the deploy volume) → trigger colony_api redeploy
```
This is the durable fix. Ties into the separate `/worldcup/feed` endpoint request
(see `notes/handover/colony-api-worldcup-feed.md`) — that endpoint could also expose a live
`as_of` so the FE drops its static snapshots entirely.

## Notes / gotchas
- `build_kg.py` flags: `--force-refresh` (must use — bypasses the stale cache),
  `--cache`, `--out`, `--summary`. Default out path is `colony/data/world_cup_kg.json`.
- `_forecast_games_from_kg` (colony_api) intentionally **skips scored games** — that's fine
  for the dropdown (it wants upcoming). The World Cup overlay needs played games too, but it
  uses the static FE copy, not this endpoint, so no change needed there.
- The FE static copy (`frontend/public/data/worldcup-games.json`) was regenerated locally
  from the fresh KG and is already correct — no backend action needed for the overlay page.

## Acceptance
- `colony/data/world_cup_kg.json` committed with 73 scored matches + resolved R32.
- Deployed `/forecast/games` returns fresh, upcoming-only fixtures (no past group games,
  no `1C vs 2F` placeholders for already-decided rounds).
- Main-scene Game dropdown lists real upcoming knockout fixtures.
- (If done) a scheduled job keeps the KG current automatically.

## Context
- Full session writeup: `notes/2026-06-28-matchesfix.md`.
- Related endpoint request: `notes/handover/colony-api-worldcup-feed.md`.
