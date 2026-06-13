# Colony Harness

First implementation of a lightweight agent-colony debate harness inspired by MiroFish, without cloning or depending on MiroFish.

The goal of this prototype is narrow:

1. spawn many genome-based predictors;
2. give each predictor a private genome;
3. attach match data through scout findings and evidence claims;
4. route selected predictors into topic debate rooms;
5. synthesize room disagreements into one final public debate signal;
6. let the rest of the colony consume the debate parametrically;
7. produce sealed betting commitments.

This is intentionally not the full product yet. Arc trades, x402 purchases, ClickHouse, and real settlement are still outside this first harness. The harness can now generate local EVM wallets and ENS identity-card records for agents so the identity layer can be tested before those systems are attached.

## Current Working Version

This repository now has a first working harness loop. It is not production quality, but it is useful enough to iterate on:

```text
World Cup KG
  -> one match subgraph
  -> public/shared/private scout findings
  -> evidence claims linked to teams, players, and sources
  -> many genome predictors
  -> overlapping topic debate rooms
  -> final chamber synthesis
  -> forecasts, pass/bet decisions, compact logs
```

What works today:

- Build a World Cup tournament KG from OpenFootball.
- Run a single match from the KG, for example Brazil vs Morocco.
- Spawn tens of cheap genome predictors with different source weights, thresholds, risk appetite, and herd bias.
- Fetch public web/search data for match news, squad availability, recent team form, player form, squad depth, predicted XI, tactical context, and optional CAMEL-style research.
- Normalize datasource output into `Finding` objects and smaller `evidence_claims`.
- Write a round `world_graph.json` with match, teams, findings, evidence claims, sources, players, genomes, predictions, and debate claims.
- Create overlapping topic rooms such as `neymar_availability`, `morocco_availability`, `team_form`, `player_form`, `market_pricing`, and `source_audit`.
- Give challengers role-aware objections against source quality, evidence relevance, or claimed impact size.
- Store compact dispute metadata for challenger/auditor claims: target claim, target excerpt, critique type, probability gap, and subject shift.
- Feed structured dispute metadata back into the voice layer so challengers and source auditors reply to the disputed claim directly.
- Render public debate messages without agent IDs in the text, with short source-grounded replies and a two-sentence cap for template voices.
- Attach a stable `genome_id` to public roster records, debate claims, forecasts, disputes, conversation memory, and KG genome entities.
- Attach local EVM wallet addresses and lineage metadata to agents.
- Generate ENS identity-card records for each ant subdomain, including parent, lineage, World ID inheritance status, profile URL, and agent-context text.
- Save/load a persistent population state so the same `genome_id` roster can run across multiple matches.
- Evolve a saved population offline from recent conversation-memory scores, keeping useful genomes and replacing weaker slots with mutations.
- Aggregate room outputs into one final-chamber synthesis with structured `diagnostics`: consensus, main evidence thread, minority report, source dispute, room range, and dispute counts.
- Save readable logs and queryable memory in `summary.md`, `debate.md`, `rooms.json`, `conversation_memory.json`, `forecasts.csv`, `findings.json`, `knowledge_views.json`, and `events.compact.jsonl`.
- Analyze recent `conversation_memory.json` files into a compact debater/archetype report for debugging debate quality.

Known rough edges:

- Claim extraction is still heuristic. It can misclassify a positive player note as `injury_availability`, or attach a sentence to the wrong team when both teams are mentioned.
- Source quality is not ranked strongly enough yet. Search snippets and generic squad pages can leak into the debate beside stronger sources such as BBC, ESPN, RotoWire, or official pages.
- Debate wording now uses short source summaries such as "BBC has Neymar missing", structured dispute targets, challenger objections, and room-level synthesis. The replies are cleaner and less repetitive than the first version, but still template-driven rather than a full natural conversation.
- The public odds scout is still a placeholder unless a real odds provider is connected.
- Settlement, bankroll updates, death, x402 data purchases, and live Worldcoin privilege routing are not implemented yet.

## Why This Shape

