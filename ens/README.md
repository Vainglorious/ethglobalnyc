# ENS — Identity Plane

> 👋 **This one's yours, Tanguy.**
>
> This folder is intentionally blank scaffolding. It's where the ENS identity
> plane lives: gasless offchain (CCIP-Read) subnames under `colony.eth`, with
> each ant's whole life story (generation, parent, verified flag, bankroll,
> accuracy, alive/dead, encoded genome) written into ENS text records.
>
> The "money shot" for the ENS prize: a judge resolves `bob-d7.colony.eth` in a
> real ENS tool and reads the ant's entire life off its text records.

## Where to start

1. Read the ENS section of the hackathon plan: `../notes/colony-hackathon-plan.md`
   (§1 Identity plane, §3 sponsor map, §6 open decision #8, §7 footguns).
2. Read the task list: `../notes/2026-06-13-ens-todo.txt`.
3. `cp .env.example .env` and fill it in (keep `.env` out of git).
4. Build your stuff in this folder. Document as you go right here in this README.

## How this plugs into the rest

- The colony harness (`../colony/`) is the brain that produces ants + genomes +
  life stats. ENS is where that identity is *named and published*.
- The frontend (`../frontend/`) will eventually want to show lineage / resolve
  names. Decide the subname format and record schema early so both sides agree.
- The ant's wallet lives on **Arc** but is *named* on **Ethereum/ENS** — keep
  the Arc address inside the ENS records and don't let them drift.

---

_TODO (Tanguy): replace this scaffold with real setup, architecture, and run
instructions as you build._
