# Prematch Data Pipeline

The benchmark collection pipeline is intentionally layered. Raw provider
snapshots are saved first, then normalized records are derived from those raw
files, then KG-ready claims are generated from the normalized layer.

## Directory Layout

Each match collection should use this layout:

```text
<match_run>/
  collection_manifest.json
  raw/
    google_news/
    gdelt/
    scrapecreators_x/
    polymarket/
      gamma_public_search.json
      clob/
  normalized/
    prematch_documents.json
  kg/
    prematch_kg_source.json
  polymarket_kg/
    <match_slug>/
      findings.json
      world_graph.json
      knowledge_views.json
  reports/
    prematch_quality_report.md
```

## Rules

- `raw/` is immutable evidence. Do not edit these files after collection.
- `normalized/` may be regenerated from `raw/`.
- `kg/` may be regenerated from `normalized/`.
- `polymarket_kg/` is produced by the existing KG scouting module; its raw
  Gamma/CLOB inputs are also saved under `raw/polymarket/`.
- Benchmark datasets should be built only after the match result is known, and
  only from sources whose `available_at_utc` is earlier than the configured
  prediction cutoff.

## Cleanup Policy

Keep:

- raw provider responses;
- normalized documents;
- KG-ready source files;
- quality reports and collection manifests.

Delete:

- dry-run manifests;
- failed one-off probes that are not linked from a collection manifest;
- raw files from obsolete hardcoded queries that do not mention the match teams;
- Python caches.

## Scheduled Collection

Use `colony/automate_prematch_snapshots.py` as a cron tick. It selects matches
whose collection target is inside the tick window, runs the existing scrape/KG
builder, imports the snapshot into Supabase, and writes a local marker so a
second tick does not repeat the same work.

Recommended cron cadence:

```bash
python3 colony/automate_prematch_snapshots.py \
  --lead-minutes 30 \
  --lookahead-minutes 0 \
  --grace-minutes 15 \
  --limit 3
```

Run that every ten minutes. Cron expression:

```text
*/10 * * * *
```

With the defaults, a match is collected when `kickoff_utc - 30 minutes` falls
between `now - 15 minutes` and `now`. The resulting Supabase `snapshot_id` is based on the
prediction cutoff, for example:

```text
worldcup_2026_france_vs_iraq_20260622T203000Z
```

For Railway Cron or a container with a persistent volume, point outputs at the
volume and keep the same `colony/.env` used by the API:

```bash
python3 colony/automate_prematch_snapshots.py \
  --out-root /data/prematch_scrape \
  --env-file colony/.env \
  --lead-minutes 30 \
  --lookahead-minutes 0 \
  --grace-minutes 15
```

Required env for Supabase import:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

Optional providers can be disabled when their credentials are not configured:

```bash
python3 colony/automate_prematch_snapshots.py --skip-scrapecreators-x
```