MiroFish's useful idea is not "copy their stack". It is the pattern:

```text
source context -> agent population -> bounded social interaction -> action logs -> analysis
```

For Colony, the equivalent first loop is:

```text
match context -> predictor genomes -> debate claims -> herd-adjusted forecasts -> sealed stakes
```

## Install

From the workspace root:

```bash
python3 -m pip install -r requirements.txt
```

The core harness uses the Python standard library. The requirements file adds CAMEL and `ddgs` for native CAMEL research scouts and web search.

## Run

From the workspace root:

```bash
python3 colony/run_demo.py
```

Each run now saves compact local artifacts by default under `colony/runs/<timestamp>_<round_id>/`.

With a custom population:

```bash
python3 colony/run_demo.py --agents 80 --rooms 8 --seed 9
```

Create or reuse a persistent population:

```bash
python3 colony/run_demo.py \
  --population-state colony/data/demo_population_state.json
```

Create/reuse local throwaway EVM wallets and assign deterministic ENS names for agents:

```bash
python3 colony/run_demo.py \
  --agents 40 \
  --agent-wallets \
  --ens-parent colonny.eth \
  --show-roster
```

Private keys are written to `colony/secrets/agent-wallets.local.json`, which is gitignored.
Only `wallet_address` and `ens_name` are exported in public agent records. The same EVM
address can be registered with Worldcoin AgentKit on World Chain mainnet and later funded
on Arc testnet for trades/x402 experiments.

Generate ENS identity-card records for the current roster:

```bash
python3 colony/run_demo.py \
  --agents 40 \
  --agent-wallets \
  --ens-parent colonny.eth \
  --verified-root ant_0000 \
  --identity-out colony/data/ens-identities.demo.json
```

Each record has a subdomain such as `root-fable-0.colonny.eth`, an `addr` record pointing
to the ant wallet, an ENSIP-26 `agent-context`, `agent-endpoint[web]`, and compact
`com.colony.*` text records.
Generation-0 ants become lineage roots. Children keep their own ENS names and inherit
`verified_lineage` from the root when a root has been registered through Worldcoin AgentKit.

See the full runbook in [`docs/ens-agent-identity.md`](docs/ens-agent-identity.md).

The canonical agent discovery path is the ENSIP-26 text record:

```text
agent-context         JSON identity card for the ant
agent-endpoint[web]   URL for the ant profile JSON/page
com.colony.*          compact Colony-specific indexes
```

Once a Colony on-chain registry exists, add ENSIP-25 verification records:

```text
agent-registration[<registry>][<agent_id>] = 1
```

Dry-run Sepolia registration from the generated identity file:

```bash
python3 colony/register_ens_identities.py colony/data/ens-identities.demo.json --limit 2
```

Check whether the parent exists and is ready before broadcasting:

```bash
python3 colony/register_ens_identities.py \
  colony/data/ens-identities.demo.json \
  --check-parent
```

To send Sepolia transactions, put `PROJECT_ENS_PRIVATE_KEY` and `SEPOLIA_RPC_URL`
in `colony/.env`, then add `--broadcast`. For ENSv2 parents such as names created in
`app.ens.dev`, the script deploys a per-owner resolver if needed, deploys and attaches a
subregistry to the parent if needed, then registers the ant subname and writes the ENSIP-26
records. Publish a specific ant first:

```bash
python3 colony/register_ens_identities.py \
  colony/data/ens-identities.demo.json \
  --agent-id ant_0001 \
  --ens-version v2 \
  --broadcast
```

The script can still fall back to classic ENS Sepolia for older wrapped/unwrapped parents,
matching the NpmGuard publisher pattern.

Write an additional full JSONL export:

```bash
python3 colony/run_demo.py --out colony/runs/demo.jsonl
```

Print room-level debate highlights and write a human-readable debug report:

```bash
python3 colony/run_demo.py --debug
```

Normal CLI output stays compact and prints the final chamber synthesis. With `--debug`,
the CLI also prints each topic room, representative role, short claim, and dispute
target so debate quality can be inspected without opening the run directory first.
Every run also reports compact debate quality counters: dispute count/rate, number
of evidence subjects, critique-type variety, subject shifts, and claims carried
between rooms.

