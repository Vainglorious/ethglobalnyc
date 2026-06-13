# ClickHouse Data Catalog

Live reference of the databases, tables, and schemas available to the Colony on our
ClickHouse Cloud instance. Generated from live inspection on 2026-06-13 (server
`26.2.1.428`). See `README.md` for the rail's purpose and `TODO.md` for build order.

## Connection

```bash
# values live in clickhouse/.env (gitignored)
HOST=h919c97wno.us-east1.gcp.clickhouse.cloud   # ClickHouse Cloud, GCP us-east1
PORT=8443                                        # HTTPS (native TLS on 9440)
USER=adil_hackathon_claude

curl -s "https://$HOST:8443/" --user "$USER:$PASSWORD" --data-binary "SELECT version()"
# append  FORMAT TSV | JSONEachRow | Vertical | PrettyCompact  to control output
```

## Access (our grants)

| Object | Access |
|---|---|
| `default_v3.polymarket_markets_active` | SELECT (read-only) |
| `default_v3.polymarket_markets_all` | SELECT (read-only) |
| `umalabs.*` | SELECT / INSERT / ALTER UPDATE / ALTER DELETE / CREATE / DROP (full) |
| everything else in `default_v3` | no access yet |

`umalabs` is our sandbox — build derived tables, the `/query` backend, and the
timestamp gate here. Don't touch `default_v3` (read-only reference).

---

## `default_v3` — Polymarket reference (read-only)

### `polymarket_markets_all`  ·  `polymarket_markets_active`
~**2,843,273 rows** (identical counts). **One row per market OUTCOME.** A single
batch snapshot (`insert_time` ≈ 2026-06-13 20:07) — current state, *not* a time-series.
~579k distinct `event_id`, ~1.42M distinct `condition_id`.

| column | type | notes |
|---|---|---|
| event_id | String | Polymarket event grouping |
| market_id | String | market id |
| question | String | e.g. "Qatar vs. Switzerland: O/U 2.5" |
| groupitemtitle | String | outcome group label |
| umaenddate | DateTime | UMA end/resolution date |
| icon | String | image url |
| active | Bool | |
| closed | Bool | |
| token_id | String | **CLOB ERC1155 outcome token id** (for trading) |
| outcome | String | e.g. "Over" / "Under" / "Yes" / "No" |
| outcome_price | Float64 | current price (0–1) for that outcome |
| condition_id | String | CTF condition id (the binary market) |
| volume | Float64 | USD volume |
| insert_time | DateTime | batch ingest time |

**Why it matters:** the lookup from a human market name → `token_id` +
`condition_id` + current price, including granular props (O/U totals, corners,
exact scores, halves) that Polymarket's *event* view and PolyGun search hide.

Example — total-goals O/U 2.5 for the 3pm match:
```sql
SELECT question, outcome, outcome_price, token_id, condition_id
FROM default_v3.polymarket_markets_all
WHERE question = 'Qatar vs. Switzerland: O/U 2.5';
-- Under @ 0.335  token 806961...428570
-- Over  @ 0.665  token 54614601...162488
-- condition 0x22bc30...8a67
```

---

## `umalabs` — our sandbox + UMA/odds data (full access)

### `market_snapshots`  ·  **odds time-series**
~**2,240 rows**, ~2,208 distinct markets, window **2026-06-10 → 2026-06-13**.
The timestamped odds history → "beat the market" signal + the timestamp-gate corpus.

| column | type |
|---|---|
| polymarket_id | String |
| captured_at | DateTime64(3,'UTC') |
| price_yes | Nullable(Float32) |
| price_no | Nullable(Float32) |
| volume | Float64 |
| liquidity | Float64 |

> Gate rule: a query at `as_of_ts = T` may only return rows with `captured_at <= T`.

### `markets_current`  ·  enriched current view + resolution status
~**2,208 rows**. Currently all `phase='proposed'`, `resolved_flag=0`, `has_uma_match=0`.

| column | type | column | type |
|---|---|---|---|
| polymarket_id | String | volume | Float64 |
| question | String | liquidity | Float64 |
| slug | String | price_yes | Nullable(Float32) |
| event_slug | String | price_no | Nullable(Float32) |
| image_url | String | odds_source | LowCardinality(String) |
| condition_id | String | phase | LowCardinality(String) |
| question_id | String | confidence | LowCardinality(String) |
| closed | UInt8 | has_uma_match | UInt8 |
| resolved_flag | UInt8 | first_dispute_at | Nullable(DateTime64) |
| uma_status_raw | String | ingested_at | DateTime64(3,'UTC') |
| end_time / closed_time | Nullable(DateTime64) | | |

### `uma_oo_v2_events_decoded`  ·  **UMA Optimistic Oracle resolutions**
~**2,387 rows**, window **2026-05-29 → 2026-06-12**.
`event_name`: Settle 1177 · ProposePrice 1177 · RequestPrice 21 · DisputePrice 12.
This is the early-resolution / dispute feed — the Bet-3 "privileged info" arb edge.

| column | type | column | type |
|---|---|---|---|
| id | String | event_signature | String |
| block_number | Int64 | event_name | String |
| block_timestamp | DateTime | topic1 / topic2 / topic3 | String |
| transaction_hash | String | data | String |
| log_index | Int64 | insert_time | DateTime |
| contract_address | String | | |

### `uma_oo_v2_events_raw`  ·  raw chain logs (2,387)
Backs the decoded view: `block_hash`, `block_timestamp` (Int64 epoch), `topics`,
`data`, `transaction_index`, `is_deleted`, etc.

### `uma_oo_v2_events_decoded_mv`
Materialized view: `uma_oo_v2_events_raw` → `uma_oo_v2_events_decoded`.

### `uma_oo_v2_event_signatures`  ·  topic0 → event_name map (4)
`topic0`, `event_name`, `notes`. Used to decode log signatures
(Settle / ProposePrice / DisputePrice / RequestPrice).

### `polymarket_markets_all_dispute`  ·  empty staging (0)
Same shape as `polymarket_markets_all` plus `dispute_state String`.

---

## How the colony uses this

- **Market resolution / pricing** → `polymarket_markets_all` (name → token_id +
  condition_id + price; finds hidden prop markets).
- **Beat-the-market + timestamp gate** → `market_snapshots` (odds over time).
- **Bet-3 arbitrage (early resolution)** → `uma_oo_v2_events_decoded` (Propose/
  Settle/Dispute before the front-end reflects it).
- **Build space** → `umalabs.*` (derived tables, the `/query` x402 backend, the gate).

## Known gaps
- `market_snapshots` is small/recent (~2.2k markets, 3 days) — not the full "1 TB"
  odds history. Confirm deeper history / backfill (needs broader `default_v3` grant).
- No markets resolved/uma-matched in `markets_current` yet for our matches.
- Timestamp gate + leak test not built yet (`TODO.md` P0) — do before agents read this.
