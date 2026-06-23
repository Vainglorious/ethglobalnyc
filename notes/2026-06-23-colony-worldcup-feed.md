# 2026-06-23 — Colony API `/worldcup/feed` (notes + reasoning)

Our working notes for why we want a single World Cup feed endpoint on `colony_api`, and
the decisions behind the spec we're handing to the other dev. The clean request-only spec
lives in `notes/handover/colony-api-worldcup-feed.md` — this file is the "why".

## The problem we're solving
The World Cup predictions page (`frontend/public/worldcup/worldcup.js`) currently reads
**three static JSON snapshots** baked into the deploy:
- `frontend/public/data/worldcup-games.json`  ← copy of the KG-derived fixtures
- `frontend/public/data/predictions.json`     ← copy of repo-root `predictions.json`
- `frontend/public/data/simulatedtransactions.json` ← copy of repo-root file

…plus a **hardcoded `REF_DATE`** in `worldcup.js` that defines "today" for the past/upcoming
split. To update the page today, someone has to: re-copy the JSON, hand-bump `REF_DATE`,
rebuild, and redeploy the static site. That's the staleness we keep hitting (the KG only
has 4 real scores; "today" drifts; trades go stale).

## Key realization — we don't need a new server
`colony_api` (already deployed on Railway, same host as `window.DN_CONFIG.API_URL`) already
serves the fixture data. The gap is just that the FE fetches local files instead of the API.

| FE static file | Already-live endpoint |
|---|---|
| `worldcup-games.json` | `GET /forecast/games` (`_forecast_games_from_kg`) |
| (raw KG) | `GET /kg/world-cup`, `/kg/world-cup/summary` |
| `predictions.json` / sim | **not served yet** |

So the ask is small: **one aggregate endpoint** that returns everything the page needs in
one shot, plus an authoritative `as_of` timestamp so the FE stops hardcoding the date.

## ⚠️ The gotcha we found (must communicate to the dev)
`_forecast_games_from_kg()` (colony_api/main.py:2966) **skips any match that already has a
score** (lines 2980–2982: `if score not in (None, "", {}): continue`). That's fine for
"what should the ants forecast next," but it's **wrong for our page** — we need *played*
games too, with their scores, to render:
- the **Settled vs Open** badge (past match = settled),
- win/loss result chips (✓/✗ vs the colony's pick),
- group standings later.

→ The new feed must return **ALL match entities including scored ones**, not reuse the
score-skipping filter. Easiest: a sibling helper that does the same KG walk *without* the
score skip. Keep `/forecast/games` untouched (other things depend on its "upcoming only"
behavior).

## Why one endpoint (not 3 passthroughs)
- The FE does one fetch, one fallback path, one `as_of`. Simpler Live/Replay wiring.
- `as_of` from the server kills the hardcoded `REF_DATE` — "today" is never stale.
- predictions + sim are small; bundling them is cheap and keeps the FE logic in one place.

## What stays as-is (the safety net)
We keep the three local JSON files in `frontend/public/data/` as the **offline / judge-safe
fallback**. The FE will try the live feed first and fall back to the bundled snapshots if
Railway is unreachable — same Live/Replay pattern the main scene already uses. So this change
is additive and reversible (consistent with the "WORLD CUP TEMP — remove after the
tournament" ethos).

## Source-of-truth file locations (for the dev)
- KG: `colony/data/world_cup_kg.json` (already `WORLD_CUP_KG` constant in colony_api)
- Real trades: repo-root `predictions.json`
- Simulated: repo-root `simulatedtransactions.json`
- Repo root constant already exists: `REPO_ROOT = Path(__file__).resolve().parents[1]`

## Follow-on (NOT part of this handover, tracked separately)
- The KG only has 4 committed scores (Jun 11–12). Standings/results stay sparse until a
  scheduled job refreshes `world_cup_kg.json` from a live results source
  (`colony/colony_harness/tournament_graph.py`). Out of scope for the feed endpoint — the
  feed just needs to faithfully pass through whatever scores the KG has.

## FE work on our side (after the endpoint ships — we do this, not the other dev)
1. `worldcup.js`: fetch `API_URL + /worldcup/feed`, fall back to the 3 local JSONs.
2. Replace hardcoded `REF_DATE` with the feed's `as_of` (date portion).
3. No shape changes if the dev matches the contract in the handover doc.
