/**
 * simStore — the non-React simulation state. ALL per-frame agent data lives
 * here in flat typed arrays (Structure-of-Arrays) so the render loop never
 * touches React state. Components read these buffers directly inside useFrame.
 *
 * Now models a real-ant-colony ecosystem: multiple colonies, each with a nest,
 * a queen, brood, food stores, and a dual-channel pheromone field (see
 * systems/pheromone.ts). Agents carry a caste (`tasks`) reassigned by colony
 * need, and a `carrying` flag for the forage loop.
 *
 * Capacity is fixed at construction (MAX_AGENTS); `count` is the active number.
 */

import { Role, AntState, AntTask } from '../data/schema'
import { groundY, terrainHeight, WATER_LEVEL } from '../utils/noise'
import { SpatialHash } from '../systems/spatialHash'

export const MAX_AGENTS = 2048
export const MAX_COLONIES = 4
export const MAX_RESOURCES = 24
export const WORLD_HALF = 220 // world spans [-WORLD_HALF, WORLD_HALF] on X/Z
export const HASH_CELL = 8 // ≈ boids perception radius

/** How many colonies to spawn in the local ecosystem (≤ MAX_COLONIES). */
export const NUM_COLONIES = 3

export interface ColonyData {
  x: number
  z: number
  /** aggregate, updated by domain/replay (0..1 unless noted) */
  population: number
  bankroll: number
  accuracy: number
  growthRate: number
  verifiedRatio: number
  /** 0..1 derived health (wealth+accuracy) for visual intensity */
  health: number
  // --- real-ant-colony state ---
  food: number // stored food (fuels brood)
  brood: number // developing young; matures into new workers
  threat: number // 0..1 recent intrusion pressure (drives soldier allocation)
  /** live caste headcounts, recomputed each tick */
  foragers: number
  soldiers: number
  nurses: number
  scouts: number
  /** per-tick accumulators (internal scratch for aggregates) */
  _bankrollSum: number
  _accSum: number
  _verifiedSum: number
}

export interface ResourceData {
  x: number
  z: number
  y: number
  energy: number // 0..1
  activeWorkers: number
}

/** Side stored as int8: 1 home, -1 away, 0 pass/none. */
export type SideCode = -1 | 0 | 1

class SimStore {
  // --- agent SoA buffers ---
  readonly positions = new Float32Array(MAX_AGENTS * 3)
  readonly velocities = new Float32Array(MAX_AGENTS * 3)
  readonly targets = new Float32Array(MAX_AGENTS * 3)
  readonly roles = new Uint8Array(MAX_AGENTS)
  readonly states = new Uint8Array(MAX_AGENTS)
  readonly tasks = new Uint8Array(MAX_AGENTS) // AntTask (caste)
  readonly carrying = new Uint8Array(MAX_AGENTS) // 1 = hauling food home
  readonly bankrolls = new Float32Array(MAX_AGENTS)
  readonly accuracy = new Float32Array(MAX_AGENTS)
  readonly homeProb = new Float32Array(MAX_AGENTS)
  readonly stake = new Float32Array(MAX_AGENTS)
  readonly side = new Int8Array(MAX_AGENTS)
  readonly verified = new Uint8Array(MAX_AGENTS)
  readonly colonyId = new Uint8Array(MAX_AGENTS)
  readonly phase = new Float32Array(MAX_AGENTS) // animation offset
  readonly highlight = new Float32Array(MAX_AGENTS) // 0..1 transient glow

  /** index -> harness agent_id (filled by replay roster; '' otherwise). */
  readonly agentIds: string[] = new Array(MAX_AGENTS).fill('')
  readonly names: string[] = new Array(MAX_AGENTS).fill('')
  readonly genomeHashes: string[] = new Array(MAX_AGENTS).fill('')
  readonly walletAddresses: string[] = new Array(MAX_AGENTS).fill('')
  readonly generations = new Int16Array(MAX_AGENTS)
  readonly idToIndex = new Map<string, number>()

  count = 0

  readonly colonies: ColonyData[] = []
  readonly resources: ResourceData[] = []

  /** spatial hash, rebuilt each tick by the orchestrator before boids. */
  readonly hash = new SpatialHash(HASH_CELL)

  /** simulation clock (seconds), advanced by the orchestrator. */
  time = 0

  /** find a land position (above the waterline) near a target, else the target. */
  private landNear(x: number, z: number, rand: () => number): [number, number] {
    for (let t = 0; t < 12; t++) {
      const a = rand() * Math.PI * 2
      const r = t * 6
      const nx = x + Math.cos(a) * r
      const nz = z + Math.sin(a) * r
      if (terrainHeight(nx, nz) > WATER_LEVEL + 2) return [nx, nz]
    }
    return [x, z]
  }

