/**
 * adapter.ts — the seam that decouples the visuals from where events come from.
 *
 * A `SimSource` emits domain events over time through an `EventSink`. The live
 * client simulation (localSim) and the harness replay (jsonlReplay) are both
 * SimSources; the renderer never knows which is active. The `EventSink` turns
 * events into concrete world effects: comm pulses, stake flows, colony updates,
 * and binding real per-agent stats onto sim indices.
 */

import { sim, type SideCode } from '../store/simStore'
import type { ColonyData } from '../store/simStore'
import type { AgentRecord } from './schema'
import { commBuffer } from '../systems/commBuffer'
import { flowBuffer } from '../systems/flowBuffer'

export interface EventSink {
  /** debate claim: pulse from agent `fromIndex` to `toIndex` (-1 = colony). */
  comm(fromIndex: number, toIndex: number, hue: number): void
  /** forecast: stake flow between agent and colony. */
  stake(agentIndex: number, side: SideCode, amount: number, win: boolean): void
  /** round summary / aggregate update. */
  updateColony(patch: Partial<ColonyData>): void
  /** roster export: attach real stats to a sim index by agent_id. */
  bindAgent(record: AgentRecord): void
}

export interface SimSource {
  readonly id: 'local' | 'replay' | 'ws'
  /** called once when the source becomes active. */
  start(sink: EventSink): void
  /** advance the source by dt seconds (emits events through the sink). */
  update(dt: number): void
  stop(): void
}

/** Resolve the world position of an agent index into out[0..2]. */
function agentPos(index: number, out: [number, number, number]) {
  const i3 = index * 3
  out[0] = sim.positions[i3]
  out[1] = sim.positions[i3 + 1]
  out[2] = sim.positions[i3 + 2]
}

const _a: [number, number, number] = [0, 0, 0]

/** Default sink: writes straight into the ring buffers + sim store. */
export function createWorldSink(): EventSink {
  return {
    comm(fromIndex, toIndex, hue) {
      if (fromIndex < 0 || fromIndex >= sim.count) return
      agentPos(fromIndex, _a)
      const fx = _a[0]
      const fy = _a[1] + 1.2
      const fz = _a[2]
      let tx: number, ty: number, tz: number
      if (toIndex < 0) {
        const c = sim.colonies[0]
        tx = c.x
        ty = 6
        tz = c.z
      } else {
        agentPos(toIndex, _a)
        tx = _a[0]
        ty = _a[1] + 1.2
        tz = _a[2]
      }
      commBuffer.spawn(fx, fy, fz, tx, ty, tz, hue)
      sim.highlight[fromIndex] = 1
    },

    stake(agentIndex, side, amount, win) {
      if (agentIndex < 0 || agentIndex >= sim.count) return
      agentPos(agentIndex, _a)
      const c = sim.colonies[0]
      flowBuffer.spawn(_a[0], _a[1] + 1, _a[2], c.x, 5, c.z, side, amount, win)
    },

    updateColony(patch) {
      const c = sim.colonies[0]
      if (!c) return
      Object.assign(c, patch)
    },

    bindAgent(record) {
      let index = sim.idToIndex.get(record.agent_id)
      if (index === undefined) {
        // bind to the next unbound slot within the active population
        index = sim.idToIndex.size
        if (index >= sim.count) return
        sim.idToIndex.set(record.agent_id, index)
        sim.agentIds[index] = record.agent_id
      }
      sim.names[index] = record.name
      sim.genomeHashes[index] = record.genome_hash
      sim.walletAddresses[index] = record.wallet_address || ''
      sim.generations[index] = record.generation
      sim.bankrolls[index] = record.bankroll
      sim.accuracy[index] = record.accuracy
      sim.verified[index] = record.genome_hash.charCodeAt(0) % 5 === 0 ? 1 : sim.verified[index]
    },
  }
}
