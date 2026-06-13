# ClickHouse — Data Access Layer 1: "uma-clickhouse-oracle" (2026-06-12)

*The first layer of ClickHouse access for the Colony agents. Engineering record.*

## What this layer is
The "**uma-clickhouse-oracle**" data layer. The `umalabs` database is experimental and good
for the hackathon, so agents get **free range** over it: read it, and even modify it (insert /
update / delete / create / drop tables and views). The Polymarket reference tables are
**read-only** by contrast.

## Connection
- Cluster host: `h919c97wno.us-east1.gcp.clickhouse.cloud` (ClickHouse Cloud, GCP us-east1)
- User created for this layer: `adil_hackathon_claude`
- Ports: HTTPS `8443` / native TLS `9440`, `secure=true`
- Real connection values + password live gitignored in `clickhouse/.env`
  (template at `clickhouse/.env.example`, host/user redacted before commit).

## User + grants (run as admin in the ClickHouse Cloud SQL console)
Modeled on the existing `lyan_dev2` user.

```sql
CREATE USER adil_hackathon_claude
    IDENTIFIED WITH sha256_password BY '<strong password>';

-- Polymarket reference tables: READ-ONLY
GRANT SELECT ON default_v3.polymarket_markets_active TO adil_hackathon_claude;
GRANT SELECT ON default_v3.polymarket_markets_all    TO adil_hackathon_claude;

-- umalabs experimental sandbox: FULL read/write/DDL (the "uma-clickhouse-oracle" free range)
GRANT SELECT, INSERT, ALTER UPDATE, ALTER DELETE, CREATE TABLE, CREATE VIEW, DROP TABLE
    ON umalabs.* TO adil_hackathon_claude;
```

Verify: `SHOW GRANTS FOR adil_hackathon_claude;` (compare to `SHOW GRANTS FOR lyan_dev2;`).

## Access summary
| Scope | Access |
|---|---|
| `umalabs.*` | free range (read + write + DDL) — agents may modify |
| `default_v3.polymarket_markets_active` | read-only |
| `default_v3.polymarket_markets_all` | read-only |
| everything else | no access yet (see below) |

## TODO — later layers (deliberately not doing now)
- Decide and grant access to the **other** data beyond `umalabs` + the two Polymarket tables
  (e.g. broader `default_v3` tables, the odds-history needed for the beat-the-market check).
  Grant explicitly, table by table, once we know what `/query` actually reads.
- Reconcile this free-range modify policy with the **timestamp gate**: agent writes to
  `umalabs` must not become a lookahead-leak vector (clickhouse/TODO.md P0, plan §4).

*Secrets note: the password and full connection string live gitignored in `clickhouse/.env`.
The `<strong password>` above is a placeholder, as in the original note.*
