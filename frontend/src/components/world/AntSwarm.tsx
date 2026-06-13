/**
 * AntSwarm — real ant GLB rendered through synchronized instanced meshes.
 *
 * The source model is small enough for thousands of instances, but we still keep
 * the existing zero-React hot path: transforms and colors are written directly
 * from simStore typed arrays inside one useFrame.
 */

import { useLayoutEffect, useMemo, useRef } from 'react'
import { useFrame, useLoader } from '@react-three/fiber'
import {
  Box3,
  BufferGeometry,
  Color,
  DynamicDrawUsage,
  Euler,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshStandardMaterial,
  Quaternion,
  Vector3,
} from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { sim, MAX_AGENTS } from '../../store/simStore'
import { AntTask } from '../../data/schema'
import { COLONY_COLORS, VERIFIED_COLOR } from '../../utils/palette'
import { useWorldStore } from '../../store/worldStore'
import { groundY } from '../../utils/noise'

const _m = new Matrix4()
const _q = new Quaternion()
const _e = new Euler()
const _p = new Vector3()
const _s = new Vector3()
const _c = new Color()
const SELECT = new Color('#fff7df')
const BODY = new Color('#1c130d')
const AMBER = new Color('#805028')
const GOLD = new Color('#d9aa45')
const SOLDIER = new Color('#6f261d')
const FOOD_GLOW = new Color('#d7c27a')

const MODEL_URL = '/models/ant.glb'
const MODEL_MIN_Y = -0.9493200182914734
const BASE_SCALE = 0.42
const QUEEN_SCALE = 1.55
const SELECT_SCALE = 1.18
const FOOT_CLEARANCE = 0.035
const SLOPE_SAMPLE_FORWARD = 1.6
const SLOPE_SAMPLE_SIDE = 1.15

interface AntPart {
  geometry: BufferGeometry
  material: MeshStandardMaterial
}

function materialFrom(source: Mesh): MeshStandardMaterial {
  const mat = Array.isArray(source.material) ? source.material[0] : source.material
  const next =
    mat instanceof MeshStandardMaterial
      ? mat.clone()
      : new MeshStandardMaterial({ color: BODY, roughness: 0.7, metalness: 0 })
  next.roughness = 0.68
  next.metalness = 0.03
  next.vertexColors = true
  next.toneMapped = true
  return next
}

function extractAntParts(scene: Group): AntPart[] {
  const parts: AntPart[] = []
  scene.updateMatrixWorld(true)
  const box = new Box3().setFromObject(scene)
  const center = new Vector3()
  box.getCenter(center)

  scene.traverse((obj) => {
    const mesh = obj as Mesh
    if (!mesh.isMesh) return
    const geometry = mesh.geometry.clone()
    geometry.applyMatrix4(mesh.matrixWorld)
    geometry.translate(-center.x, 0, -center.z)
    geometry.computeVertexNormals()
    parts.push({ geometry, material: materialFrom(mesh) })
  })
  return parts
}

function disposeParts(parts: AntPart[]) {
  for (const part of parts) {
    part.geometry.dispose()
    part.material.dispose()
  }
}

function useAntParts() {
  const gltf = useLoader(GLTFLoader, MODEL_URL)
  return useMemo(() => extractAntParts(gltf.scene), [gltf])
}