Disable automatic compact run logs:

```bash
python3 colony/run_demo.py --no-run-log
```

## Build The World Cup KG

Build the tournament-level knowledge graph from OpenFootball:

```bash
python3 colony/build_kg.py --force-refresh
```

Highlight specific teams in the readable summary:

```bash
python3 colony/build_kg.py \
  --team Brazil --team Morocco \
  --team Scotland --team Haiti \
  --team Qatar --team Switzerland
```

Outputs are written under `colony/data/`:

- `openfootball/worldcup_2026.json` - cached source schedule.
- `world_cup_kg.json` - tournament graph JSON.
- `world_cup_kg.summary.md` - readable graph summary and focused matches.

`colony/data/` is ignored by git because future scouts may store fetched or premium data there.

## Run One KG Match Without X

Once the World Cup KG exists, run one match from the graph:

```bash
python3 colony/run_match.py --match "Brazil vs Morocco" --agents 40 --rooms 6 --seed 12 --debug
```

This path uses tournament metadata from the KG and deterministic scout placeholders for market, team-form, odds, news, lineup, and weather. X/social scouts are intentionally disabled here so we can test the core predictor/debater loop before adding noisy or paid social data.

To fetch lightweight public data instead of using synthetic scout placeholders:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --refresh-data \
  --agents 20 \
  --rooms 5 \
  --seed 12 \
  --debug
```

The public-data path currently fetches:

- Wikipedia page summaries for both national teams.
- Google News RSS results for the match query.
- Team-targeted recent-match and form searches for each national team, with DDGS fallback and compact result claims.
- Key-player season-form searches for both teams, including player-specific DDGS queries for tracked players.
- Squad-depth, predicted-XI, and role-depth searches for both teams.
- Google News RSS squad, player, and injury availability headlines.

It does not use X/social unless you explicitly enable the X scout. It also does not claim to have bookmaker odds yet: the odds finding is logged as a low-confidence `odds_unavailable_scout` until a real odds provider is connected.

Add the optional deeper research scout:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --include-camel \
  --agents 20 \
  --rooms 5 \
  --seed 12 \
  --debug
```

`--include-camel` writes a `camel_research_scout` finding. By default it uses focused web/news research queries. If `camel-ai` is installed and `COLONY_CAMEL_USE_NATIVE=1`, it attempts native CAMEL `ChatAgent` + `SearchToolkit().search_duckduckgo` using the `COLONY_CAMEL_*` model settings from `colony/.env`; if native CAMEL fails or returns no usable items, it falls back to the focused web/news path.

To keep the same population across several matches, add `--population-state`:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --population-state colony/data/worldcup_population_state.json \
  --agents 40 \
  --rooms 6 \
  --debug
```

On the first run, the file is created. On later runs, the same agents, genomes, bankrolls, accuracy values, and public wallet addresses are loaded. If a state already exists, omit `--agents` or pass the same population size.

Add the optional X/social scout:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --include-x \
  --agents 20 \
  --rooms 5 \
  --seed 12 \
  --debug
```

The X scout is isolated as `x_availability_scout` and is `shared` access by default. To wire ScrapeCreators or another X provider, set `SCRAPECREATORS_API_KEY` and `SCRAPECREATORS_X_SEARCH_URL` in `colony/.env`. The URL may either contain `{query}` for a templated GET request, or accept POST JSON shaped as `{"query": "..."}`.

## Run Artifacts

Default logs are intentionally compact. They are designed for debugging and analysis without saving raw LLM prompts, raw provider responses, or secret-bearing payloads.

Each automatic run directory contains:

