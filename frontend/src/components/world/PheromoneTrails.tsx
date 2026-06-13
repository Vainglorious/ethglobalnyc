/**
 * PheromoneTrails — visualizes the ant trail system as worn earth paths, not a
 * debug heatmap. The simulation still uses the pheromone grid; this renderer
 * samples colony/resource relationships and draws subtle ground-hugging paths
 * where real ants would visibly wear routes into the terrain.
 */

import { useMemo } from 'react'
import { CatmullRomCurve3, Color, TubeGeometry, Vector3 } from 'three'
import { sim } from '../../store/simStore'
import { groundY, isDryLand } from '../../utils/noise'
import { COLONY_COLORS } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'

const MAX_ROUTES_PER_COLONY = 4
const POINTS_PER_ROUTE = 18
const _soil = new Color('#6b5137')

function dryRoutePoint(x: number, z: number, nx: number, nz: number): [number, number] {
  if (isDryLand(x, z, 0.45)) return [x, z]
  for (let r = 4; r <= 42; r += 4) {
    const ax = x + nx * r
    const az = z + nz * r
    if (isDryLand(ax, az, 0.45)) return [ax, az]
    const bx = x - nx * r
    const bz = z - nz * r
    if (isDryLand(bx, bz, 0.45)) return [bx, bz]
  }
  return [x, z]
}

function makeRoute(colonyIndex: number, tx: number, tz: number) {
  const c = sim.colonies[colonyIndex]
  const pts: Vector3[] = []
  const dx = tx - c.x
  const dz = tz - c.z
  const len = Math.max(1, Math.hypot(dx, dz))
  const nx = -dz / len
  const nz = dx / len
  const bend = Math.sin((colonyIndex + 1) * 1.37 + tx * 0.03 + tz * 0.02) * 10

  for (let i = 0; i < POINTS_PER_ROUTE; i++) {
    const t = i / (POINTS_PER_ROUTE - 1)
    const ease = t * t * (3 - 2 * t)
    const wobble = Math.sin(t * Math.PI) * bend + Math.sin(t * Math.PI * 3 + colonyIndex) * 2.4
    let x = c.x + dx * ease + nx * wobble
    let z = c.z + dz * ease + nz * wobble
    ;[x, z] = dryRoutePoint(x, z, nx, nz)
    pts.push(new Vector3(x, groundY(x, z) + 0.08, z))
  }

  return new CatmullRomCurve3(pts, false, 'centripetal')
}

function routeKeys() {
  return sim.colonies.flatMap((c, colonyIndex) =>
    sim.resources
      .map((r, resourceIndex) => ({
        colonyIndex,
        resourceIndex,
        x: r.x,
        z: r.z,
        score: Math.hypot(r.x - c.x, r.z - c.z) - r.energy * 80,
      }))
      .sort((a, b) => a.score - b.score)
      .slice(0, MAX_ROUTES_PER_COLONY),
  )
}

function TrailRoute({ colonyIndex, x, z }: { colonyIndex: number; x: number; z: number }) {
  const geometry = useMemo(() => new TubeGeometry(makeRoute(colonyIndex, x, z), 48, 0.55, 7, false), [colonyIndex, x, z])
  const accent = COLONY_COLORS[colonyIndex % COLONY_COLORS.length]

  return (
    <group>
      <mesh geometry={geometry} receiveShadow>
        <meshStandardMaterial color={_soil} roughness={1} metalness={0} transparent opacity={0.52} />
      </mesh>
      <mesh geometry={geometry} position={[0, 0.035, 0]}>
        <meshBasicMaterial color={accent} transparent opacity={0.09} depthWrite={false} toneMapped />
      </mesh>
    </group>
  )
}

export default function PheromoneTrails() {
  const agentCount = useWorldStore((s) => s.agentCount)
  const routes = useMemo(routeKeys, [agentCount])

  return (
    <group>
      {routes.map((r) => (
        <TrailRoute
          key={`${r.colonyIndex}:${r.resourceIndex}`}
          colonyIndex={r.colonyIndex}
          x={r.x}
          z={r.z}
        />
      ))}
    </group>
  )
}
