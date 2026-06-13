# Colony Harness

First implementation of a lightweight agent-colony debate harness inspired by MiroFish, without cloning or depending on MiroFish.

The goal of this prototype is narrow:

1. spawn many genome-based predictors;
2. give each predictor a private genome;
3. select a bounded set of debaters;
4. let debaters publish structured claims;
5. let the rest of the colony consume the debate parametrically;
6. produce sealed betting commitments.

This is intentionally not the full product yet. There is no ENS, Arc, x402, ClickHouse, or real match oracle in this first harness. Those systems can be attached once the core loop feels right.

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
python3 colony/run_demo.py --agents 80 --speakers 8 --seed 9
```

Write an additional full JSONL export:

```bash
python3 colony/run_demo.py --out colony/runs/demo.jsonl
```

Write a human-readable debug report:

```bash
python3 colony/run_demo.py --debug
```

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
python3 colony/run_match.py --match "Brazil vs Morocco" --agents 40 --speakers 6 --seed 12 --debug
```

This path uses tournament metadata from the KG and deterministic scout placeholders for market, team-form, odds, news, lineup, and weather. X/social scouts are intentionally disabled here so we can test the core predictor/debater loop before adding noisy or paid social data.

To fetch lightweight public data instead of using synthetic scout placeholders:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --refresh-data \
  --agents 20 \
  --speakers 5 \
  --seed 12 \
  --debug
```

The public-data path currently fetches:

- Wikipedia page summaries for both national teams.
- Google News RSS results for the match query.
- Google News RSS recent-result headlines for each national team.
- Google News RSS squad, player, and injury availability headlines.

It does not use X/social unless you explicitly enable the X scout. It also does not claim to have bookmaker odds yet: the odds finding is logged as a low-confidence `odds_unavailable_scout` until a real odds provider is connected.

Add the optional deeper research scout:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --include-camel \
  --agents 20 \
  --speakers 5 \
  --seed 12 \
  --debug
```

`--include-camel` writes a `camel_research_scout` finding. By default it uses focused web/news research queries. If `camel-ai` is installed and `COLONY_CAMEL_USE_NATIVE=1`, it attempts native CAMEL `ChatAgent` + `SearchToolkit().search_duckduckgo` using the `COLONY_CAMEL_*` model settings from `colony/.env`; if native CAMEL fails or returns no usable items, it falls back to the focused web/news path.

Add the optional X/social scout:

```bash
python3 colony/run_match.py \
  --match "Brazil vs Morocco" \
  --data-mode public \
  --include-x \
  --agents 20 \
  --speakers 5 \
  --seed 12 \
  --debug
```

The X scout is isolated as `x_availability_scout` and is `shared` access by default. To wire ScrapeCreators or another X provider, set `SCRAPECREATORS_API_KEY` and `SCRAPECREATORS_X_SEARCH_URL` in `colony/.env`. The URL may either contain `{query}` for a templated GET request, or accept POST JSON shaped as `{"query": "..."}`.

## Run Artifacts

Default logs are intentionally compact. They are designed for debugging and analysis without saving raw LLM prompts, raw provider responses, or secret-bearing payloads.

Each automatic run directory contains:

- `summary.md` - match, population, datasource, and betting summary.
- `debate.md` - public debater claims.
- `forecasts.csv` - final forecast and bet/pass decision for every predictor.
- `findings.json` - normalized findings used by the run.
- `knowledge_views.json` - filtered predictor views derived from the full graph.
- `world_graph.json` - lightweight round subgraph for the selected match, findings, predictions, and claims.
- `events.compact.jsonl` - compact event stream with summary, findings, claims, and forecasts.
- `debug.md` - optional, written only with `--debug`.

The legacy `--out` JSONL export still includes bet commitments and should be used deliberately.

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
- optional `evidence_claims` for player/team availability, lineup, tactical, or market-preview facts extracted from public sources.

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

Alive predictors expose only `genome_hash`. The plaintext genome can be revealed later on death.

### Debate

Speech is scarce. Only `speaker_slots` predictors become debaters in a round. This mirrors the plan's rule: cost scales with debate slots, not population.

Each claim includes:

- debater id;
- `claim_type`;
- `selection_reason`;
- stated probability;
- confidence;
- direction;
- short message;
- optional evidence tags.

Selection is intentionally explicit in debug logs. A debater is either an elite predictor for the round, based on a simple bankroll/accuracy score, or a wildcard chosen to keep exploration and dissent in the public debate.

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

1. Add real datasource adapters that emit `Finding` objects.
2. Add optional CAMEL scouts for extraction and source critique.
3. Add shared/private finding access policies.
4. Add settlement and bankroll updates.
5. Add reproduction/death across epochs.
