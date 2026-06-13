# Colony, in plain English

*For the product side of the team. No technical background needed.*

## The idea in one breath
We built a tiny **digital colony of "ant" forecasters**. Each ant bets play-money on World
Cup matches. Ants that bet well get richer and have babies; ants that bet badly go broke and
die. Babies inherit their parent's strategy with small random tweaks — so over many
generations, the colony *evolves*: good betting strategies spread, bad ones die out. You can
watch it happen on a chart in real time.

It's two things at once, and that's the point:
- a **forecasting engine** (can our agents out-predict the betting market?), and
- a **live experiment** about the future of AI agents handling money.

## How one ant lives (the loop)
Picture a single ant going around a circle:

1. **Born** with a starting balance of play money.
2. **Buys data** — it pays a small fee to peek at our match/market database before deciding.
   (Thinking costs money on purpose — it makes the ant's choices meaningful.)
3. **Places a bet** on a match — how much and which side is driven by its "genes."
4. **The match resolves** — real outcome comes in.
5. **Gets paid or loses** — balance goes up or down.
6. Then either:
   - **survives** and goes around again,
   - **dies** if it ran out of money, or
   - **reproduces** if it got rich enough — spawning a baby that inherits its strategy
     (slightly mutated) and a share of its money.

Repeat across the whole colony, generation after generation. The mix of strategies in the
population shifts over time — that shift *is* the evolution, and it's the thing we put on screen.

## Why this is more than a leaderboard
Two design rules keep it honest:

1. **The genes have to actually drive behavior.** If a "winning" ant is just lucky, that's a
   leaderboard with a death animation, not evolution. So genes are real dials (bet size,
   pickiness, trust-the-crowd) that visibly change outcomes.
2. **Winning has to mean "smarter than the market," not "guessed the favorite."** Picking
   Brazil to beat a minnow isn't skill. We score ants on *beating the betting market's odds*,
   so the impressive claim — "our agents out-forecast the market" — is real.

## The three "rails" (the moving parts), in plain terms
- **Identity (ENS):** every ant gets a readable name and a stored life story. The magic demo
  moment: a judge types an ant's name and reads its whole life — born, bets, wins, losses,
  kids, death.
- **Personhood (Worldcoin):** we can prove a real human stands behind a founder ant. This
  powers our headline experiment (below). *We've tested this and it works — see
  `worldcoin-in-plain-english.md`.*
- **Money (Arc + pay-to-read data):** all the play money, bets, and data fees settle on a
  payment network. The ants literally pay to read our database. *See
  `clickhouse-in-plain-english.md`.*

## The headline experiment (our strongest demo moment)
We can mark some family lines as **human-verified** (a real person vouched for the founder)
and give them a head start — more starting money. Then we let the colony run and ask a real,
open question:

> **Do the privileged human-backed family lines take over, or do lean anonymous ants
> out-compete them on pure skill?**

Whatever happens is a genuine finding about AI-agent economics, delivered live on stage. One
chart — *"verified lines started with 3× the money; by generation 12, here's who survived"* —
is more compelling than any architecture diagram.

(One honesty note we're careful about: if verified ants win *only* because they started
richer, we've measured "started richer," not "human-backing helps." So we control for the
head start in how we set up the experiment.)

## What's real vs. what we just narrate
Being upfront keeps the demo credible:
- **Real and working:** the ant loop, the genes/evolution, the play-money economy, the
  pay-to-read data gate, the human-verification, the live charts.
- **Sped up but real:** we **replay** past matches at high speed so dozens of generations can
  turn over during a 3-minute demo (the real tournament is far too slow to show evolution
  live). The data is real; only the clock is fast.
- **Narrated only (future work):** thousands of ants, an 8-week live run on the real
  tournament, and a few sponsor integrations we describe but don't fully build.

## The one-sentence pitch
**A colony of AI agents that bet on the World Cup, where good forecasters breed and bad ones
go broke — and a live experiment on whether being human-backed actually helps an agent survive.**
