/**
 * boids.ts — MOVEMENT. Turns each ant's caste + carrying state + the pheromone
 * field into steering, then integrates. Real-ant behaviors:
 *   • Forager searching → climbs the TO_FOOD trail (else weak sight-seek / wander),
 *     laying TO_HOME so it can find the way back.
 *   • Forager/Scout carrying → heads to the nest laying a strong TO_FOOD trail,
 *     so nestmates are recruited to the find (trails self-reinforce).
 *   • Scout → roams wide to discover resources and seed fresh trails.
 *   • Nurse/Queen → stay in the nest.
 *   • Soldier → patrols the territory rim and chases foreign intruders.
 *   • Territory → ants are repelled from rival nests, so colonies separate.
 * Crowding (separation) and soft world bounds apply to everyone.
 *
 * Allocation-free per frame: module-scoped scalars + one reusable dir buffer.
 */

import { sim, WORLD_HALF } from '../store/simStore'
import { groundY, isDryLand, WATER_LEVEL } from '../utils/noise'
import { AntTask } from '../data/schema'
import { mulberry32 } from '../utils/math'
import { pher, TO_FOOD, TO_HOME } from './pheromone'

const rng = mulberry32(0xa117)

const PERCEPTION_SQ = 8 * 8
const SEPARATION = 3.2
const SEPARATION_SQ = SEPARATION * SEPARATION
const BOUNDS = WORLD_HALF * 0.94

const W_SEP = 1.8
const W_SEEK = 1.1
const W_TRAIL = 1.4
const W_WANDER = 0.7

const SIGHT = 52 // forager can see a resource within this range to head for it
const TERRITORY = 64 // rival-nest repulsion / patrol radius
const TERRITORY_SQ = TERRITORY * TERRITORY

const BASE_SPEED = 9
const MAX_FORCE = 26
const DRY_LEVEL = WATER_LEVEL + 0.7
const WATER_LOOKAHEAD = 10

// caste cruising-speed multipliers
const TASK_SPEED: Record<AntTask, number> = {
  [AntTask.Queen]: 0.25,
  [AntTask.Forager]: 1.0,
  [AntTask.Scout]: 1.5,
  [AntTask.Nurse]: 0.5,
  [AntTask.Soldier]: 1.15,
}

const _dir = new Float32Array(2)
const DRY_DIRS = 12

