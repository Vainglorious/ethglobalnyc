/**
 * worldStore — UI-facing state ONLY (selection, camera mode, throttled stats).
 * Never holds per-frame agent data. Updates here trigger React re-renders, so
 * the sim loop writes to it sparingly (selection changes, ~4Hz stat snapshots).
 */

import { create } from 'zustand'

export type CameraMode = 'explore' | 'transition' | 'strategic'
/** A camera transition destination — never 'transition' itself. */
export type CameraTarget = Exclude<CameraMode, 'transition'>


/** Throttled snapshot of an inspected ant (copied out of typed arrays). */
export interface AntSnapshot {
  index: number
  agentId: string
  name: string
  role: number
  state: number
  verified: boolean
  bankroll: number
  accuracy: number
  homeProbability: number
  side: number
  stake: number
  genomeHash: string
  walletAddress: string
  generation: number
}

export interface ColonySnapshot {
  index: number
  population: number
  bankroll: number
  accuracy: number
  growthRate: number
  verifiedRatio: number
  health: number
}

interface WorldState {
  cameraMode: CameraMode
  /** target mode used during a transition (never 'transition'). */
  targetMode: CameraTarget

  selectedAnt: number | null
  selectedColony: number | null
  hoveredResource: number | null

  antSnapshot: AntSnapshot | null
  colonySnapshot: ColonySnapshot | null

  agentCount: number
  dataSource: 'local' | 'replay'
  replayActive: boolean
  fps: number

  // actions
  setCameraMode: (m: CameraTarget) => void
  beginTransition: (to: CameraTarget) => void
  endTransition: () => void
  toggleCamera: () => void

  selectAnt: (i: number | null) => void
  selectColony: (i: number | null) => void
  setHoveredResource: (i: number | null) => void

  setAntSnapshot: (s: AntSnapshot | null) => void
  setColonySnapshot: (s: ColonySnapshot | null) => void

  setAgentCount: (n: number) => void
  setDataSource: (d: 'local' | 'replay') => void
  setReplayActive: (b: boolean) => void
  setFps: (n: number) => void
}

export const useWorldStore = create<WorldState>((set, get) => ({
  cameraMode: 'strategic',
  targetMode: 'strategic',

  selectedAnt: null,
  selectedColony: null,
  hoveredResource: null,

  antSnapshot: null,
  colonySnapshot: null,

  agentCount: 500,
  dataSource: 'local',
  replayActive: false,
  fps: 0,

  setCameraMode: (m) => set({ cameraMode: m, targetMode: m }),
  beginTransition: (to) => set({ cameraMode: 'transition', targetMode: to }),
  endTransition: () => set((s) => ({ cameraMode: s.targetMode })),
  toggleCamera: () => {
    const { cameraMode } = get()
    if (cameraMode === 'transition') return
    const to: CameraTarget = cameraMode === 'explore' ? 'strategic' : 'explore'
    set({ cameraMode: 'transition', targetMode: to })
  },

  selectAnt: (i) => set({ selectedAnt: i, selectedColony: null }),
  selectColony: (i) => set({ selectedColony: i, selectedAnt: null, antSnapshot: null }),
  setHoveredResource: (i) => set({ hoveredResource: i }),

  setAntSnapshot: (s) => set({ antSnapshot: s }),
  setColonySnapshot: (s) => set({ colonySnapshot: s }),

  setAgentCount: (n) => set({ agentCount: n }),
  setDataSource: (d) => set({ dataSource: d }),
  setReplayActive: (b) => set({ replayActive: b }),
  setFps: (n) => set({ fps: n }),
}))