- `summary.md` - match, population, datasource, and betting summary.
- `debate.md` - room debates and the final chamber synthesis.
- `rooms.json` - topic room membership, representatives, claims, and synthesis.
- `conversation_memory.json` - queryable debate memory: room timeline, claims, dispute edges, debater activity, and final diagnostics.
- `forecasts.csv` - final forecast and bet/pass decision for every predictor.
- `findings.json` - normalized findings used by the run.
- `knowledge_views.json` - filtered predictor views derived from the full graph.
- `world_graph.json` - lightweight round subgraph for the selected match, findings, genomes, predictions, and claims.
- `events.compact.jsonl` - compact event stream with summary, findings, claims, and forecasts.
- `debug.md` - optional, written only with `--debug`.

The legacy `--out` JSONL export still includes bet commitments and should be used deliberately.

## Analyze Debate Memory

After several runs, aggregate the conversation memories:

```bash
python3 colony/analyze_memory.py \
  --latest 20 \
  --out colony/runs/conversation_memory_report.md \
  --json-out colony/runs/conversation_memory_report.json
```

The report summarizes:

- debate quality trends, including dispute rate, evidence subjects, critique variety, subject shifts, and carried claims;
- critique mix across recent rooms, such as source quality vs counter-evidence;
- final diagnostic themes, such as recurring availability disputes;
- top stable `genome_id` rows when analyzed runs include genome identity;
- top debater archetypes by persona/model/access tier;
- top single-run debaters for debugging specific room behavior.

This is a debugging heuristic, not a truth label. `speaker_id` is still run-local; use `genome_id` for a stable genome identity and archetypes for broader behavior patterns. To make `genome_id` recur across matches, run with `--population-state`.

## Evolve A Population

Once a population has run for a few matches, create the next population state:

```bash
python3 colony/evolve_population.py \
  --population-state colony/data/worldcup_population_state.json \
  --out colony/data/worldcup_population_state.next.json \
  --latest 20 \
  --survival-rate 0.55 \
  --mutation-rate 0.18
```

The evolution pass is intentionally offline and inspectable. It scores genomes using recent `conversation_memory.json` files, keeps the stronger genomes, and fills weaker agent slots with mutated children. It preserves public wallet addresses by slot and writes lineage hints such as `parent_genome_id`, `previous_genome_id`, and `evolution_role`.

Then run the next match with the evolved state:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --population-state colony/data/worldcup_population_state.next.json
```

## Optional LLM Voices

The harness does not require API keys by default. Debate messages are generated by deterministic local templates.

To use OpenRouter for debater messages:

```bash
cp colony/.env.example colony/.env
# edit colony/.env with your provider values
python3 colony/run_demo.py --voice-mode llm
```

The expected env variables are:

```bash
COLONY_LLM_PROVIDER=openrouter
COLONY_LLM_API_KEY=
COLONY_LLM_BASE_URL=https://openrouter.ai/api/v1
COLONY_LLM_MODEL=deepseek/deepseek-v4-flash
COLONY_LLM_TIMEOUT_SECONDS=30
OPENROUTER_HTTP_REFERER=
OPENROUTER_APP_TITLE=Colony Harness
```

For OpenRouter, `COLONY_LLM_API_KEY` can be replaced by `OPENROUTER_API_KEY` if you prefer to keep provider keys separate. The optional `OPENROUTER_HTTP_REFERER` and `OPENROUTER_APP_TITLE` values are attribution headers used by OpenRouter.

The OpenRouter endpoint is OpenAI-compatible, so the harness sends `POST /chat/completions` with `Authorization: Bearer <key>`.

MiniMax is still supported via `COLONY_LLM_PROVIDER=minimax`.

`COLONY_LLM_BASE_URL` for MiniMax accepts either `https://api.minimax.io` or the Anthropic SDK form from the MiniMax docs, `https://api.minimax.io/anthropic`.

The installed official MiniMax CLI maps regions like this:

- global: `https://api.minimax.io`
- CN: `https://api.minimaxi.com`

For text chat, the CLI uses `POST /anthropic/v1/messages` with the `x-api-key` header, so the harness supports that native MiniMax shape. If you want an OpenAI-compatible provider instead, set `COLONY_LLM_PROVIDER=openai` and use a base URL that exposes `/chat/completions`.

MiniMax has two key types:

- Pay-as-you-go API keys from `API Keys`.
- Subscription Key from `Billing > Token Plan`.

