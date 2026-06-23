-- WorldColony — Supabase product schema
-- Run this in the Supabase SQL editor (or via psql with DIRECT_URL).
--
-- Persistence model:
--   colonies            → current colony state, one row per wallet
--   colony_ants         → live ant roster owned by a colony
--   colony_runs         → run history + config snapshots
--   colony_config_events → audit log for config changes
--   wallet_nonces       → replay protection for future signed wallet writes
--
-- Frontend compatibility:
--   The current browser client expects colonies(pubkey, angle, dist, accent,
--   name, founded_at, updated_at). Keep those names stable.
--
-- Security note:
--   colonies and colony_ants keep permissive write policies so the current
--   local publishable-key flow remains testable. Tighten these after
--   wallet-signature auth is wired.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------
-- colonies: one row per Phantom wallet
-- ---------------------------------------------------------------------
create table if not exists public.colonies (
  pubkey                text primary key,
  angle                 double precision not null,
  dist                  double precision not null,
  accent                bigint not null,                    -- 0xRRGGBB as integer
  name                  text not null,
  config                jsonb not null default '{}'::jsonb,
  visibility            text not null default 'public',
  config_schema_version integer not null default 1,
  founded_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),

  constraint colonies_visibility_check
    check (visibility in ('public', 'private', 'unlisted')),
  constraint colonies_config_is_object_check
    check (jsonb_typeof(config) = 'object'),
  constraint colonies_config_schema_version_check
    check (config_schema_version >= 1)
);

-- Upgrade path for an older colonies table that only had the frontend columns.
alter table public.colonies
  add column if not exists config jsonb not null default '{}'::jsonb,
  add column if not exists visibility text not null default 'public',
  add column if not exists config_schema_version integer not null default 1;

create index if not exists colonies_updated_at_idx
  on public.colonies (updated_at desc);

create index if not exists colonies_visibility_idx
  on public.colonies (visibility);

create index if not exists colonies_config_gin_idx
  on public.colonies using gin (config);

-- Bump updated_at on every row update
create or replace function public.colonies_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists colonies_touch_updated_at on public.colonies;
create trigger colonies_touch_updated_at
  before update on public.colonies
  for each row execute function public.colonies_touch_updated_at();

-- ---------------------------------------------------------------------
-- colony_ants: persistent roster for every user colony
-- ---------------------------------------------------------------------
create table if not exists public.colony_ants (
  id                    uuid primary key default gen_random_uuid(),
  pubkey                text not null references public.colonies(pubkey) on delete cascade,
  agent_id              text not null,
  name                  text not null,
  status                text not null default 'alive',
  generation            integer not null default 0,
  parent_agent_id       text not null default '',
  lineage_id            text not null default '',
  lineage_root_agent_id text not null default '',
  genome_id             text not null,
  genome                jsonb not null default '{}'::jsonb,
  strategy              jsonb not null default '{}'::jsonb,
  datafeed_interests    jsonb not null default '[]'::jsonb,
  model                 text not null,
  persona               text not null,
  risk_profile          text not null,
  bankroll              numeric not null default 100,
  accuracy              numeric not null default 0,
  wallet_address        text not null default '',
  ens_name              text not null default '',
  metadata              jsonb not null default '{}'::jsonb,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),

  constraint colony_ants_agent_unique
    unique (pubkey, agent_id),
  constraint colony_ants_status_check
    check (status in ('alive', 'dead', 'inactive', 'retired')),
  constraint colony_ants_generation_check
    check (generation >= 0),
  constraint colony_ants_genome_is_object_check
    check (jsonb_typeof(genome) = 'object'),
  constraint colony_ants_strategy_is_object_check
    check (jsonb_typeof(strategy) = 'object'),
  constraint colony_ants_datafeed_interests_is_array_check
    check (jsonb_typeof(datafeed_interests) = 'array'),
  constraint colony_ants_metadata_is_object_check
    check (jsonb_typeof(metadata) = 'object')
);

create index if not exists colony_ants_pubkey_status_idx
  on public.colony_ants (pubkey, status);

create index if not exists colony_ants_pubkey_agent_id_idx
  on public.colony_ants (pubkey, agent_id);

create index if not exists colony_ants_pubkey_lineage_idx
  on public.colony_ants (pubkey, lineage_id);

create index if not exists colony_ants_model_idx
  on public.colony_ants (model);

create index if not exists colony_ants_strategy_gin_idx
  on public.colony_ants using gin (strategy);