  /**
   * Initialize an ecosystem of NUM_COLONIES colonies, each with a queen, a ring
   * of workers, and a starting food/brood store; resources scattered across the
   * whole world and contested between colonies. Deterministic given `rand`.
   */
  init(count: number, rand: () => number) {
    this.count = Math.min(count, MAX_AGENTS)
    this.colonies.length = 0
    this.resources.length = 0
    this.idToIndex.clear()
    this.time = 0

    // --- nests: spread on land around the origin ---
    const nC = Math.min(NUM_COLONIES, MAX_COLONIES)
    for (let c = 0; c < nC; c++) {
      const a = (c / nC) * Math.PI * 2 + 0.4
      const [cx, cz] = this.landNear(Math.cos(a) * 120, Math.sin(a) * 120, rand)
      this.colonies.push({
        x: cx,
        z: cz,
        population: 0,
        bankroll: 100,
        accuracy: 0.5,
        growthRate: 0.5,
        verifiedRatio: 0.18,
        health: 0.6,
        food: 25,
        brood: 10,
        threat: 0,
        foragers: 0,
        soldiers: 0,
        nurses: 0,
        scouts: 0,
        _bankrollSum: 0,
        _accSum: 0,
        _verifiedSum: 0,
      })
    }

    // --- resources scattered across the world (contested) ---
    const RES = Math.min(16, MAX_RESOURCES)
    for (let i = 0; i < RES; i++) {
      const a = (i / RES) * Math.PI * 2 + rand() * 0.5
      const r = 40 + rand() * 170
      let x = Math.cos(a) * r
      let z = Math.sin(a) * r
      ;[x, z] = this.landNear(x, z, rand)
      this.resources.push({
        x,
        z,
        y: groundY(x, z),
        energy: 0.5 + rand() * 0.5,
        activeWorkers: 0,
      })
    }

    // --- agents, assigned round-robin to colonies ---
    for (let i = 0; i < this.count; i++) {
      const i3 = i * 3
      const cid = i % nC
      const colony = this.colonies[cid]
      const a = rand() * Math.PI * 2
      const r = rand() * 18
      const x = colony.x + Math.cos(a) * r
      const z = colony.z + Math.sin(a) * r
      this.positions[i3] = x
      this.positions[i3 + 1] = groundY(x, z) + 1.2
      this.positions[i3 + 2] = z

      const sp = 0.4 + rand() * 0.4
      const va = rand() * Math.PI * 2
      this.velocities[i3] = Math.cos(va) * sp
      this.velocities[i3 + 1] = 0
      this.velocities[i3 + 2] = Math.sin(va) * sp

      this.targets[i3] = x
      this.targets[i3 + 1] = 0
      this.targets[i3 + 2] = z

      // first agent of each colony is its queen; others get a caste by ratio
      const isQueen = i < nC
      if (isQueen) {
        this.tasks[i] = AntTask.Queen
      } else {
        const roll = rand()
        this.tasks[i] =
          roll < 0.55 ? AntTask.Forager : roll < 0.72 ? AntTask.Scout : roll < 0.9 ? AntTask.Nurse : AntTask.Soldier
      }

      // keep the prediction-market Role too (drives the existing economy/UI)
      const rRoll = rand()
      this.roles[i] =
        rRoll < 0.5
          ? Role.Worker
          : rRoll < 0.72
            ? Role.Explorer
            : rRoll < 0.9
              ? Role.Carrier
              : rRoll < 0.97
                ? Role.Builder
                : Role.Messenger

      this.states[i] = AntState.Wander
      this.carrying[i] = 0
      this.bankrolls[i] = 92 + rand() * 16
      this.accuracy[i] = 0.35 + rand() * 0.3
      this.homeProb[i] = 0.45 + rand() * 0.1
      this.stake[i] = 0
      this.side[i] = 0
      this.verified[i] = rand() < 0.18 ? 1 : 0
      this.colonyId[i] = cid
      this.phase[i] = rand() * Math.PI * 2
      this.highlight[i] = 0
      this.agentIds[i] = ''
      this.names[i] = `ant-${i.toString().padStart(4, '0')}`
      this.genomeHashes[i] = ''
      this.walletAddresses[i] = ''
      this.generations[i] = 0
    }
  }
}

/** Module singleton. */
export const sim = new SimStore()