If you are using a Token Plan quota, put the Subscription Key in `COLONY_LLM_API_KEY`. A normal pay-as-you-go key can still return `insufficient_balance_error` even when your Token Plan usage page shows available quota.

## Files

- `run_demo.py` - CLI entrypoint.
- `run_match.py` - one-match runner from the World Cup KG, with X/social scouts disabled.
- `build_kg.py` - World Cup tournament KG builder.
- `colony_harness/genes.py` - genome definitions and random generation.
- `colony_harness/scouts.py` - mock scout findings until real datasources are connected.
- `colony_harness/knowledge.py` - access policy and per-predictor filtered knowledge views.
- `colony_harness/tournament_graph.py` - OpenFootball schedule loader and tournament graph builder.
- `colony_harness/agent.py` - predictor behavior, forecasting, debating, listening.
- `colony_harness/debate.py` - bounded debate feed.
- `colony_harness/harness.py` - orchestration.
- `config/example.colony.json` - example scenario.

## Current Model Layer

This first version uses deterministic local voice templates by default. That keeps the harness cheap, reproducible, and dependency-free.

Later, the `VoiceModel` interface can be backed by:

- a direct OpenAI-compatible API;
- OpenRouter;
- CAMEL `ChatAgent`;
- an OASIS-style environment if we later want richer social actions.

CAMEL is not necessary for this first harness because we do not need full multi-agent tool orchestration yet. We need a clean simulation core first.

## Important Concepts

### Findings

The harness now represents match inputs as `Finding` objects. A finding is a compact piece of structured evidence produced by a scout or deterministic adapter. The current version converts the synthetic config values into mock scout findings:

- market baseline;
- stats finding;
- odds finding;
- news finding.
- shared lineup read;
- shared social read;
- private weather read.

Findings are written into the full graph, but predictors do not automatically see all findings. The harness builds a filtered `KnowledgeView` for every predictor:

- `public`: sees public findings;
- `shared`: sees public and shared findings;
- `private`: sees public, shared, and private findings.

The current access policy is still local and deterministic: a predictor's `query_budget` decides whether it receives public, shared, or private access. Later this can be replaced with x402 payments, Worldcoin privilege, or real data-purchase events.

This gives us the shape needed for future real datasources:

```text
ScrapeCreators / APIs / local files
  -> CAMEL scout or deterministic adapter
  -> Finding
  -> genome predictors
  -> debate and bets
```

Each finding has:

- `scout_name`;
- `access_level`: `public`, `shared`, or `private`;
- `source_type`: `market`, `stats`, `odds`, `news`, `lineup`, `social`, and so on;
- `home_probability` or `home_delta`;
- `confidence`;
- `cost`;
- `citations`;
- `summary`;
- optional `evidence_claims` for player/team availability, recent form, player form, lineup, tactical, or market-preview facts extracted from public sources.

### Tournament KG And Round Subgraph

The target architecture is a World Cup-level knowledge graph, not a graph for only one match.

```text
World Cup KG
  -> tournament
  -> groups
  -> teams
  -> venues
  -> matches
  -> match-specific findings
  -> predictions and debate claims per match
  -> persistent predictor history
```

Each current run writes a lightweight `world_graph.json`. Today this file is a round subgraph for the selected match. It is the first local version of what will later be extracted from the larger World Cup KG:

- `team` entities;
- `match` entity;
- `finding` entities;
- `evidence_claim` entities for structured facts extracted from findings;
- `source` entities for cited articles, feeds, or scraped pages;
- `player` entities when a claim mentions a specific player;
- `predictor` entities;
- `prediction` entities;
- `debate_claim` entities.

Relations include:

- team `plays_home_in` / `plays_away_in` match;
- finding `concerns` match;
- finding `has_evidence_claim`;
- evidence claim `concerns` match;
- evidence claim `about_team`;
- evidence claim `about_player`;
- evidence claim `evidenced_by` source;
- player `member_of` team;
- predictor `made_prediction`;
- predictor `published_claim`;
- claim `concerns` match.

