/**
 * domain.ts — the MEANING behind the motion, now a real ant-colony model:
 *
 *   • Foraging loop: searching ants pick up food at resources → carry home →
 *     deposit into the colony food store. (Movement/trail-following is boids.ts.)
 *   • Brood & growth: queens convert stored food into brood; nurses mature brood
 *     into new workers, so colonies grow (and starve back) with their food supply.
 *   • Division of labor: castes are reassigned by colony need (low food → more
 *     foragers, threat → more soldiers, brood → more nurses) via response
 *     thresholds.
 *   • Per-colony aggregates (population/wealth/accuracy/health) + the legacy
 *     prediction-market economy (stake/bankroll/accuracy) for the existing UI.
 *
 * Writes `states`, `tasks`, `carrying`, `targets` (only for homing ants),
 * domain scalar arrays, and the ColonyData aggregates. boids.ts turns the rest
 * into movement using the pheromone field.
 */

import { sim, MAX_AGENTS } from '../store/simStore'
import { Role, AntState, AntTask } from '../data/schema'
import { mulberry32, clamp } from '../utils/math'
import { findDryLandNear, groundY } from '../utils/noise'
import { pher } from './pheromone'

const rng = mulberry32(0xc0ffee)

const RESOURCE_REACH_SQ = 6 * 6
const NEST_REACH = 14
const NEST_REACH_SQ = NEST_REACH * NEST_REACH
const BITE = 0.02 // energy removed per pickup
const RESPAWN_RATE = 0.012 // resource energy regained per second
const FOOD_PER_HAUL = 1 // food added to colony store per delivered load
const UPKEEP = 0.018 // food consumed per ant per second
const BROOD_FEED = 0.6 // food → brood conversion rate (×nurse factor)
const MATURE_RATE = 0.5 // brood maturation chance/sec (×nurse factor)

function setTarget(i: number, x: number, z: number) {
  const i3 = i * 3
  sim.targets[i3] = x
  sim.targets[i3 + 2] = z
}

function nearestResource(px: number, pz: number): number {
  let best = -1
  let bestD = Infinity
  const R = sim.resources
  for (let r = 0; r < R.length; r++) {
    if (R[r].energy < 0.05) continue
    const dx = R[r].x - px
    const dz = R[r].z - pz
    const d = dx * dx + dz * dz
    if (d < bestD) {
      bestD = d
      best = r
    }
  }
  return best
}

/** Spawn a matured worker at colony `cid`'s nest. Returns true if spawned. */
function spawnWorker(cid: number): boolean {
  if (sim.count >= MAX_AGENTS) return false
  const i = sim.count
  const i3 = i * 3
  const colony = sim.colonies[cid]
  const a = rng() * Math.PI * 2
  const r = rng() * 6
  const [x, z] = findDryLandNear(colony.x + Math.cos(a) * r, colony.z + Math.sin(a) * r, rng, 1.4)
  sim.positions[i3] = x
  sim.positions[i3 + 1] = groundY(x, z)
  sim.positions[i3 + 2] = z
  sim.velocities[i3] = Math.cos(a) * 0.5
  sim.velocities[i3 + 1] = 0
  sim.velocities[i3 + 2] = Math.sin(a) * 0.5
  sim.targets[i3] = x
  sim.targets[i3 + 2] = z
  // newborns start as foragers or nurses
  sim.tasks[i] = rng() < 0.6 ? AntTask.Forager : AntTask.Nurse
  sim.roles[i] = rng() < 0.6 ? Role.Worker : Role.Carrier
  sim.states[i] = AntState.Wander
  sim.carrying[i] = 0
  sim.bankrolls[i] = 90
  sim.accuracy[i] = 0.4 + rng() * 0.2
  sim.homeProb[i] = 0.5
  sim.stake[i] = 0
  sim.side[i] = 0
  sim.verified[i] = 0
  sim.colonyId[i] = cid
  sim.phase[i] = rng() * Math.PI * 2
  sim.highlight[i] = 0
  sim.names[i] = `ant-${i.toString().padStart(4, '0')}`
  sim.generations[i] = 1
  sim.count++
  return true
}

/** Reassign one ant's caste toward the colony's most-deficient need. */
function reallocate(i: number, cid: number) {
  if (sim.tasks[i] === AntTask.Queen) return
  const c = sim.colonies[cid]
  const pop = Math.max(1, c.population)
  // desired fractions from need
  const wantSoldier = 0.08 + c.threat * 0.3
  const wantNurse = 0.1 + clamp(c.brood / (pop * 0.6), 0, 1) * 0.25
  const wantScout = 0.12
  const wantForager = clamp(1 - wantSoldier - wantNurse - wantScout, 0.2, 0.8)
  // current fractions
  const fS = c.soldiers / pop
  const fN = c.nurses / pop
  const fSc = c.scouts / pop
  const fF = c.foragers / pop
  // largest deficit wins
  let task = AntTask.Forager
  let deficit = wantForager - fF
  if (wantSoldier - fS > deficit) {
    deficit = wantSoldier - fS
    task = AntTask.Soldier
  }
  if (wantNurse - fN > deficit) {
    deficit = wantNurse - fN
    task = AntTask.Nurse
  }
  if (wantScout - fSc > deficit) {
    deficit = wantScout - fSc
    task = AntTask.Scout
  }
  if (deficit > 0.05) {
    sim.tasks[i] = task
    if (sim.carrying[i] && task !== AntTask.Forager) sim.carrying[i] = 0
  }
}

