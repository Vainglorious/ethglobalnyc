# The "data the agents pay to read," in plain English

*For the product side. This is the ClickHouse / data piece.*

## What it is
We have a large database of **prediction-market and match data** — odds, outcomes, history.
This is our secret sauce: it's what lets an ant make a smart bet instead of a coin-flip guess.
("ClickHouse" is just the brand of database we're using; the name doesn't matter to the story.)

## The one clever rule: thinking costs money
An ant can't read this database for free. Every time it wants data, it has to **pay a small
fee** out of its play-money balance. Think of it like a pay-per-view paywall for facts.

Why bother charging? Because **free information makes for lazy, meaningless decisions.** If
peeking costs something, every ant has to decide *"is this data worth the price?"* — and that
trade-off is what makes its choices feel real and gives its wins weight. An ant that wastes
money on data it didn't need goes broke faster. That's part of the natural selection.

## The one rule we must never break
This is the single most important technical guardrail, and it's easy to explain:

> **An ant may only see data from the past, never the future.**

We **replay** old matches at high speed (so generations turn over in minutes). During replay,
if an ant could accidentally peek at a result that, in its timeline, *hasn't happened yet*,
then it's not forecasting — it's cheating, and every result becomes worthless. So we build a
strict "no peeking past the current moment" gate, and we test it before anything else. If you
hear the team obsess about "timestamp gating" or "lookahead," this is what they mean.

## What we set up so far
- We created a dedicated login to the database for our agents.
- **Layer 1 access ("the UMA sandbox"):** there's an experimental section of the database we
  gave the agents **free range** over — they can read it and even modify it. It's a safe
  playground for the hackathon.
- The **market/odds reference tables** are **read-only** — agents can look but not touch.
- **Left for later:** opening up access to the *other*, more sensitive data, one table at a
  time, once we know exactly what the agents need.

## Why it matters for the product
- It's what turns "agents guessing" into "agents researching" — the credible version of the
  pitch.
- The pay-to-read fee is also a money sink that keeps the economy honest (ants can't just sit
  on infinite free info).
- The "only past data" rule is our integrity guarantee — it's what lets us honestly say the
  forecasts are real, not hindsight.

## One-line summary
**A paywalled database of match and betting data that ants spend money to read — with an
ironclad "no peeking at the future" rule that keeps every forecast honest.**
