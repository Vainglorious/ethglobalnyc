# Plain-English Docs — Colony, explained without the jargon

Plain-English versions of our technical docs, written for the product side of the team.
No code, no crypto vocabulary assumed. If you only read one thing, read
`colony-in-plain-english.md`.

## What's here
- `colony-in-plain-english.md` — the whole project in one sitting: what we're building,
  why it's interesting, and what the demo actually shows.
- `worldcoin-in-plain-english.md` — how we prove a real human is behind an agent, and
  what we proved works today.
- `clickhouse-in-plain-english.md` — the "data the agents pay to read" piece, and why
  charging for it matters.
- `football-in-plain-english.md` — for our football expert: the system basics PLUS a set of
  fill-in-the-blank prompts where their game knowledge feeds the agents. Two-way doc — we want
  answers back, not just a read.

## The 10-second version
We're building a little **digital colony of "ant" agents that bet on World Cup matches**.
Ants that forecast well earn money and reproduce; ants that forecast badly go broke and
die. Over many generations you can literally watch good strategies take over the colony.
It's part forecasting product, part live experiment about AI agents and money.

## Glossary (translate the jargon when you hit it)
- **Ant / agent** — one little automated forecaster. It has a "personality" (its genes)
  and a wallet with play money.
- **Genome / genes** — a handful of numbers that control how an ant behaves (how much it
  bets, how picky it is, how much it trusts the crowd). Kids inherit them with small random
  tweaks — that's the "evolution."
- **Bankroll** — the ant's play-money balance. Win bets → it grows. Lose / overspend → it
  shrinks to zero and the ant dies.
- **Lineage** — a family line of ants: a founder and all its descendants.
- **Verified lineage** — a family line whose founder was proven to be backed by a real
  human (via World ID). The experiment asks whether these do better or worse than anonymous ones.
- **World ID / Worldcoin** — the "prove you're a real human, once" system. We use it to
  stamp a founder as human-backed.
- **humanId** — the anonymous "this is the same human" tag World gives us. One real person
  = one humanId, forever, no matter how many wallets they make.
- **ClickHouse** — the big database of prediction-market and match data the ants read to
  make smarter bets. It's our "secret sauce" dataset.
- **x402** — the "pay-to-access" rule on a web request: ask for data → get told "pay first"
  → pay → get the data. It's how we make the ants spend money to think.
- **USDC** — a stable digital dollar (here, test/play money, not real funds).
- **Arc** — the payment network where the play money and bets are settled.
- **ENS** — the naming system that gives each ant a human-readable name and stores its life
  story (e.g. `bob-d7.colony.eth`).
- **Replay** — fast-forwarding through past matches so generations of ants can live and die
  in minutes instead of weeks. Needed because the real tournament is too slow for a 3-min demo.