export function updateDomain(dt: number) {
  const { positions: P, states, colonies, resources, count } = sim
  if (colonies.length === 0) return

  // keep the pheromone fields sized to the colony set
  if (pher.nColonies !== colonies.length) pher.reset(colonies.length)

  // resource regrowth + reset per-tick worker counts
  for (let r = 0; r < resources.length; r++) {
    resources[r].energy = clamp(resources[r].energy + RESPAWN_RATE * dt, 0, 1)
    resources[r].activeWorkers = 0
  }

  // reset per-colony per-tick accumulators
  for (let c = 0; c < colonies.length; c++) {
    const col = colonies[c]
    col.population = 0
    col.foragers = 0
    col.soldiers = 0
    col.nurses = 0
    col.scouts = 0
    col.threat = Math.max(0, col.threat - dt * 0.15)
    col._bankrollSum = 0
    col._accSum = 0
    col._verifiedSum = 0
  }

  for (let i = 0; i < count; i++) {
    const i3 = i * 3
    const px = P[i3]
    const pz = P[i3 + 2]
    const cid = sim.colonyId[i]
    const colony = colonies[cid]
    if (!colony) continue
    const task = sim.tasks[i] as AntTask

    if (sim.highlight[i] > 0) sim.highlight[i] = Math.max(0, sim.highlight[i] - dt * 1.6)

    // tally castes / aggregates
    colony.population++
    colony._bankrollSum += sim.bankrolls[i]
    colony._accSum += sim.accuracy[i]
    colony._verifiedSum += sim.verified[i]
    if (task === AntTask.Forager) colony.foragers++
    else if (task === AntTask.Soldier) colony.soldiers++
    else if (task === AntTask.Nurse) colony.nurses++
    else if (task === AntTask.Scout) colony.scouts++

    // --- behavior ---
    if (task === AntTask.Queen) {
      setTarget(i, colony.x, colony.z)
      states[i] = AntState.Wander
    } else if (task === AntTask.Nurse) {
      // tend brood at the nest
      const dx = colony.x - px
      const dz = colony.z - pz
      if (dx * dx + dz * dz > NEST_REACH_SQ) setTarget(i, colony.x, colony.z)
      states[i] = AntState.Wander
    } else if (task === AntTask.Soldier) {
      // patrol the territory rim; intruders are handled in boids (repel)
      states[i] = AntState.Wander
    } else {
      // Forager / Scout — the forage loop
      if (sim.carrying[i]) {
        states[i] = AntState.Carrying
        setTarget(i, colony.x, colony.z)
        const dx = colony.x - px
        const dz = colony.z - pz
        if (dx * dx + dz * dz < NEST_REACH_SQ) {
          // deliver
          colony.food += FOOD_PER_HAUL
          sim.carrying[i] = 0
          sim.bankrolls[i] = clamp(sim.bankrolls[i] + sim.stake[i] * 2, 0, 1000)
          sim.accuracy[i] = clamp(sim.accuracy[i] + (rng() - 0.45) * 0.01, 0.05, 0.95)
          sim.stake[i] = 0
          states[i] = AntState.Wander
        }
      } else {
        states[i] = AntState.SeekResource
        const r = nearestResource(px, pz)
        if (r >= 0) {
          const res = resources[r]
          const dx = res.x - px
          const dz = res.z - pz
          const d2 = dx * dx + dz * dz
          if (d2 < RESOURCE_REACH_SQ) {
            res.energy = clamp(res.energy - BITE, 0, 1)
            res.activeWorkers++
            sim.carrying[i] = 1
            sim.stake[i] = 0.3 + rng() * 0.7
            states[i] = AntState.Carrying
            setTarget(i, colony.x, colony.z)
          }
          // else: boids follows the TO_FOOD trail / wanders toward known food
        }
      }
    }

    // gentle homeProb drift (prediction-market liveliness)
    sim.homeProb[i] = clamp(sim.homeProb[i] + (rng() - 0.5) * 0.04 * dt, 0.05, 0.95)

    // occasional caste reallocation by need
    if (rng() < 0.15 * dt) reallocate(i, cid)
  }

  // --- per-colony economy: brood, growth, upkeep, aggregates ---
  for (let c = 0; c < colonies.length; c++) {
    const col = colonies[c]
    const pop = Math.max(1, col.population)

    // upkeep drains food with population
    col.food = Math.max(0, col.food - UPKEEP * pop * dt)

    // queen feeds brood from food, scaled by nurse coverage
    const nurseFactor = clamp(col.nurses / (pop * 0.15 + 1), 0.3, 1.6)
    const feed = Math.min(col.food, BROOD_FEED * nurseFactor * dt)
    col.food -= feed
    col.brood += feed * 0.8

    // brood matures into new workers (nurse-accelerated)
    if (col.brood >= 1 && rng() < MATURE_RATE * nurseFactor * dt) {
      if (spawnWorker(c)) col.brood -= 1
    }

    // aggregates
    col.bankroll = col._bankrollSum / pop
    col.accuracy = col._accSum / pop
    col.verifiedRatio = col._verifiedSum / pop
    const wealthNorm = clamp((col.bankroll - 80) / 60, 0, 1)
    const foodNorm = clamp(col.food / (pop * 2), 0, 1)
    col.health = clamp(wealthNorm * 0.3 + col.accuracy * 0.3 + foodNorm * 0.4, 0, 1)
    col.growthRate = clamp(foodNorm, 0, 1)
  }
}