function nearestVisibleResource(px: number, pz: number): number {
  let best = -1
  let bestD = SIGHT * SIGHT
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

export function updateBoids(dt: number) {
  const { positions: P, velocities: V, targets: T, count, colonies } = sim

  for (let i = 0; i < count; i++) {
    const i3 = i * 3
    const px = P[i3]
    const pz = P[i3 + 2]
    const vx = V[i3]
    const vz = V[i3 + 2]
    const cid = sim.colonyId[i]
    const colony = colonies[cid]
    if (!colony) continue
    const task = sim.tasks[i] as AntTask
    const carrying = sim.carrying[i] === 1

    let ax = 0
    let az = 0

    // --- separation (crowding) from close neighbors ---
    sim.hash.forEachNeighbor(px, pz, (j) => {
      if (j === i) return
      const j3 = j * 3
      const dx = px - P[j3]
      const dz = pz - P[j3 + 2]
      const d2 = dx * dx + dz * dz
      if (d2 > PERCEPTION_SQ || d2 === 0) return
      if (d2 < SEPARATION_SQ) {
        const inv = 1 / d2
        ax += dx * inv * 2
        az += dz * inv * 2
      }
      // soldiers chase foreign intruders near them
      if (task === AntTask.Soldier && sim.colonyId[j] !== cid) {
        ax += (P[j3] - px) * 0.05
        az += (P[j3 + 2] - pz) * 0.05
      }
    })
    ax *= W_SEP
    az *= W_SEP

    // --- caste behavior ---
    if (task === AntTask.Queen || task === AntTask.Nurse) {
      // stay home — seek the (nest) target domain assigned
      const tx = T[i3] - px
      const tz = T[i3 + 2] - pz
      const td = Math.hypot(tx, tz)
      if (td > 0.001) {
        ax += (tx / td) * W_SEEK * BASE_SPEED
        az += (tz / td) * W_SEEK * BASE_SPEED
      }
    } else if (task === AntTask.Soldier) {
      // patrol the territory rim: orbit the nest at ~TERRITORY*0.7
      const dx = px - colony.x
      const dz = pz - colony.z
      const d = Math.hypot(dx, dz) || 1
      const ringErr = TERRITORY * 0.7 - d
      ax += (-dx / d) * ringErr * 0.04 + (-dz / d) * 0.0 // pull toward ring radius
      az += (-dz / d) * ringErr * 0.04
      // tangential drift to circle the nest
      ax += (-dz / d) * BASE_SPEED * 0.4
      az += (dx / d) * BASE_SPEED * 0.4
    } else {
      // Forager / Scout — the forage loop
      if (carrying) {
        // home along the target (nest), depositing a strong food trail
        const tx = colony.x - px
        const tz = colony.z - pz
        const td = Math.hypot(tx, tz) || 1
        ax += (tx / td) * W_SEEK * BASE_SPEED
        az += (tz / td) * W_SEEK * BASE_SPEED
        pher.deposit(cid, TO_FOOD, px, pz, 6 * dt) // strong food trail home
      } else {
        // searching: follow the food trail, else sight-seek, else wander
        const onTrail = task === AntTask.Forager && pher.gradient(cid, TO_FOOD, px, pz, vx, vz, _dir)
        if (onTrail) {
          ax += _dir[0] * W_TRAIL * BASE_SPEED
          az += _dir[1] * W_TRAIL * BASE_SPEED
        } else {
          const r = task === AntTask.Forager ? nearestVisibleResource(px, pz) : -1
          if (r >= 0) {
            const res = sim.resources[r]
            const dx = res.x - px
            const dz = res.z - pz
            const d = Math.hypot(dx, dz) || 1
            ax += (dx / d) * W_SEEK * BASE_SPEED * 0.7
            az += (dz / d) * W_SEEK * BASE_SPEED * 0.7
          } else {
            // wander: meander around current heading
            const base = Math.atan2(vz, vx)
            const wa = base + (rng() - 0.5) * 1.4
            ax += Math.cos(wa) * W_WANDER * BASE_SPEED
            az += Math.sin(wa) * W_WANDER * BASE_SPEED
            // scouts that drift too far get pulled gently back toward home
            const hx = colony.x - px
            const hz = colony.z - pz
            if (hx * hx + hz * hz > 190 * 190) {
              const hd = Math.hypot(hx, hz) || 1
              ax += (hx / hd) * BASE_SPEED * 0.6
              az += (hz / hd) * BASE_SPEED * 0.6
            }
          }
        }
        // lay a home trail outbound so we (and nestmates) can navigate back
        pher.deposit(cid, TO_HOME, px, pz, 2.5 * dt)
      }
    }

    // --- shoreline avoidance: water is an obstacle, not just blue terrain ---
    const speedForLook = Math.hypot(vx, vz)
    const hx = speedForLook > 0.01 ? vx / speedForLook : Math.cos(rng() * Math.PI * 2)
    const hz = speedForLook > 0.01 ? vz / speedForLook : Math.sin(rng() * Math.PI * 2)
    if (groundY(px + hx * WATER_LOOKAHEAD, pz + hz * WATER_LOOKAHEAD) < DRY_LEVEL) {
      let bestX = hx
      let bestZ = hz
      let bestH = -Infinity
      const offset = rng() * Math.PI * 2
      for (let s = 0; s < DRY_DIRS; s++) {
        const a = offset + (s / DRY_DIRS) * Math.PI * 2
        const sx = Math.cos(a)
        const sz = Math.sin(a)
        const h = groundY(px + sx * WATER_LOOKAHEAD, pz + sz * WATER_LOOKAHEAD)
        if (h > bestH) {
          bestH = h
          bestX = sx
          bestZ = sz
        }
      }
      ax += bestX * BASE_SPEED * 3.1
      az += bestZ * BASE_SPEED * 3.1
    }

    // --- territory: repelled from rival nests; raise their threat ---
    for (let c = 0; c < colonies.length; c++) {
      if (c === cid) continue
      const oc = colonies[c]
      const dx = px - oc.x
      const dz = pz - oc.z
      const d2 = dx * dx + dz * dz
      if (d2 < TERRITORY_SQ && d2 > 0.01) {
        const d = Math.sqrt(d2)
        const push = (TERRITORY - d) / TERRITORY
        ax += (dx / d) * push * BASE_SPEED * 1.2
        az += (dz / d) * push * BASE_SPEED * 1.2
        oc.threat = Math.min(1, oc.threat + dt * 0.4 * push)
      }
    }

    // soft bounds
    if (px > BOUNDS) ax -= (px - BOUNDS) * 1.5
    else if (px < -BOUNDS) ax -= (px + BOUNDS) * 1.5
    if (pz > BOUNDS) az -= (pz - BOUNDS) * 1.5
    else if (pz < -BOUNDS) az -= (pz + BOUNDS) * 1.5

    // clamp steering force
    const af = Math.hypot(ax, az)
    if (af > MAX_FORCE) {
      const s = MAX_FORCE / af
      ax *= s
      az *= s
    }

    // integrate velocity
    V[i3] += ax * dt
    V[i3 + 2] += az * dt

    // clamp to caste max speed
    const maxSpeed = BASE_SPEED * TASK_SPEED[task]
    const speed = Math.hypot(V[i3], V[i3 + 2])
    if (speed > maxSpeed) {
      const s = maxSpeed / speed
      V[i3] *= s
      V[i3 + 2] *= s
    }

    // integrate position; store the terrain contact point. Renderers add model
    // foot clearance from their own bounds so ants do not float above hills.
    let nx = px + V[i3] * dt
    let nz = pz + V[i3 + 2] * dt
    if (!isDryLand(nx, nz, 0.42)) {
      let found = false
      let bestX = px
      let bestZ = pz
      let bestH = -Infinity
      for (let ring = 1; ring <= 3 && !found; ring++) {
        const radius = ring * 4
        const offset = Math.atan2(-V[i3 + 2], -V[i3])
        for (let s = 0; s < DRY_DIRS; s++) {
          const a = offset + (s / DRY_DIRS) * Math.PI * 2
          const sx = px + Math.cos(a) * radius
          const sz = pz + Math.sin(a) * radius
          const h = groundY(sx, sz)
          if (h > bestH) {
            bestH = h
            bestX = sx
            bestZ = sz
          }
          if (h > DRY_LEVEL) {
            bestX = sx
            bestZ = sz
            found = true
            break
          }
        }
      }
      nx = bestX
      nz = bestZ
      V[i3] *= -0.18
      V[i3 + 2] *= -0.18
    }
    P[i3] = nx
    P[i3 + 2] = nz
    P[i3 + 1] = groundY(nx, nz)
  }
}
