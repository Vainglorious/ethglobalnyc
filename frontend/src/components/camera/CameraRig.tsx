/**
 * CameraRig — the explore ↔ strategic camera state machine.
 *
 *   strategic : OrbitControls (mounted only in this state)
 *   explore   : PointerLockControls + WASD walk (mounted only in this state)
 *   transition: NEITHER controller; camera position + lookAt are damped toward
 *               the destination preset, then endTransition() flips the state.
 *
 * This guarantees only one controller is ever active and that every mode change
 * is a smooth lerp, never a hard cut (per the plan).
 */

import { useEffect, useMemo, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { OrbitControls, PointerLockControls } from '@react-three/drei'
import { Vector3 } from 'three'
import { damp3 } from 'maath/easing'
import { useWorldStore, type CameraTarget } from '../../store/worldStore'
import { groundY } from '../../utils/noise'
import { sim } from '../../store/simStore'

const EYE_HEIGHT = 6.2
const WALK_SPEED = 19
const SPRINT = 1.75

const PRESETS: Record<CameraTarget, { pos: Vector3; target: Vector3 }> = {
  strategic: { pos: new Vector3(88, 58, 112), target: new Vector3(0, 9, 0) },
  explore: { pos: new Vector3(0, 14, 32), target: new Vector3(0, 8, -24) },
}

export default function CameraRig() {
  const cameraMode = useWorldStore((s) => s.cameraMode)
  const targetMode = useWorldStore((s) => s.targetMode)
  const { camera, gl } = useThree()
  const orbitRef = useRef<any>(null)

  // live keyboard state (no React re-render)
  const keys = useRef<Record<string, boolean>>({})
  const lookTarget = useMemo(() => new Vector3(0, 8, 0), [])
  const colonyTarget = useMemo(() => new Vector3(0, 8, 0), [])
  const forward = useMemo(() => new Vector3(), [])
  const right = useMemo(() => new Vector3(), [])

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      keys.current[e.code] = true
    }
    const up = (e: KeyboardEvent) => {
      keys.current[e.code] = false
    }
    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
    }
  }, [])

  // Prime the lookTarget when a transition begins so damping reads smoothly.
  useEffect(() => {
    if (cameraMode === 'transition') {
      lookTarget.copy(PRESETS[targetMode].target)
    }
  }, [cameraMode, targetMode, lookTarget])

  useFrame((state, dt) => {
    if (sim.colonies.length > 0) {
      let x = 0
      let z = 0
      for (const colony of sim.colonies) {
        x += colony.x
        z += colony.z
      }
      x /= sim.colonies.length
      z /= sim.colonies.length
      colonyTarget.set(x, groundY(x, z) + 10, z)
    }

    if (cameraMode === 'strategic' && orbitRef.current) {
      orbitRef.current.target.lerp(colonyTarget, 1 - Math.exp(-dt * 2.6))
      orbitRef.current.update()
    }

    if (cameraMode === 'transition') {
      const dest = PRESETS[targetMode]
      const target = targetMode === 'strategic' ? colonyTarget : dest.target
      damp3(camera.position, dest.pos, 0.28, dt)
      damp3(lookTarget, target, 0.22, dt)
      camera.lookAt(lookTarget)
      if (camera.position.distanceToSquared(dest.pos) < 2.4) {
        camera.position.copy(dest.pos)
        useWorldStore.getState().endTransition()
      }
      return
    }

    if (cameraMode === 'explore') {
      // WASD walk along the ground plane using current facing
      camera.getWorldDirection(forward)
      forward.y = 0
      forward.normalize()
      right.crossVectors(forward, camera.up).normalize()

      const k = keys.current
      let mx = 0
      let mz = 0
      if (k['KeyW'] || k['ArrowUp']) mz += 1
      if (k['KeyS'] || k['ArrowDown']) mz -= 1
      if (k['KeyD'] || k['ArrowRight']) mx += 1
      if (k['KeyA'] || k['ArrowLeft']) mx -= 1
      if (mx !== 0 || mz !== 0) {
        const sp = WALK_SPEED * (k['ShiftLeft'] ? SPRINT : 1) * dt
        const len = Math.hypot(mx, mz)
        camera.position.addScaledVector(forward, (mz / len) * sp)
        camera.position.addScaledVector(right, (mx / len) * sp)
      }
      // Glue eye height to the smooth terrain surface. Keep this comfortably
      // above ants/rocks so first-person screenshots do not start inside props.
      const desiredY = groundY(camera.position.x, camera.position.z) + EYE_HEIGHT
      camera.position.y += (desiredY - camera.position.y) * (1 - Math.exp(-dt * 7))
      const breathing = Math.sin(state.clock.elapsedTime * 1.15) * 0.045
      camera.position.y += breathing
    }
  })

  return (
    <>
      {cameraMode === 'strategic' && (
        <OrbitControls
          ref={orbitRef}
          makeDefault
          enablePan
          minPolarAngle={Math.PI * 0.16}
          maxPolarAngle={Math.PI * 0.46}
          minDistance={34}
          maxDistance={245}
          enableDamping
          dampingFactor={0.055}
          rotateSpeed={0.36}
          zoomSpeed={0.62}
          panSpeed={0.42}
        />
      )}
      {cameraMode === 'explore' && <PointerLockControls makeDefault domElement={gl.domElement} />}
    </>
  )
}
