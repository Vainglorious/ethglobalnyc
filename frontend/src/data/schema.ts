/**
 * TypeScript mirror of the Python Colony harness data models.
 * Source of truth: colony/colony_harness/models.py and harness.py:write_jsonl.
 *
 * The harness emits newline-delimited JSON (JSONL); each line carries an
 * `event_type` discriminator. We add `agent_record` (roster export) so the
 * frontend can show real per-agent stats on replay.
 */

export type Side = 'home' | 'away' | 'pass'

/** colony_harness/models.py: MatchContext */
export interface MatchContext {
  round_id: string
  home_team: string
  away_team: string
  market_home_probability: number
  stats_home_signal: number
  odds_home_signal: number
  news_home_signal: number
}

/** colony_harness/models.py: DebateClaim */
export interface DebateClaim {
  round_id: string
  speaker_id: string
  speaker_name: string
  model: string
  persona: string
  stated_home_probability: number
  confidence: number
  direction: Side
  message: string
  evidence_tags: string[]
}

/** colony_harness/models.py: Forecast */
export interface Forecast {
  agent_id: string
  home_probability: number
  edge: number
  side: Side
  stake: number
  bankroll: number
}

/** colony_harness/models.py: BetCommitment */
export interface BetCommitment {
  agent_id: string
  round_id: string
  commitment: string
  reveal: {
    agent_id: string
    round_id: string
    side: Side
    stake: number
    salt: string
  }
}

/** harness.py round_summary dict */
export interface RoundSummary {
  population: number
  speaker_slots: number
  debate_home_probability: number | null
  market_home_probability: number
  home_bets: number
  away_bets: number
  passes: number
  total_staked: number
}

/**
 * agent.public_record (colony_harness/agent.py) — exported via the roster
 * change to harness.write_jsonl so replay carries real per-agent stats.
 */
export interface AgentRecord {
  agent_id: string
  name: string
  wallet_address?: string
  generation: number
  bankroll: number
  accuracy: number
  status: string
  genome_hash: string
}

/* ---- JSONL event envelopes (event_type discriminator) ---- */

export type ColonyEvent =
  | ({ event_type: 'round_summary' } & RoundSummary)
  | ({ event_type: 'debate_claim' } & DebateClaim)
  | ({ event_type: 'forecast' } & Forecast)
  | ({ event_type: 'bet_commitment' } & BetCommitment)
  | ({ event_type: 'agent_record' } & AgentRecord)

export type ColonyEventType = ColonyEvent['event_type']

/* ---- Frontend-domain enums (decoupled from harness wire types) ---- */

/** Visual role buckets. Index = value stored in the roles Uint8Array. */
export enum Role {
  Worker = 0,
  Explorer = 1,
  Carrier = 2,
  Builder = 3,
  Messenger = 4,
}

export const ROLE_COUNT = 5

/** Behavioral state. Index = value stored in the states Uint8Array. */
export enum AntState {
  Wander = 0,
  SeekResource = 1,
  Carrying = 2,
  ReturnHome = 3,
  Debating = 4,
}

/**
 * Caste / task — real ant colonies allocate labor by response thresholds. The
 * value lives in the `tasks` Uint8Array and is reassigned dynamically by colony
 * need (more foragers when food is low, more soldiers under threat, etc.).
 */
export enum AntTask {
  Queen = 0, // one per colony; stays in the nest, lays brood
  Forager = 1, // follows food pheromone, hauls food home
  Scout = 2, // roams wide to discover new resources, seeds trails
  Nurse = 3, // tends brood at the nest
  Soldier = 4, // patrols the territory border, repels intruders
}

export const TASK_COUNT = 5