function AntPartMesh({ part, index }: { part: AntPart; index: number }) {
  const ref = useRef<InstancedMesh>(null)
  const agentCount = useWorldStore((s) => s.agentCount)

  useLayoutEffect(() => {
    const mesh = ref.current
    if (!mesh) return
    mesh.instanceMatrix.setUsage(DynamicDrawUsage)
    mesh.raycast = () => null
  }, [])

  useFrame((state) => {
    const mesh = ref.current
    if (!mesh) return

    const t = state.clock.elapsedTime
    const count = sim.count
    const selected = useWorldStore.getState().selectedAnt
    const camX = state.camera.position.x
    const camZ = state.camera.position.z
    const P = sim.positions
    const V = sim.velocities

    for (let i = 0; i < count; i++) {
      const i3 = i * 3
      const px = P[i3]
      const py = P[i3 + 1]
      const pz = P[i3 + 2]
      const dx = px - camX
      const dz = pz - camZ
      const far = dx * dx + dz * dz > 170 * 170

      const speed = Math.hypot(V[i3], V[i3 + 2])
      const yaw = speed > 0.02 ? Math.atan2(V[i3], V[i3 + 2]) : sim.phase[i]
      const gait = far ? 0 : Math.sin(t * 12 + sim.phase[i])
      const bob = far ? 0 : Math.max(0, gait) * 0.045 * Math.min(speed / 5, 1)
      let pitch = far ? 0 : Math.min(speed * 0.012, 0.18)
      let roll = far ? 0 : gait * 0.055 * Math.min(speed / 5, 1)
      if (!far) {
        const fx = Math.sin(yaw)
        const fz = Math.cos(yaw)
        const rx = Math.cos(yaw)
        const rz = -Math.sin(yaw)
        const front = groundY(px + fx * SLOPE_SAMPLE_FORWARD, pz + fz * SLOPE_SAMPLE_FORWARD)
        const back = groundY(px - fx * SLOPE_SAMPLE_FORWARD, pz - fz * SLOPE_SAMPLE_FORWARD)
        const right = groundY(px + rx * SLOPE_SAMPLE_SIDE, pz + rz * SLOPE_SAMPLE_SIDE)
        const left = groundY(px - rx * SLOPE_SAMPLE_SIDE, pz - rz * SLOPE_SAMPLE_SIDE)
        pitch += Math.atan2(front - back, SLOPE_SAMPLE_FORWARD * 2)
        roll += Math.atan2(left - right, SLOPE_SAMPLE_SIDE * 2)
      }
      _e.set(pitch, yaw, roll)
      _q.setFromEuler(_e)

      const task = sim.tasks[i] as AntTask
      const isQueen = task === AntTask.Queen
      const sel = i === selected
      const scale = BASE_SCALE * (isQueen ? QUEEN_SCALE : 1) * (sel ? SELECT_SCALE : 1)
      const footLift = -MODEL_MIN_Y * scale + FOOT_CLEARANCE
      _p.set(px, py + footLift + bob, pz)
      _s.set(scale, scale, scale)
      _m.compose(_p, _q, _s)
      mesh.setMatrixAt(i, _m)

      _c.copy(BODY).lerp(AMBER, 0.24)
      _c.lerp(COLONY_COLORS[sim.colonyId[i] % COLONY_COLORS.length], 0.14)
      if (isQueen) _c.lerp(GOLD, 0.38)
      else if (task === AntTask.Soldier) _c.lerp(SOLDIER, 0.34)
      if (sim.carrying[i]) _c.lerp(FOOD_GLOW, 0.32)
      if (sim.verified[i]) _c.lerp(VERIFIED_COLOR, 0.14)
      const hl = sim.highlight[i]
      if (hl > 0) _c.lerp(SELECT, hl * 0.55)
      if (sel) _c.copy(SELECT)
      if (index === 1) _c.lerp(SELECT, 0.08)
      mesh.setColorAt(i, _c)
    }

    mesh.count = count
    mesh.instanceMatrix.needsUpdate = true
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh
      ref={ref}
      args={[part.geometry, part.material, MAX_AGENTS]}
      frustumCulled={false}
      castShadow
      key={`${agentCount}-${index}`}
    />
  )
}

export default function AntSwarm() {
  const parts = useAntParts()

  useLayoutEffect(() => () => disposeParts(parts), [parts])

  return (
    <>
      {parts.map((part, index) => (
        <AntPartMesh key={index} part={part} index={index} />
      ))}
    </>
  )
}
