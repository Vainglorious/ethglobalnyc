/**
 * Experience — the Canvas + scene graph root. <Engine> is FIRST so its frame
 * callback advances the sim before any renderer reads the buffers. Sunny blue
 * sky, hard shadows, gentle bloom only on the bright emissives (core/crystals).
 */

import { Canvas } from '@react-three/fiber'
import { Sky, AdaptiveDpr, AdaptiveEvents } from '@react-three/drei'
import { EffectComposer, Bloom, Vignette } from '@react-three/postprocessing'
import { Perf } from 'r3f-perf'
import { FogExp2, Color, ACESFilmicToneMapping, SRGBColorSpace } from 'three'

import Engine from './Engine'
import Atmosphere from './world/Atmosphere'
import Terrain from './world/Terrain'
import Water from './world/Water'
import Vegetation from './world/Vegetation'
import PheromoneTrails from './world/PheromoneTrails'
import Colony from './world/Colony'
import AntSwarm from './world/AntSwarm'
import Resources from './world/Resources'
import CommLinks from './world/CommLinks'
import StakeFlows from './world/StakeFlows'
import CameraRig from './camera/CameraRig'
import AntCard from './ui/AntCard'
import ColonyCard from './ui/ColonyCard'
import ResourceTooltip from './ui/ResourceTooltip'
import { PALETTE } from '../utils/palette'

export default function Experience() {
  return (
    <Canvas
      shadows="soft"
      dpr={[1, 2]}
      gl={{
        antialias: true,
        powerPreference: 'high-performance',
        toneMapping: ACESFilmicToneMapping,
        outputColorSpace: SRGBColorSpace,
      }}
      camera={{ position: [88, 58, 112], fov: 48, near: 0.1, far: 3000 }}
      onCreated={({ scene }) => {
        scene.background = new Color(PALETTE.sky)
        scene.fog = new FogExp2(PALETTE.horizon, 0.00105)
      }}
    >
      {/* sim driver — must be first */}
      <Engine />

      <Sky
        sunPosition={[80, 54, 42]}
        turbidity={6.6}
        rayleigh={2.4}
        mieCoefficient={0.006}
        mieDirectionalG={0.82}
      />

      <Atmosphere />
      <Terrain />
      <Water />
      <Vegetation />
      <PheromoneTrails />
      <Colony />
      <AntSwarm />
      <Resources />
      <CommLinks />
      <StakeFlows />

      {/* spatial UI (in-scene) */}
      <AntCard />
      <ColonyCard />
      <ResourceTooltip />

      <CameraRig />

      <EffectComposer enableNormalPass={false}>
        <Bloom mipmapBlur intensity={0.12} luminanceThreshold={1.08} luminanceSmoothing={0.24} />
        <Vignette eskil={false} offset={0.48} darkness={0.1} />
      </EffectComposer>

      <AdaptiveDpr />
      <AdaptiveEvents />
      {import.meta.env.DEV && <Perf position="top-left" minimal />}
    </Canvas>
  )
}
