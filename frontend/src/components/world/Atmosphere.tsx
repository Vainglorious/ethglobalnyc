/**
 * Atmosphere — soft natural daylight: warm sun, strong sky fill, and a little
 * drifting dust. The goal is readable terrain with no crushed-black forests.
 */

import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { AdditiveBlending, BufferAttribute, BufferGeometry, DirectionalLight, Points } from 'three'
import { VOXEL_HALF } from '../../utils/noise'
import { PALETTE } from '../../utils/palette'
import { mulberry32 } from '../../utils/math'

const DUST_COUNT = 520

export default function Atmosphere() {
  const dustRef = useRef<Points>(null)
  const sunRef = useRef<DirectionalLight>(null)

  const dustGeo = useMemo(() => {
    const rand = mulberry32(98765)
    const arr = new Float32Array(DUST_COUNT * 3)
    for (let i = 0; i < DUST_COUNT; i++) {
      const r = Math.sqrt(rand()) * VOXEL_HALF * 1.45
      const a = rand() * Math.PI * 2
      arr[i * 3] = Math.cos(a) * r
      arr[i * 3 + 1] = 4 + Math.pow(rand(), 1.7) * 62
      arr[i * 3 + 2] = Math.sin(a) * r
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(arr, 3))
    return g
  }, [])

  useFrame((state) => {
    if (dustRef.current) {
      const t = state.clock.elapsedTime
      dustRef.current.rotation.y = t * 0.006
      dustRef.current.position.y = Math.sin(t * 0.18) * 1.1
    }
  })

  return (
    <>
      <hemisphereLight args={['#d7e9f1', '#9a8665', 0.92]} />
      <ambientLight intensity={0.34} />
      <directionalLight
        ref={sunRef}
        position={[86, 72, 48]}
        intensity={2.35}
        color={PALETTE.sun}
        castShadow
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={20}
        shadow-camera-far={520}
        shadow-camera-left={-220}
        shadow-camera-right={220}
        shadow-camera-top={220}
        shadow-camera-bottom={-220}
        shadow-bias={-0.00025}
      />

      <points ref={dustRef} geometry={dustGeo}>
        <pointsMaterial
          size={0.42}
          color="#ffe7bd"
          transparent
          opacity={0.11}
          sizeAttenuation
          depthWrite={false}
          blending={AdditiveBlending}
        />
      </points>
    </>
  )
}