create or replace function public.colony_ants_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists colony_ants_touch_updated_at on public.colony_ants;
create trigger colony_ants_touch_updated_at
  before update on public.colony_ants
  for each row execute function public.colony_ants_touch_updated_at();

-- ---------------------------------------------------------------------
-- colony_runs: append-friendly run history and config snapshots
-- ---------------------------------------------------------------------
create table if not exists public.colony_runs (
  id              uuid primary key default gen_random_uuid(),
  pubkey          text not null references public.colonies(pubkey) on delete cascade,
  run_id          text,
  status          text not null default 'queued',
  config_snapshot jsonb not null default '{}'::jsonb,
  code_version    text,
  artifacts       jsonb not null default '{}'::jsonb,
  started_at      timestamptz,
  completed_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint colony_runs_status_check
    check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  constraint colony_runs_config_snapshot_is_object_check
    check (jsonb_typeof(config_snapshot) = 'object'),
  constraint colony_runs_artifacts_is_object_check
    check (jsonb_typeof(artifacts) = 'object')
);

create index if not exists colony_runs_pubkey_created_at_idx
  on public.colony_runs (pubkey, created_at desc);

create index if not exists colony_runs_run_id_idx
  on public.colony_runs (run_id);

create unique index if not exists colony_runs_run_id_unique_idx
  on public.colony_runs (run_id)
  where run_id is not null;

alter table public.colony_runs
  add column if not exists started_at timestamptz;

alter table public.colony_runs
  add column if not exists completed_at timestamptz;

create or replace function public.colony_runs_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists colony_runs_touch_updated_at on public.colony_runs;
create trigger colony_runs_touch_updated_at
  before update on public.colony_runs
  for each row execute function public.colony_runs_touch_updated_at();

-- ---------------------------------------------------------------------
-- colony_config_events: audit log for every config mutation
-- ---------------------------------------------------------------------
create table if not exists public.colony_config_events (
  id              uuid primary key default gen_random_uuid(),
  pubkey          text not null references public.colonies(pubkey) on delete cascade,
  event_type      text not null,
  previous_config jsonb,
  next_config     jsonb,
  signature       text,
  metadata        jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now(),

  constraint colony_config_events_previous_config_is_object_check
    check (previous_config is null or jsonb_typeof(previous_config) = 'object'),
  constraint colony_config_events_next_config_is_object_check
    check (next_config is null or jsonb_typeof(next_config) = 'object'),
  constraint colony_config_events_metadata_is_object_check
    check (jsonb_typeof(metadata) = 'object')
);

create index if not exists colony_config_events_pubkey_created_at_idx
  on public.colony_config_events (pubkey, created_at desc);

create index if not exists colony_config_events_event_type_idx
  on public.colony_config_events (event_type);

-- ---------------------------------------------------------------------
-- wallet_nonces: replay protection for future signed wallet writes
-- ---------------------------------------------------------------------
create table if not exists public.wallet_nonces (
  id         uuid primary key default gen_random_uuid(),
  pubkey     text not null,
  nonce      text not null,
  action     text not null,
  expires_at timestamptz,
  used_at    timestamptz,
  created_at timestamptz not null default now()
);

create unique index if not exists wallet_nonces_pubkey_nonce_idx
  on public.wallet_nonces (pubkey, nonce);

create index if not exists wallet_nonces_pubkey_created_at_idx
  on public.wallet_nonces (pubkey, created_at desc);

create index if not exists wallet_nonces_expires_at_idx
  on public.wallet_nonces (expires_at);

-- ---------------------------------------------------------------------
-- prematch_snapshots: immutable benchmark inputs for settled games
-- ---------------------------------------------------------------------
create table if not exists public.prematch_snapshots (
  snapshot_id            text primary key,
  match_id               text not null default '',
  match_slug             text not null,
  competition            text not null default 'worldcup_2026',
  home_team              text not null,
  away_team              text not null,
  kickoff_utc            timestamptz not null,
  prediction_cutoff_utc  timestamptz not null,
  created_at_utc         timestamptz,
  status                 text not null default 'ready',
  document_count         integer not null default 0,
  claim_count            integer not null default 0,
  raw_source_count       integer not null default 0,
  source_dir             text not null default '',
  documents_path         text not null default '',
  kg_source_path         text not null default '',
  raw_storage_prefix     text not null default '',
  summary                jsonb not null default '{}'::jsonb,
  metadata               jsonb not null default '{}'::jsonb,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),

  constraint prematch_snapshots_status_check
    check (status in ('draft', 'ready', 'archived')),
  constraint prematch_snapshots_counts_check
    check (document_count >= 0 and claim_count >= 0 and raw_source_count >= 0),
  constraint prematch_snapshots_summary_is_object_check
    check (jsonb_typeof(summary) = 'object'),
  constraint prematch_snapshots_metadata_is_object_check
    check (jsonb_typeof(metadata) = 'object')
);

