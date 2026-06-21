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
-- Row-level security
-- ---------------------------------------------------------------------
alter table public.colonies enable row level security;
alter table public.colony_ants enable row level security;
alter table public.colony_runs enable row level security;
alter table public.colony_config_events enable row level security;
alter table public.wallet_nonces enable row level security;

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

-- History/audit/nonce tables intentionally have no public policies yet.
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