This keeps the graph small while making repeated player facts navigable. For example, several sources can point to separate Neymar availability claims, all attached to the same `player:neymar` node and the same Brazil match subgraph.

### Knowledge Views

The tournament graph can store everything the system knows. A round extracts a match subgraph, then forecasting and debating use a filtered `KnowledgeView` instead of the raw full graph.

```text
World Cup KG
  -> selected match subgraph
  -> access policy
  -> predictor-specific KnowledgeView
  -> forecast / claim
```

This is the first version of the premium data layer. Shared findings can alter the source probabilities for predictors with enough query budget; private findings are visible only to high-budget predictors. Each forecast and debate claim records its `access_tier` and number of visible findings.

### Genome

Each predictor has:

- `estimator`: `poisson` or `llm`;
- `model`: model species label;
- `risk_appetite`;
- `edge_threshold`;
- `source_weights`;
- `herd_bias`;
- `query_budget`;
- `persona`;

Alive predictors expose `genome_id` and `genome_hash`, not the plaintext genome. The plaintext genome can be revealed later on death.

### Debate

Speech is scarce, but interaction should still scale with population. A round now uses two debate layers:

```text
all predictors
  -> cluster by stance and evidence focus
  -> small debate rooms
  -> room syntheses
  -> final chamber synthesis
  -> public debate signal
```

With 100 predictors and `--rooms 6`, the harness creates up to 6 topic rooms. `--speakers` remains as a deprecated alias for old commands. Each room selects a few representatives with roles such as `advocate`, `challenger`, and `source_auditor`. The final chamber now aggregates the room claims into one public synthesis: market lean, main evidence thread, and unresolved disagreement. This keeps logs readable while still letting a large population interact indirectly.

Availability rooms are created only when visible findings contain structured injury or
availability claims. A Brazil vs Morocco synthetic run, for example, should debate
team form or market pricing unless real/scouted Morocco availability evidence exists.

The run summary tracks lightweight debate quality metrics:

- `dispute_count` and `dispute_rate` show whether room representatives are challenging each other.
- `subject_count` shows how many distinct evidence subjects entered the room debate.
- `critique_type_count` shows whether disagreements are varied or all the same kind.
- `subject_shift_count` shows how often a reply brings a different counterweight.
- `carried_claim_count` shows whether agents are bridging ideas across rooms.

Each claim includes:

- debater id;
- debate phase: `room` or `final`;
- room id;
- debate role;
- `claim_type`;
- `selection_reason`;
- stated probability;
- confidence;
- direction;
- short message;
- optional evidence tags;
- optional `dispute` metadata when the claim challenges a previous room claim.

Selection is intentionally explicit in debug logs. With `--debug`, the terminal prints
a compact room-by-room debate preview. Room membership is saved in `rooms.json`, while
`debate.md` shows both room debates and the final chamber synthesis. Room claims and
the final synthesis are also added to the round `world_graph.json` as `debate_claim`
entities. When a claim disputes another claim, the KG also adds a `disputes`
relationship between the two debate-claim entities.

### Listening

Predictors do not become free-form LLM workers. They read the debate as a structured social finding. Their `source_weights.debate` and `herd_bias` determine how strongly they follow or fade the crowd.

Every forecast includes a compact `decision_reason` in `forecasts.csv`, explaining whether the predictor bet or passed based on edge, threshold, debate shift, and dominant source weights.

### Sealed Bets

The harness produces a commitment hash:

```text
sha256(agent_id | round_id | side | stake | salt)
```

The side, stake, and salt are kept in the local reveal record. This gives us the shape needed for a later on-chain commit/reveal betting window.

## Next Steps

1. Clean claim extraction: better team/player attribution, claim typing, duplicate handling, and source-quality ranking.
2. Add settlement and bankroll/accuracy updates after match results.
3. Use settled accuracy plus debate usefulness for reproduction/death.
4. Add a first real odds datasource.
5. Add shared/private finding access policies backed by explicit purchase events.
6. Promote useful source-quality scouts into explicit datasource trust scores.
