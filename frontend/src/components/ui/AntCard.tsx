/**
 * AntCard — floating spatial panel for the selected ant. Lives inside the
 * Canvas; a group follows the ant's live position each frame and a drei <Html>
 * anchors the glass card beside it. Content comes from the throttled
 * antSnapshot in worldStore (never read per-frame in React).
 *
 * Only ONE AntCard exists (the selected ant) per the one-panel-per-type rule.
 */

import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { Html } from '@react-three/drei'
import { Group } from 'three'
import { useWorldStore } from '../../store/worldStore'
import { sim } from '../../store/simStore'
import { Role, AntState } from '../../data/schema'
import { ROLE_LABELS, ROLE_HEX, STATE_LABELS } from '../../utils/palette'

export default function AntCard() {
  const selected = useWorldStore((s) => s.selectedAnt)
  const snap = useWorldStore((s) => s.antSnapshot)
  const group = useRef<Group>(null)

  useFrame(() => {
    if (selected === null || !group.current) return
    const i3 = selected * 3
    group.current.position.set(sim.positions[i3], sim.positions[i3 + 1] + 2, sim.positions[i3 + 2])
  })

  if (selected === null || !snap || snap.index !== selected) return null

  const role = snap.role as Role
  const state = snap.state as AntState
  const sideLabel = snap.side > 0 ? 'HOME' : snap.side < 0 ? 'AWAY' : '—'

  return (
    <group ref={group}>
      <Html center distanceFactor={48} zIndexRange={[20, 0]} style={{ pointerEvents: 'none' }}>
        <div className="glass panel">
          <div className="panel-head">
            <div>
              <div className="panel-title">{snap.name}</div>
              <div className="panel-sub">{ROLE_LABELS[role]}</div>
            </div>
            {snap.verified && <span className="badge gold">Verified</span>}
          </div>

          <div className="row">
            <span className="k">
              <span className="dot" style={{ background: ROLE_HEX[role] }} />
              State
            </span>
            <span className="v">{STATE_LABELS[state]}</span>
          </div>

          <div className="row">
            <span className="k">Bankroll</span>
            <span className="v">${snap.bankroll.toFixed(1)}</span>
          </div>

          <div>
            <div className="row" style={{ marginBottom: 0 }}>
              <span className="k">Accuracy</span>
              <span className="v">{(snap.accuracy * 100).toFixed(0)}%</span>
            </div>
            <div className="bar">
              <i style={{ width: `${snap.accuracy * 100}%`, background: '#2eff7a' }} />
            </div>
          </div>

          <div>
            <div className="row" style={{ marginBottom: 0, marginTop: 8 }}>
              <span className="k">P(home)</span>
              <span className="v">
                {(snap.homeProbability * 100).toFixed(0)}% · {sideLabel}
              </span>
            </div>
            <div className="bar">
              <i style={{ width: `${snap.homeProbability * 100}%`, background: '#3abeff' }} />
            </div>
          </div>

          <div className="row" style={{ marginTop: 10 }}>
            <span className="k">Generation</span>
            <span className="v">{snap.generation}</span>
          </div>
          {snap.genomeHash && (
            <div className="row">
              <span className="k">Genome</span>
              <span className="v">{snap.genomeHash.slice(0, 10)}…</span>
            </div>
          )}
          {snap.walletAddress && (
            <div className="row">
              <span className="k">Wallet</span>
              <span className="v">
                {snap.walletAddress.slice(0, 6)}…{snap.walletAddress.slice(-4)}
              </span>
            </div>
          )}
        </div>
      </Html>
    </group>
  )
}
