# Frontend — "COLONY: Living Intelligence" 3D Viz (2026-06-13)

*The interactive 3D visualization that makes the colony loop legible. Engineering record
(path `frontend/`).*

## One line
An interactive **3D (React + Three.js / R3F)** visualization of the ant-colony forecasting swarm:
ants foraging on procedural terrain, debate pulses flying between agents, USDC stake flows arcing
to nests — fed either by a local procedural simulation or by **replaying the Python harness's
JSONL event stream.** This is the "make the loop legible" half of the thesis.

## Tech stack
TypeScript (strict) · React 18.3 · three r0.169 (WebGL2) + @react-three/fiber 8 + drei 9 ·
postprocessing (Bloom + Vignette) · **zustand** (two stores; SoA typed arrays for agents) ·
Vite 5 (dev :5173) · Playwright (headless screenshots). No `.env` — **all config is baked into
source constants.**

## Architecture (the load-bearing idea)
**The hot path is fully decoupled from React.** `Engine.tsx` runs ONE `useFrame` (priority, so it
runs first) that each frame: `stepSimulation(dt)` (hash rebuild → pheromone → domain → boids) →
active sim-source update (LocalSim or JsonlReplay) → comm/flow buffer aging → **throttled UI
snapshots (~2 Hz fps, ~8 Hz ant/colony)**. It never touches React state in the hot path — it
writes **typed arrays**; renderers read them the same frame. That's what holds 60 fps at
500–2048 agents.

- **world/** — all `InstancedMesh` (one draw call each): `AntSwarm` (verified ants gold-tinted),
  `Colony` (nests), `Terrain` (CPU-displaced, biome-colored), `Water`, `Vegetation`, `Atmosphere`,
  `Resources`, `CommLinks` (debate pulses), `StakeFlows` (Bezier stake particles, color by side,
  winners accelerate in / losers fade), `PheromoneTrails`.
- **systems/** — pure logic: `simulation`, `domain` (foraging/brood/caste meaning layer), `boids`,
  `pheromone` (dual-channel stigmergy), `spatialHash` (O(neighbors) lookup), `commBuffer`/
  `flowBuffer` (zero-alloc ring buffers), `raycast` (ant picking).
- **data/** — `schema.ts` (TS mirror of the Python harness models), `adapter.ts`
  (`createWorldSink` routes events → buffers/store), `jsonlReplay.ts` (fetches `/data/demo.jsonl`,
  ~12 ev/s, loops), `localSim.ts` (always-on synthetic generator), `wsClient.ts` (**STUB** — live
  WebSocket feed not wired yet).
- **store/** — `simStore` (non-React SoA, `MAX_AGENTS=2048`), `worldStore` (UI zustand: selection,
  camera mode, snapshots, data source).
- **camera/** — dual-camera state machine: explore (PointerLock + WASD, glued to terrain) ↔
  strategic (Orbit), ~2 s lerp, `V` toggles.

## Demo data format (`public/data/demo.jsonl`)
Newline-delimited JSON, each line a `ColonyEvent`. Observed `event_type`s: `round_summary`,
`agent_record`, `debate_claim`, `forecast`. **This JSONL is the contract between colony (producer)
and frontend (consumer)** — `schema.ts` and the colony's `write_jsonl` / `events.compact.jsonl`
must stay in sync.

## WebGPU prototype (`frontend/webgpu-proto/`)
A self-contained vertical slice proving a WebGPU path (TSL sky/terrain/water, 400 instanced ants)
under `WebGPURenderer`. Key gotcha solved: dual-three-instance issue (uses the `three/webgpu`
build). **Proof of concept, not integrated** — the path to GPU scaling if WebGL can't keep up.

## State of completeness
**Working:** boids + pheromone + domain sim, spatial-hash picking, JSONL replay + local synthesis,
dual camera, selection cards + tooltips, full render (terrain/water/veg/colonies/agents/FX), live
comm pulses + stake flows + pheromone trails, population slider (1–2048), data-source toggle, FPS.
**Stubbed / TODO:** `wsClient.ts` live feed (not wired), WebGPU (prototype only), no
persistence/multiplayer, **no agent death/culling in the frontend sim yet**, silent fallback if
replay JSONL fails, mobile likely unsupported.

## Design notes to remember
- Engine's `useFrame` **must run first**; renderers read frozen buffers the same frame — order is
  load-bearing.
- Keep React out of the hot path — typed arrays + throttled snapshots is what holds 60 fps.
- One `InstancedMesh` per object type = one draw call; geometry pre-merged.
- `terrainHeight()` is the single source of truth shared by CPU logic and terrain geometry — never
  fork it.
- **The JSONL schema is the seam with the colony harness — treat it as a contract.**

## Next moves
1. Wire `wsClient.ts` to a real harness WebSocket for a **live** (not replay) feed.
2. Surface agent death / reproduction visually once the harness emits settlement + lineage events.
3. Add the **survival/lineage charts** the plan calls the demo's strongest moment (verified vs
   anonymous bankroll over generations).
4. Keep `schema.ts` aligned with `events.compact.jsonl` as the colony evolves.
