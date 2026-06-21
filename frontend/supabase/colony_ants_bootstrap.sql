-- WorldColony — incremental bootstrap for persistent ant rosters.
-- Use this if public.colonies already exists and you only need ant rows +
-- local testing delete policies.

create extension if not exists pgcrypto;

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

alter table public.colony_ants enable row level security;

drop policy if exists "colonies_public_delete" on public.colonies;
drop policy if exists "colony_ants_public_read" on public.colony_ants;
drop policy if exists "colony_ants_public_insert" on public.colony_ants;
drop policy if exists "colony_ants_public_update" on public.colony_ants;
drop policy if exists "colony_ants_public_delete" on public.colony_ants;

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

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'colony_ants'
  ) then
    alter publication supabase_realtime add table public.colony_ants;
  end if;
end $$;
