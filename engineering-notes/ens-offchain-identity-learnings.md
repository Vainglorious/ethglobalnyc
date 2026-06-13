# ENS — Offchain Lineage Identity (plan & handoff) (2026-06-13)

*The ant identity plane: a gasless ENS subname per ant whose text records hold its whole life
story. Engineering record / handoff (owner: Tanguy; path `ens/`).*

## The goal (one line)
Give every ant a **gasless ENS identity** — an **offchain (CCIP-Read)** subname under
`colony.eth` whose text records hold the ant's entire life story. Demo moment: a judge resolves
`bob-d7.colony.eth` in a real ENS tool and reads generation, parent, verified flag, bankroll,
accuracy, alive/dead, and genome straight off the records.

## Why offchain (hold the line on this)
Onchain minting one subname per ant = gas + latency and will **not** survive thousands of
generations or per-round record updates. Use an offchain **CCIP-Read resolver (durin-style)** so
subnames are gasless and updatable every round. The plan flags "reverting to onchain ENS minting
under time pressure" as a footgun — decide offchain **now**.

## Task list (rough priority)
1. **Confirm the namespace** — lock the parent (`colony.eth` or whatever we control), the subname
   format (e.g. `{name}-{gen}.colony.eth`), and that we can set an offchain resolver on the parent.
2. **Stand up the offchain CCIP-Read resolver** (core deliverable) — durin-style gateway: resolver
   contract → HTTP gateway that signs answers; **wildcard** resolution for `*.colony.eth` (no
   per-ant mint); a signer key serves text records on demand.
3. **Define the text-record schema** (agree with colony + frontend). Suggested keys:
   `colony.generation`, `colony.parent`, `colony.verified` (Worldcoin lineage flag),
   `colony.bankroll`, `colony.accuracy`, `colony.status` (alive/dead), `colony.genome`
   (encoded; harness exposes only a **hash** while alive — plaintext on death), `colony.arc_address`.
4. **Write path** — update records every round from harness output
   (`events.compact.jsonl` / `agent_record` events). Idempotent + fast (fires for many ants/round).
5. **Lineage / reproduction** — on reproduce: child subname + parent record + mutated genome +
   reflect USDC inheritance. On death: set `colony.status=dead` (never delete — the life story is
   the point).
6. **Cross-plane binding** — ant lives on Arc, named on Ethereum; keep `arc_address` in the record
   and verify the two never drift.
7. **Verify against the EXACT tool judges use** — the offchain resolver must clear the ENS prize's
   "real resolution" bar in the public tool (e.g. app.ens.domains), not just locally. Test early.

## Footguns (from plan §7)
- Onchain-minting relapse under crunch — **stay offchain.**
- Cross-chain identity drift (Arc address vs ENS name) — keep in sync.
- World ID uniqueness — `colony.verified` is a **lineage-root** property (one proof per human),
  never minted fresh per child. Coordinate with the Worldcoin owner.
- "ENS name doesn't resolve publicly" on demo day — test the resolve-and-read flow in the judges'
  tool.

## Scope for 36 hours
**Build for real:** offchain subnames + lineage in text records, resolving **publicly** — that's
the ENS deliverable. **Narrated only:** thousands of ants, 8-week live run, Arc mainnet. Population
is tens, replay clock accelerated.

## Dependencies
- **Colony harness** — source of genomes/bankroll/accuracy/alive-dead/lineage; agree the record
  schema + data bridge (`events.compact.jsonl` is the existing contract).
- **Worldcoin owner** — how the verified-lineage flag is set at the lineage root.
- **Arc owner** — where the ant's wallet address comes from (`arc_address`).
- **Frontend owner** — agree subname format + record keys so both sides match.

## Scaffolding in place
`ens/README.md` (handoff, points back here), `ens/.env.example` (parent name, RPC, resolver
gateway + signer, ENS owner key, Arc binding). Everything else is to be built.
