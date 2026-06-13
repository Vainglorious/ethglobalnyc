/**
 * Engine — the single simulation driver. Renders nothing; it owns the one
 * useFrame that advances the world each frame in strict order:
 *   stepSimulation → active SimSource.update → ring-buffer updates → throttled
 *   UI snapshots. Must be the FIRST child in the scene so its frame callback
 *   runs before the renderers read the buffers (all at priority 0 → tree order).
 */

import { useEffect, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { sim } from '../store/simStore'
import { stepSimulation } from '../systems/simulation'
import { commBuffer } from '../systems/commBuffer'
import { flowBuffer } from '../systems/flowBuffer'
import { mulberry32 } from '../utils/math'
import { createWorldSink, type SimSource } from '../data/adapter'
import { LocalSim } from '../data/localSim'
import { JsonlReplay } from '../data/jsonlReplay'
import { useWorldStore, type AntSnapshot } from '../store/worldStore'

export default function Engine() {
  const agentCount = useWorldStore((s) => s.agentCount)
  const dataSource = useWorldStore((s) => s.dataSource)

  const sink = useRef(createWorldSink())
  const local = useRef(new LocalSim())
  const replay = useRef(new JsonlReplay())
  const active = useRef<SimSource>(local.current)

  // (Re)initialize the population whenever the requested count changes.
  useEffect(() => {
    sim.init(agentCount, mulberry32(0x1234 + agentCount))
    // restart the active source against the fresh population
    active.current.stop()
    active.current.start(sink.current)
  }, [agentCount])

  // Switch sources when the user toggles local <-> replay.
  useEffect(() => {
    let cancelled = false
    async function swap() {
      active.current.stop()
      if (dataSource === 'replay') {
        const ok = await replay.current.load()
        if (cancelled) return
        if (ok) {
          active.current = replay.current
          useWorldStore.getState().setReplayActive(true)
        } else {
          // no file → fall back to local, report inactive
          active.current = local.current
          useWorldStore.getState().setDataSource('local')
          useWorldStore.getState().setReplayActive(false)
        }
      } else {
        active.current = local.current
        useWorldStore.getState().setReplayActive(false)
      }
      active.current.start(sink.current)
    }
    void swap()
    return () => {
      cancelled = true
    }
  }, [dataSource])

  // Throttle accumulators for UI-facing updates.
  const fpsAcc = useRef(0)
  const fpsFrames = useRef(0)
  const snapAcc = useRef(0)

  useFrame((_, rawDt) => {
    const dt = rawDt > 0.1 ? 0.1 : rawDt

    stepSimulation(dt)
    active.current.update(dt)
    commBuffer.update(dt)
    flowBuffer.update(dt)

    // ---- throttled UI updates (keep React out of the hot path) ----
    const store = useWorldStore.getState()

    // FPS ~2Hz
    fpsAcc.current += dt
    fpsFrames.current++
    if (fpsAcc.current >= 0.5) {
      store.setFps(Math.round(fpsFrames.current / fpsAcc.current))
      fpsAcc.current = 0
      fpsFrames.current = 0
    }

    // Selected ant snapshot ~8Hz (only while one is selected)
    snapAcc.current += dt
    if (snapAcc.current >= 0.12) {
      snapAcc.current = 0
      const i = store.selectedAnt
      if (i !== null && i < sim.count) {
        const snap: AntSnapshot = {
          index: i,
          agentId: sim.agentIds[i] || sim.names[i],
          name: sim.names[i],
          role: sim.roles[i],
          state: sim.states[i],
          verified: sim.verified[i] === 1,
          bankroll: sim.bankrolls[i],
          accuracy: sim.accuracy[i],
          homeProbability: sim.homeProb[i],
          side: sim.side[i],
          stake: sim.stake[i],
          genomeHash: sim.genomeHashes[i],
          walletAddress: sim.walletAddresses[i],
          generation: sim.generations[i],
        }
        store.setAntSnapshot(snap)
      }
      const c = store.selectedColony
      if (c !== null && c < sim.colonies.length) {
        const col = sim.colonies[c]
        store.setColonySnapshot({
          index: c,
          population: col.population,
          bankroll: col.bankroll,
          accuracy: col.accuracy,
          growthRate: col.growthRate,
          verifiedRatio: col.verifiedRatio,
          health: col.health,
        })
      }
    }
  })

  return null
}