create index if not exists prematch_snapshots_competition_kickoff_idx
  on public.prematch_snapshots (competition, kickoff_utc desc);

create index if not exists prematch_snapshots_match_slug_cutoff_idx
  on public.prematch_snapshots (match_slug, prediction_cutoff_utc desc);

create or replace function public.prematch_snapshots_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists prematch_snapshots_touch_updated_at on public.prematch_snapshots;
create trigger prematch_snapshots_touch_updated_at
  before update on public.prematch_snapshots
  for each row execute function public.prematch_snapshots_touch_updated_at();

-- ---------------------------------------------------------------------
-- prematch_raw_sources: traceable source fetches that produced a snapshot
-- ---------------------------------------------------------------------
create table if not exists public.prematch_raw_sources (
  id                 uuid primary key default gen_random_uuid(),
  snapshot_id        text not null references public.prematch_snapshots(snapshot_id) on delete cascade,
  source_id          text not null,
  source_type        text not null default '',
  locator            text not null default '',
  sha256             text not null default '',
  bytes              integer,
  collected_at_utc   timestamptz,
  raw_source         jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now(),

  constraint prematch_raw_sources_unique
    unique (snapshot_id, source_id),
  constraint prematch_raw_sources_raw_source_is_object_check
    check (jsonb_typeof(raw_source) = 'object')
);

create index if not exists prematch_raw_sources_snapshot_idx
  on public.prematch_raw_sources (snapshot_id);

create index if not exists prematch_raw_sources_type_idx
  on public.prematch_raw_sources (source_type);

-- ---------------------------------------------------------------------
-- prematch_documents: normalized, timestamped documents before kickoff
-- ---------------------------------------------------------------------
create table if not exists public.prematch_documents (
  id                   uuid primary key default gen_random_uuid(),
  snapshot_id          text not null references public.prematch_snapshots(snapshot_id) on delete cascade,
  document_id          text not null,
  source_type          text not null default '',
  adapter              text not null default '',
  signal_type          text not null default '',
  title                text not null default '',
  snippet              text not null default '',
  url                  text not null default '',
  source_name          text not null default '',
  source_snapshot_id   text not null default '',
  published_at_utc     timestamptz,
  available_at_utc     timestamptz,
  timestamp_precision  text not null default '',
  content_hash         text not null default '',
  sentiment            jsonb not null default '{}'::jsonb,
  raw_document         jsonb not null default '{}'::jsonb,
  created_at           timestamptz not null default now(),

  constraint prematch_documents_unique
    unique (snapshot_id, document_id),
  constraint prematch_documents_sentiment_is_object_check
    check (jsonb_typeof(sentiment) = 'object'),
  constraint prematch_documents_raw_document_is_object_check
    check (jsonb_typeof(raw_document) = 'object')
);

create index if not exists prematch_documents_snapshot_available_idx
  on public.prematch_documents (snapshot_id, available_at_utc);

create index if not exists prematch_documents_snapshot_signal_idx
  on public.prematch_documents (snapshot_id, signal_type);

create index if not exists prematch_documents_source_type_idx
  on public.prematch_documents (source_type);

create index if not exists prematch_documents_title_fts_idx
  on public.prematch_documents using gin (to_tsvector('english', title || ' ' || snippet));

-- ---------------------------------------------------------------------
-- prematch_kg_claims: KG-ready facts extracted from prematch documents
-- ---------------------------------------------------------------------
create table if not exists public.prematch_kg_claims (
  id                    uuid primary key default gen_random_uuid(),
  snapshot_id           text not null references public.prematch_snapshots(snapshot_id) on delete cascade,
  claim_id              text not null,
  team                  text not null default '',
  player                text not null default '',
  subject               text not null default '',
  claim_type            text not null default '',
  claim                 text not null,
  impact                text not null default '',
  confidence            double precision,
  source_kind           text not null default '',
  source_domain         text not null default '',
  source_title          text not null default '',
  source_url            text not null default '',
  source_published      timestamptz,
  source_published_date date,
  available_at_utc      timestamptz,
  source_quality        text not null default '',
  extraction_method     text not null default '',
  metrics               jsonb not null default '{}'::jsonb,
  raw_claim             jsonb not null default '{}'::jsonb,
  created_at            timestamptz not null default now(),

  constraint prematch_kg_claims_unique
    unique (snapshot_id, claim_id),
  constraint prematch_kg_claims_metrics_is_object_check
    check (jsonb_typeof(metrics) = 'object'),
  constraint prematch_kg_claims_raw_claim_is_object_check
    check (jsonb_typeof(raw_claim) = 'object')
);

