# Worldcoin Rail — TODO

Owner: dev C (ENS offchain resolver, World ID, lineage records — plan §5).

## P0 — verification
- [ ] World ID verify flow → `nullifier_hash`.
- [ ] Nullifier registry: reject any human already used as a lineage root (one per human).

## P1 — privilege grant
- [ ] `grantLineageRoot`: birth bankroll multiplier (~3x) + `data_tier: premium` flag.
- [ ] Hand `verified` + tier to ENS lineage text records (coordinate with ENS rail).
- [ ] ClickHouse rail reads `data_tier` to unlock premium query tier.

## P2 — the experiment (the actual deliverable, plan §8)
- [ ] Cohort design: verified vs. anonymous.
- [ ] Survival-chart data feed (live-updating: bankroll/survival by generation).
- [ ] Bankroll-control variant so the result isn't just "started richer" (plan §6 Q5).
- [ ] Decide: simulate extra verified lineages to raise N? If so, label as simulated.

## Notes
- One proof per human. Verification attaches to a LINEAGE, never per-ant.
- The survival chart is the demo's strongest moment — prioritize it over static viz.
