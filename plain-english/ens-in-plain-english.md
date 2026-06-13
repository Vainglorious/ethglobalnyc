# The ant's name and life story (ENS), in plain English

*For the product side. This is the "every ant has a readable name card" part.*

## The idea
Every ant gets a human-readable name like **`bob-d7.colony.eth`** — and attached to that name is
its **whole life story**: which generation it is, who its parent was, whether it's human-verified,
how much money it has, how accurate its forecasts are, whether it's alive or dead, and its
"genes." Anyone can look up the name and read all of that.

## The demo moment
A judge types **`bob-d7.colony.eth`** into a normal ENS name-lookup tool and instantly sees the
ant's entire life laid out — no special access, just a public name anyone can resolve. That's the
"wow, these agents are real citizens with histories" moment.

## Why we do it the "gasless" way (the important choice)
Normally, registering a name on Ethereum costs a fee and takes time. With **thousands of ants
being born, updated every round, and dying**, paying a fee each time would be far too slow and
expensive. So we use an **offchain** approach: the names and their life-stories live on our own
fast service, but still resolve through the real ENS system. **Free to create, instant to update,
still publicly real.** We're committed to this approach and won't fall back to the slow/expensive
way under time pressure.

## How it stays truthful
- The life-story records get **updated every round** straight from the colony's brain (bankroll,
  accuracy, alive/dead, etc.).
- When an ant **reproduces**, its child gets a new name pointing back to the parent.
- When an ant **dies**, we mark it dead but **never delete it** — the point is the history.
- One subtle rule: "verified human" is a property of a **family line**, set once at the root (one
  real person), not stamped onto every individual ant.

## Where it stands
This is a defined plan with a clear owner and starter scaffolding in place; the core piece to
build is the service that serves each ant's records on demand. The one must-pass check: it has to
work in the **exact public tool the judges use**, not just on our laptops.

## One-line summary
**Every ant has a public, readable name whose records tell its whole life story — created for
free, updated every round, and resolvable by anyone, including the judges.**