create index if not exists prematch_kg_claims_snapshot_available_idx
  on public.prematch_kg_claims (snapshot_id, available_at_utc);

create index if not exists prematch_kg_claims_snapshot_type_idx
  on public.prematch_kg_claims (snapshot_id, claim_type);

create index if not exists prematch_kg_claims_source_kind_idx
  on public.prematch_kg_claims (source_kind);

create index if not exists prematch_kg_claims_metrics_gin_idx
  on public.prematch_kg_claims using gin (metrics);

create index if not exists prematch_kg_claims_claim_fts_idx
  on public.prematch_kg_claims using gin (to_tsvector('english', claim));

-- ---------------------------------------------------------------------
-- Row-level security
-- ---------------------------------------------------------------------
alter table public.colonies enable row level security;
alter table public.colony_ants enable row level security;
alter table public.colony_runs enable row level security;
alter table public.colony_config_events enable row level security;
alter table public.wallet_nonces enable row level security;
alter table public.prematch_snapshots enable row level security;
alter table public.prematch_raw_sources enable row level security;
alter table public.prematch_documents enable row level security;
alter table public.prematch_kg_claims enable row level security;

drop policy if exists "colonies_public_read"   on public.colonies;
drop policy if exists "colonies_public_insert" on public.colonies;
drop policy if exists "colonies_public_update" on public.colonies;
drop policy if exists "colonies_public_delete" on public.colonies;
drop policy if exists "colony_ants_public_read"   on public.colony_ants;
drop policy if exists "colony_ants_public_insert" on public.colony_ants;
drop policy if exists "colony_ants_public_update" on public.colony_ants;
drop policy if exists "colony_ants_public_delete" on public.colony_ants;
drop policy if exists "colony_runs_public_read" on public.colony_runs;
drop policy if exists "colony_config_events_public_read" on public.colony_config_events;
drop policy if exists "prematch_snapshots_public_read" on public.prematch_snapshots;
drop policy if exists "prematch_raw_sources_public_read" on public.prematch_raw_sources;
drop policy if exists "prematch_documents_public_read" on public.prematch_documents;
drop policy if exists "prematch_kg_claims_public_read" on public.prematch_kg_claims;

create policy "colonies_public_read"
  on public.colonies for select using (true);

create policy "colonies_public_insert"
  on public.colonies for insert with check (true);

create policy "colonies_public_update"
  on public.colonies for update using (true) with check (true);

create policy "colonies_public_delete"
  on public.colonies for delete using (true);

create policy "colony_ants_public_read"
  on public.colony_ants for select using (true);

create policy "colony_ants_public_insert"
  on public.colony_ants for insert with check (true);

create policy "colony_ants_public_update"
  on public.colony_ants for update using (true) with check (true);

create policy "colony_ants_public_delete"
  on public.colony_ants for delete using (true);

create policy "prematch_snapshots_public_read"
  on public.prematch_snapshots for select using (true);

create policy "prematch_raw_sources_public_read"
  on public.prematch_raw_sources for select using (true);

create policy "prematch_documents_public_read"
  on public.prematch_documents for select using (true);

create policy "prematch_kg_claims_public_read"
  on public.prematch_kg_claims for select using (true);

-- History/audit/nonce tables intentionally have no public policies yet.
-- Prematch benchmark tables are public-read but server-write only.
-- Add owner-scoped policies once signed wallet auth is wired.

-- ---------------------------------------------------------------------
-- Realtime: stream INSERT/UPDATE/DELETE on colonies to subscribed clients.
-- Run history/audit streams are useful for future product surfaces too.
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'colonies'
  ) then
    alter publication supabase_realtime add table public.colonies;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'colony_ants'
  ) then
    alter publication supabase_realtime add table public.colony_ants;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'colony_runs'
  ) then
    alter publication supabase_realtime add table public.colony_runs;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'colony_config_events'
  ) then
    alter publication supabase_realtime add table public.colony_config_events;
  end if;
end $$;
