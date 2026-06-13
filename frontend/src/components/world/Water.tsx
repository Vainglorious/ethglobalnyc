/**
 * Water — a large reflective plane at WATER_LEVEL. MeshReflectorMaterial gives
 * real planar reflections of the sky/terrain so low basins read as lakes/sea.
 * A faint vertical bob animates the surface without touching geometry.
 */

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { MeshReflectorMaterial } from '@react-three/drei'
import { Mesh } from 'three'
import { WATER_LEVEL } from '../../utils/noise'

export default function Water() {
  const ref = useRef<Mesh>(null)

  useFrame((state) => {
    if (ref.current) {
      ref.current.position.y = WATER_LEVEL + Math.sin(state.clock.elapsedTime * 0.6) * 0.12
    }
  })

  return (
    <mesh ref={ref} rotation={[-Math.PI / 2, 0, 0]} position={[0, WATER_LEVEL, 0]} receiveShadow>
      <planeGeometry args={[2400, 2400]} />
      <MeshReflectorMaterial
        resolution={512}
        mirror={0.18}
        mixBlur={3.2}
        mixStrength={1.35}
        blur={[520, 180]}
        minDepthThreshold={0.3}
        maxDepthThreshold={1.8}
        depthScale={0.85}
        color="#5d9cb8"
        metalness={0.02}
        roughness={0.34}
      />
    </mesh>
  )
}
