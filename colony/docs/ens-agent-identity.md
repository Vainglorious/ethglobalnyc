# ENS Agent Identity Pipeline

Colony uses ENS as the public identity layer for ant agents.

The important separation is:

1. **Local identity assignment**: every generated ant gets a wallet address and a deterministic ENS name.
2. **Identity record export**: the roster is written as ENSIP-26-ready records.
3. **On-chain publication**: selected records are registered as ENSv2 subnames and written to the agent resolver.

This keeps the simulation usable before spending gas, while making the on-chain demo a real extension of the same data.

## Identity Model

Each ant has:

```text
agent_id        ant_0001
wallet_address  0x2D84...
ens_name        root-onyx-1.colonny.eth
generation      0
lineage         root-onyx-1.colonny.eth
world_status    unverified
```

Generation-0 ants are lineage roots. Children receive their own ENS names but point back to their parent and lineage root:

```text
gold-lens-42.colonny.eth
  parent  = root-fable-0.colonny.eth
  lineage = root-fable-0.colonny.eth
  world   = inherited_verified
```

Wallets are local throwaway EVM wallets stored in `colony/secrets/agent-wallets.local.json`, which is gitignored. Only public addresses and ENS names are exported.

## Generation Flow

Generate agents with wallets and ENS names:

```bash
python3 colony/run_demo.py \
  --agents 4 \
  --agent-wallets \
  --ens-parent colonny.eth \
  --verified-root ant_0000 \
  --identity-out colony/data/ens-identities.demo.json \
  --show-roster
```

During generation:

```text
AntAgent.wallet_address is assigned/reused from the local wallet store.
AntAgent.ens_name is deterministically assigned from the ENS parent.
The public roster includes both wallet_address and ens_name.
The identity JSON contains the records that can later be published on-chain.
```

The ENS name is deterministic, so the same agent under the same parent gets the same name across runs.

## ENSIP-26 Records

Each exported identity has:

```text
addr                 the ant wallet address
agent-context        JSON identity card for agent discovery
agent-endpoint[web]  web/profile URL
com.colony.*         compact Colony-specific indexes
```

The `agent-context` record is the canonical machine-readable entrypoint:

```json
{
  "schema": "ensip-26",
  "kind": "colony_ant",
  "agent_id": "ant_0001",
  "ens_name": "root-onyx-1.colonny.eth",
  "wallets": {
    "evm": "0x2D84...",
    "arc_testnet": "0x2D84..."
  },
  "generation": 0,
  "parent": "",
  "lineage": "root-onyx-1.colonny.eth",
  "world_status": "unverified",
  "capabilities": ["stats_scout", "forecast", "debate", "trade"]
}
```

## ENSv2 Publication

Names created in `app.ens.dev` are ENSv2 names. ENSv2 needs two one-time pieces before subnames can be created:

1. A per-owner permissioned resolver.
2. A subregistry attached to the parent name.

The publisher handles both automatically.

Check the parent:

```bash
python3 colony/register_ens_identities.py \
  colony/data/ens-identities.demo.json \
  --check-parent \
  --ens-version v2
```

Expected ready state:

```text
Parent:      colonny.eth
Version:     v2
Controller:  0xa569...
Subregistry: 0x0C15...
Ready:       yes
```

Publish one ant:

```bash
python3 colony/register_ens_identities.py \
  colony/data/ens-identities.demo.json \
  --agent-id ant_0001 \
  --ens-version v2 \
  --broadcast
```

The first ENSv2 publish for a parent may send up to five transactions:

```text
deploy owner resolver
deploy parent subregistry
attach subregistry to parent
register ant subname
write resolver records
```

After the parent is ready, each new ant normally needs two transactions:

```text
register ant subname
write resolver records
```

Already registered ENSv2 subnames are skipped for the create step, so the script can safely continue a partial publication run.

## Verified Lineages

World ID verification is attached to lineage roots, not every descendant.

```bash
python3 colony/run_demo.py \
  --agent-wallets \
  --ens-parent colonny.eth \
  --verified-root ant_0000 \
  --world-human-id world_pseudonymous_root \
  --identity-out colony/data/ens-identities.demo.json
```

The root gets:

```text
com.colony.world = verified_root
```

Descendants inherit:

```text
com.colony.world = inherited_verified
```

## ENSIP-25 Later

ENSIP-25 should be added once Colony has an on-chain agent registry.

Future flow:

```text
ColonyAgentRegistry:
  ant_0001 -> root-onyx-1.colonny.eth

ENS text record:
  agent-registration[<registry>][ant_0001] = 1
```

Until that registry exists, ENSIP-26 is the right standard to implement first.
