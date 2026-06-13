# Worldcoin Rail — proof-of-personhood at the lineage root

The **identity-privilege plane** of Colony. World ID gates **lineage roots**: one proof
per human seeds one founding ant, and verified lineages start with a bigger bankroll and
a premium data tier. This rail powers the demo's strongest moment — the live experiment:

> *Over generations, do privileged human-verified lineages dominate, or do lean anonymous
> ants out-compete them on pure skill?* (plan §8)

This folder is scaffolding only — interface + TODOs, no committed language yet.
See `../colony/README.md` and `../notes/colony-hackathon-plan (1).md` §3 (Worldcoin row), §8.

## The core constraint (do not violate)

**One proof per human.** You CANNOT mint many verified ants from one human — that is the
entire point of proof-of-personhood. Verification attaches to a **lineage**, never to each
ant (plan §3, §7). Real N is therefore limited by real humans at the event.

## What this rail owns

1. **World ID verification** of a human → mint/flag one **lineage root**.
2. **Privilege grants** for verified lineages: larger birth bankroll + premium ClickHouse
   data tier (`../clickhouse/README.md`).
3. **The experiment harness:** verified vs. anonymous cohorts, and the survival chart that
   is the demo centerpiece.

## Interface contract (strawman — confirm with rail owner C)

```text
verifyHuman(worldid_proof) -> { verified: bool, nullifier_hash }
  # nullifier_hash is the one-per-human key; reject if already used for a root.

grantLineageRoot(nullifier_hash) -> {
    lineage_id,
    tier: "verified",
    birth_bankroll_multiplier,   # e.g. 3x (plan §8: "3x bankroll")
    data_tier: "premium"
}
```

- The grant is consumed by **Birth** in the colony loop and by ENS lineage records
  (verified flag in text records — plan §3, ENS row).
- The `data_tier` is read by the ClickHouse rail to unlock the premium query tier.

## The experiment (this is the deliverable, not just a feature)

- **Confound to control for (plan §6 Q5 / §7):** if verified ants win only because they
  started richer, you measured *starting capital*, not human-backing. Use matched cohorts
  or normalize by starting capital so the chart measures something real.
- **N problem:** real humans are few. If you simulate extra verified lineages to lift N,
  label them clearly as simulated.
- **The chart:** *"verified lineages started with 3× bankroll; by generation 12, here's who
  survived."* One live-updating survival chart beats any architecture slide (plan §8).

## Build order

- [ ] World ID verify flow → nullifier_hash, reject double-use.
- [ ] Lineage-root grant (bankroll multiplier + premium data tier flag).
- [ ] Write `verified` + tier into ENS lineage text records (coordinate with ENS rail).
- [ ] Cohort design + the survival chart data feed (verified vs. anon).
- [ ] Bankroll-control variant so the experiment isn't confounded.

## Open questions (blocking)

- How many real humans can we verify at the event? (sets real N — plan §6 Q5)
- Do we simulate extra verified lineages to raise N, and how do we label them?
- Exact privilege values (bankroll multiplier, what "premium tier" actually unlocks)?

## TODO stubs to add next

```text
worldcoin/
  README.md            # this file
  verify/              # World ID proof verification + nullifier registry
  lineage/             # root grant: bankroll multiplier + data tier
  experiment/          # cohort design, survival chart feed, bankroll control
```
