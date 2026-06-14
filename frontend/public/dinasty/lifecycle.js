// Di-nasty — lifecycle controller. State machine for the demo arc:
//   0 idle → 1 kickoff → 2 scouting → 3 kg_forming → 4 recruitment →
//   5 converge → 6 ingress → 7 debate → 8 resolution → 9 egress_roam
// Frontend-paced visual timing. Owns ant activation + crystal show while the
// backend run uses the selected fixture and public scouting data.
// Resolution wires the run's forecast decisions into the Arc forecast
// contract and claims payouts for winning ants.
window.DN = window.DN || {};

console.log('[dinasty] lifecycle.js loaded · build 2026-06-14');

DN.lifecycle = (function () {
  const L = { phase: 'idle', phaseT: 0, winner: null, settleTxHash: null, runId: null, phaseHold: false };

  // duration per phase in seconds; 'idle' and 'egress_roam' are open-ended
  // Slower pacing — the previous values cut off the visible round trip
  // (ants reached the crystal but couldn't walk back before ingress
  // fired). Everything is roughly 1.5–3× longer, with the biggest bump
  // going to converge so the entire crystal → home loop completes
  // on-screen before we dive underground.
  const DURATIONS = {
    idle:        Infinity,
    kickoff:      2.5,
    scouting:    12.0,
    kg_forming:  14.0,
    recruitment:  6.0,
    converge:    18.0,   // ← big bump so ants complete the round trip
    ingress:      6.0,
    debate:      10.0,
    resolution:   3.0,
    egress_roam: Infinity
  };
  const NEXT = {
    idle:        null,         // entered only via L.start()
    kickoff:    'scouting',
    scouting:   'kg_forming',
    kg_forming: 'recruitment',
    recruitment:'converge',
    converge:   'ingress',
    ingress:    'debate',
    debate:     'resolution',
    resolution: 'egress_roam',
    egress_roam: null
  };
  const LABEL = {
    idle:        'Idle',
    kickoff:     'Kickoff',
    scouting:    'Scouting',
    kg_forming:  'Knowledge crystal forming',
    recruitment: 'Recruitment',
    converge:    'Converge on crystal',
    ingress:     'Ingress',
    debate:      'Debate',
    resolution:  'Resolution',
    egress_roam: 'Egress & roam'
  };

  // ---- helpers ----------------------------------------------------------
  function logPhase(phase) {
    if (!DN.logTerm) return;
    DN.logTerm.push('PHASE', '── ' + LABEL[phase] + ' ──');
  }

  function scoutCountPerColony() { return 6; }

  function pickScoutAnts(col, n) {
    const out = [];
    for (const a of DN.ants.list) {
      if (a.col !== col) continue;
      if (a.state !== 'idle') continue;
      if (a.hero) continue;
      out.push(a);
      if (out.length >= n) break;
    }
    return out;
  }

  function selectedMatch() {
    const el = document.getElementById('forecast-game');
    return el && el.value ? el.value : 'match:world_cup_2026:013:2026_06_13_brazil_morocco';
  }

  function selectedWinner() {
    const el = document.getElementById('forecast-winner');
    return el && el.value ? el.value : 'Brazil';
  }

  function configuredContract() {
    return (window.DN_CONFIG && window.DN_CONFIG.FORECAST && window.DN_CONFIG.FORECAST.CONTRACT) || '';
  }

  function configuredRun() {
    return (window.DN_CONFIG && window.DN_CONFIG.RUN) || {};
  }

  function configuredForecastWalletStore() {
    const forecast = (window.DN_CONFIG && window.DN_CONFIG.FORECAST) || {};
    return forecast.WALLET_STORE || forecast.wallet_store || '';
  }

  // Look up the currently selected game's cached metadata (home/away
  // team etc.) so settleForecastDemo has the right `home_team` /
  // `away_team` for the API.
  function selectedGameMeta() {
    const games = (DN.databridge && DN.databridge.forecastGames) || [];
    const key = selectedMatch();
    const found = games.find((g) => g.market_key === key);
    if (found) return found;
    return {
      market_key: key,
      match_id: key,
      market_type: 'three_way',
      home_team: 'Brazil',
      away_team: 'Morocco',
      name: 'Brazil vs Morocco'
    };
  }

  function winnerSideFor(winner, meta) {
    const norm = (v) => String(v || '').toLowerCase().trim();
    if (norm(winner) === norm(meta.home_team) || norm(winner) === 'home') return 'home';
    if (norm(winner) === norm(meta.away_team) || norm(winner) === 'away') return 'away';
    if (norm(winner) === 'draw') return 'draw';
    return 'home';
  }

  function winnerNameForSide(side, meta) {
    if (side === 'away') return meta.away_team || 'away';
    if (side === 'draw') return 'Draw';
    return meta.home_team || 'home';
  }

  function sideWithLargestStake(stakes) {
    const totals = { home: 0, draw: 0, away: 0 };
    (stakes || []).forEach((stake) => {
      if (totals[stake.outcome] == null) return;
      totals[stake.outcome] += Number(stake.amount || 0);
    });
    return Object.keys(totals).sort((a, b) => totals[b] - totals[a])[0];
  }

  function runMarketKey(meta, runId) {
    return [
      meta.market_key || selectedMatch(),
      'run',
      runId || Date.now()
    ].join(':');
  }

  function shortHash(value) {
    const text = String(value || '');
    if (text.length < 14) return text;
    return text.slice(0, 8) + '...' + text.slice(-6);
  }

  function explorerTxUrl(hash, fallbackExplorer) {
    if (!hash) return '';
    const explorer = String(fallbackExplorer || 'https://explorer.testnet.arc.network').replace(/\/$/, '');
    return explorer + '/tx/' + hash;
  }

  function receiptTransactions(step) {
    const receipt = (step && step.receipt) || {};
    const chain = receipt.chain || {};
    const explorer = chain.explorer || '';
    const out = [];
    (receipt.transactions || []).forEach((tx) => {
      if (!tx || !tx.tx_hash) return;
      out.push({
        action: tx.type || receipt.action || step.action || 'tx',
        hash: tx.tx_hash,
        explorer_url: tx.explorer_url || explorerTxUrl(tx.tx_hash, explorer),
        agent_id: receipt.agent_id || '',
        wallet: receipt.wallet || '',
        outcome: receipt.outcome || '',
        amount_usdc: receipt.amount_usdc || '',
      });
    });
    (receipt.receipts || []).forEach((tx) => {
      if (!tx || !tx.tx_hash) return;
      out.push({
        action: receipt.action || step.action || tx.transfer_id || 'fund',
        hash: tx.tx_hash,
        explorer_url: tx.explorer_url || explorerTxUrl(tx.tx_hash, explorer),
        agent_id: tx.agent_id || '',
        wallet: tx.to || '',
        outcome: '',
        amount_usdc: tx.amount_usdc || '',
      });
    });
    if (receipt.tx_hash) {
      out.push({
        action: receipt.action || step.action || 'tx',
        hash: receipt.tx_hash,
        explorer_url: receipt.explorer_url || explorerTxUrl(receipt.tx_hash, explorer),
        agent_id: receipt.agent_id || '',
        wallet: receipt.wallet || '',
        outcome: receipt.outcome || receipt.result || '',
        amount_usdc: receipt.amount_usdc || '',
      });
    }
    return out;
  }

  function firstReceiptWith(result, key) {
    const steps = (result && result.steps) || [];
    for (const step of steps) {
      const receipt = (step && step.receipt) || {};
      if (receipt[key]) return receipt;
    }
    return {};
  }

  function logForecastChainTrail(kind, result) {
    if (!DN.logTerm || !result) return;
    const contract = result.contract || '';
    const marketKey = result.market_key || '';
    const marketReceipt = firstReceiptWith(result, 'market_id');
    const marketId = marketReceipt.market_id || '';
    if (contract) DN.logTerm.push('CHAIN', kind + ' contract ' + contract);
    if (marketKey) DN.logTerm.push('CHAIN', kind + ' market_key ' + marketKey);
    if (marketId) DN.logTerm.push('CHAIN', kind + ' market_id ' + marketId);

    const steps = result.steps || [];
    let count = 0;
    steps.forEach((step) => {
      receiptTransactions(step).forEach((tx) => {
        count++;
        const who = tx.agent_id ? ' ' + tx.agent_id : '';
        const detail = [
          tx.amount_usdc ? tx.amount_usdc + ' USDC' : '',
          tx.outcome || '',
          tx.wallet ? 'wallet ' + shortHash(tx.wallet) : '',
        ].filter(Boolean).join(' · ');
        DN.logTerm.push(
          'CHAIN',
          kind + ' ' + tx.action + who +
            (detail ? ' · ' + detail : '') +
            ' · tx ' + tx.hash +
            (tx.explorer_url ? ' · ' + tx.explorer_url : '')
        );
      });
    });
    if (!count) {
      DN.logTerm.push('CHAIN', kind + ' returned no tx hashes. This usually means the API failed before signing or the response shape changed.');
    }
  }

  function startBackendRun() {
    if (L.runPromise) return L.runPromise;
    if (!DN.databridge || !DN.databridge.startScoutingRun) {
      L.runPromise = Promise.resolve(null);
      return L.runPromise;
    }
    const meta = selectedGameMeta();
    const runCfg = configuredRun();
    const matchName = meta.name || [meta.home_team, meta.away_team].filter(Boolean).join(' vs ');
    if (DN.logTerm) {
      DN.logTerm.push('SYSTEM', 'Public fixture run kicked off for ' + matchName + ' (this can take a minute).');
    }
    L.runPromise = DN.databridge.startScoutingRun({
      match: matchName,
      match_id: meta.match_id || meta.market_key,
      data_mode: 'public',
      include_deepseek_scout: true,
      agents: Math.min(Number(runCfg.agents || 200), 200),
      rooms: Math.min(Number(runCfg.rooms || 12), 50),
      seed: Number.isFinite(Number(runCfg.seed)) ? Number(runCfg.seed) : Math.floor(Math.random() * 10000),
      voice_mode: runCfg.voice_mode || 'llm',
    })
      .then((res) => {
        if (res && res.id) {
          L.runId = res.id;
          if (DN.databridge.resetCommsRun) DN.databridge.resetCommsRun(res.id);
          if (DN.commsViz && DN.commsViz.reset) DN.commsViz.reset();
          if (DN.hud && DN.hud._pollComms) DN.hud._pollComms();
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Fixture run ' + res.id + ' complete — selected-match forecast stakes ready.');
        }
        return res || null;
      })
      .catch((err) => {
        L.runError = err;
        if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Backend run failed: ' + (err && err.message || err));
        return null;
      });
    return L.runPromise;
  }

  // ---- onArrive callbacks for the scripted Bezier walks --------------
  // When a scout reaches its forest target, it walks to the crystal and
  // deposits one finding. When a converger reaches the crystal, it
  // walks home and disappears into the colony.
  function scoutArrivedAtForest(a) {
    // Don't log per-scout — when 40+ scouts arrive in the same second the
    // terminal floods. crystal.depositOne already logs the rolling total.
    const crystal = DN.crystal ? DN.crystal.position() : new THREE.Vector3(0, 0, 0);
    DN.ants.scriptWalk(
      a, a.x, a.z, crystal.x, crystal.z,
      { speed: 0.14, curl: 0.1, onArrive: scoutArrivedAtCrystal }
    );
  }
  function scoutArrivedAtCrystal(a) {
    if (DN.crystal && DN.crystal.depositOne) DN.crystal.depositOne();
    DN.ants.scriptWalk(
      a, a.x, a.z, a.col.entrance.x, a.col.entrance.z,
      { speed: 0.14, curl: 0.08, onArrive: hideAnt }
    );
  }
  function convergerArrivedAtCrystal(a) {
    a.hasShard = true;
    a._homing = true;
    // Crystal shrinks as ants pick up data — by the time the last
    // converger arrives the crystal is almost depleted.
    if (DN.crystal && DN.crystal.takeOne) DN.crystal.takeOne(0.12);
    DN.ants.scriptWalk(
      a, a.x, a.z, a.col.entrance.x, a.col.entrance.z,
      { speed: 0.12, curl: 0.06, onArrive: hideAnt }
    );
  }
  function hideAnt(a) {
    a.state = 'idle';
    a._idleWritten = false;
    a.scout = false;
    a.hasShard = false;
    a._homing = false;
  }
  // After egress, ants hop between random nearby roam points so the
  // surface looks alive while the user inspects them.
  function roamHop(a) {
    const ang = Math.random() * Math.PI * 2;
    const r = 18 + Math.random() * 18;
    const tx = a.col.entrance.x + Math.cos(ang) * r;
    const tz = a.col.entrance.z + Math.sin(ang) * r;
    DN.ants.scriptWalk(
      a, a.x, a.z, tx, tz,
      { speed: 0.08, curl: 0.16, onArrive: roamHop }
    );
  }

  // ---- phase enter hooks (visual; on-chain hooks wired in later steps) --
  const ENTER = {
    idle: () => {
      if (DN.ants && DN.ants.allIdle) DN.ants.allIdle();
      if (DN.ants && DN.ants.hideOutcomeGlow) DN.ants.hideOutcomeGlow();
      if (DN.crystal) DN.crystal.hide();
    },
    kickoff: () => {
      // ONE flyTo for the entire surface lifecycle. Subsequent phases
      // (scouting → ingress) deliberately do NOT touch the camera, so
      // every action plays out in one continuous shot — no bouncing
      // between phases, no recompute-direction-from-current-position.
      if (DN.camera && DN.camera.flyTo) {
        // 14% closer than the previous (220, 140) pass — tighter shot.
        DN.camera.flyTo(new THREE.Vector3(0, 0, 0), 190, 120, 3.0);
      }
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Match: ' + selectedMatch());
      startBackendRun();
    },
    scouting: () => {
      // Previously kicked startScoutingRun() here which streamed SSE
      // events from Railway and hammered kgview's SVG rebuild path
      // while the 3D scene was already busy with scout animations —
      // that was the source of the heavy lag. The cached KG is
      // streamed in via replayGraph during kg_forming instead.
      if (DN.logTerm) DN.logTerm.push('SCOUT', 'Scouts mining sources for findings.');
      // Wake a small scout party per colony, send each on a dedicated
      // Bezier walk to a forest target.
      let total = 0;
      (DN.colony.list || []).forEach(col => {
        const n = scoutCountPerColony();
        const arr = pickScoutAnts(col, n);
        arr.forEach((a, idx) => {
          a.scout = true;
          // Spread scouts radially around the colony, pointing into the
          // forest (outside the play area) so they're visible from the
          // overhead camera.
          const ang = (idx / Math.max(1, arr.length)) * Math.PI * 2 + Math.random() * 0.3;
          const dist = 38 + Math.random() * 18;
          const tx = col.pos.x + Math.cos(ang) * dist;
          const tz = col.pos.z + Math.sin(ang) * dist;
          a.scoutTarget = { x: tx, z: tz };
          DN.ants.scriptWalk(
            a, col.entrance.x, col.entrance.z, tx, tz,
            {
              speed: 0.12, curl: 0.12,
              // Stagger scout emergence so they leave one-by-one over
              // the first ~2.5 seconds of the scouting phase instead of
              // all spawning at the mouth simultaneously.
              tStart: -(idx / Math.max(1, arr.length - 1)) * 0.3,
              onArrive: scoutArrivedAtForest
            }
          );
        });
        total += arr.length;
      });
      if (DN.logTerm) DN.logTerm.push('SCOUT', total + ' scouts dispatched from ' + DN.colony.list.length + ' colonies.');
      // No follow() call — the static kickoff framing already shows
      // every colony + the surrounding forest, so scouts walk out
      // within frame without any camera motion at all.
    },
    kg_forming: () => {
      if (DN.crystal) DN.crystal.show();
      if (DN.databridge && DN.databridge.fetchWorldCupKg) {
        DN.databridge.fetchWorldCupKg().then((payload) => {
          const ents = payload.entity_count != null ? payload.entity_count : (payload.entities || []).length;
          const links = payload.relationship_count != null ? payload.relationship_count : (payload.relationships || []).length;
          if (DN.logTerm) DN.logTerm.push('KG', 'KG ready · ' + ents + ' entities · ' + links + ' relationships absorbed by the crystal.');
          if (DN.kgview && DN.kgview.replayGraph) {
            DN.kgview.replayGraph(payload, 'World Cup KG');
          } else if (DN.kgview && DN.kgview.showGraph) {
            DN.kgview.showGraph(payload, 'World Cup KG');
          }
        }).catch(() => { /* no KG yet — crystal still grows from scout deposits */ });
      }
      L._depositTimer = 0;
    },
    recruitment: () => {
      // IMPORTANT: don't wake the idle workers here. If we A.activate()
      // them now they all snap to their entrance position on the next
      // frame — that's the "mass pop out of nowhere" the user reported.
      // The converge phase wakes + walks them in one step using a
      // negative-staggered scriptWalk, so they visibly emerge one by
      // one from each mound. Recruitment is purely a camera + on-chain
      // staging beat now.
      if (DN.logTerm) DN.logTerm.push('BIRTH', 'Population staking on the round — emerging next.');
      if (DN.logTerm) DN.logTerm.push('STAKE', 'Waiting for selected-match forecasts before committing Arc stakes.');
    },
    converge: () => {
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Selected fixture run is feeding the debate and economy.');
      // Send every visible worker to the crystal. To make them read as a
      // single-file line per colony (not a chaotic swarm) we:
      //   • bucket workers by colony
      //   • use ONE shared curl sign per colony (so all curves bow the same way)
      //   • stagger tStart so they're distributed along the trail at frame 1
      //   • tighten laneOffset so the column has minimal lateral spread
      const crystal = DN.crystal ? DN.crystal.position() : new THREE.Vector3(0, 0, 0);
      let count = 0;
      (DN.colony.list || []).forEach((col, ci) => {
        // collect this colony's eligible workers — INCLUDING idle ones
        // (the recruitment phase deliberately left them idle so we wake
        // them here in the same step that gives them their walk).
        const ants = [];
        for (const a of DN.ants.list) {
          if (a.hero) continue;
          if (a.col !== col) continue;
          if (a.state === 'dead') continue;
          ants.push(a);
        }
        if (!ants.length) return;
        // alternating curl signs around the ring so the 7 lines fan out
        // rather than overlapping
        const sign = (ci % 2 === 0) ? 1 : -1;
        // Negative tStart values mean each ant WAITS at the entrance
        // (curve start) for a fraction of a full traversal before its
        // `migT` reaches 0 and walking begins. With speed=0.12 the full
        // path is ~8.3s; tStart range [-0.55, 0] means the slowest ant
        // emerges ~4.5s after the first. That gives a continuous
        // visible stream of ants leaving the mound and walking the
        // ENTIRE path to the crystal — not pre-distributed along it.
        ants.forEach((a, i) => {
          a._homing = false; // reset before new outbound trip
          DN.ants.scriptWalk(
            a, col.entrance.x, col.entrance.z, crystal.x, crystal.z,
            {
              speed: 0.12,
              curl: 0.10,
              curlSign: sign,
              tStart: -(i / Math.max(1, ants.length - 1)) * 0.55,
              onArrive: convergerArrivedAtCrystal
            }
          );
          a.laneOffset = (i % 2 === 0 ? -1 : 1) * 0.08;
          count++;
        });
      });
      if (DN.logTerm) DN.logTerm.push('SYSTEM', count + ' workers converging on the crystal in 7 columns.');
      // No camera change — kickoff framing already shows every colony
      // + the crystal at centre.
    },
    ingress: () => {
      // Workers who are already on their home leg (a._homing === true)
      // are left alone — they're walking home in single file already.
      // Anyone still outbound or stalled gets snapped onto a fast home
      // walk so the surface clears within the 6s phase.
      let homing = 0;
      for (const a of DN.ants.list) {
        if (a.hero) continue;
        if (a.state === 'idle' || a.state === 'dead') continue;
        if (a._homing) continue; // already heading home — don't interrupt
        DN.ants.scriptWalk(
          a, a.x, a.z, a.col.entrance.x, a.col.entrance.z,
          { speed: 0.24, curl: 0.04, onArrive: hideAnt }
        );
        a._homing = true;
        homing++;
      }
      if (homing && DN.logTerm) DN.logTerm.push('SYSTEM', homing + ' stragglers heading underground.');
      if (DN.crystal) DN.crystal.hide();
      // Delay the underground dive by a couple of seconds so the user
      // sees the homing ants actually reach the mounds before the
      // camera cuts to the chamber view.
      const col = DN.colony && DN.colony.list && DN.colony.list[0];
      if (col && DN.app && DN.app.enterColony) {
        setTimeout(() => {
          if (L.phase === 'ingress') DN.app.enterColony(col);
        }, 2200);
      }
    },
    debate: () => {
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Chambers in session — agents exchanging claims.');
      if (DN.underground && DN.underground.startDebate) DN.underground.startDebate();
      // Stream the buffered backend debate text into the chamber bubbles
      // so the underground view visibly shows agents speaking — even
      // though most events were already dispatched and dedup'd during
      // earlier phases.
      if (DN.commsViz && DN.commsViz.streamChambersFromBuffer) {
        DN.commsViz.streamChambersFromBuffer({ count: 22, strideMs: 480 });
      }
    },
    resolution: () => {
      if (DN.underground && DN.underground.stopDebate) DN.underground.stopDebate();
      L.phaseHold = true;
      let released = false;
      const release = () => {
        if (released) return;
        released = true;
        L.phaseHold = false;
        L.phaseT = 0;
      };
      settleRunEconomy().finally(release);
      // Watchdog: if settle hangs on the network the demo still
      // advances to egress_roam after 12s so the user isn't stranded
      // staring at the chamber.
      setTimeout(() => {
        if (!released && DN.logTerm) DN.logTerm.push('SYSTEM', 'Settle still in flight after 12s — advancing to egress so the demo continues.');
        release();
      }, 12000);
    },
    egress_roam: () => {
      // Back to surface; derive per-agent outcome, then have each
      // colony's workers emerge in a single-file line and walk to a
      // shared roam target. The shared per-colony target means all
      // ants from one mound walk one column out together.
      if (DN.app && DN.app.exitColony) DN.app.exitColony();
      deriveOutcomes();
      let woke = 0;
      (DN.colony.list || []).forEach((col, ci) => {
        // One destination per colony — far enough out to be visible.
        const ang = (ci / Math.max(1, (DN.colony.list || []).length)) * Math.PI * 2;
        const r = 30;
        const tx = col.pos.x + Math.cos(ang) * r;
        const tz = col.pos.z + Math.sin(ang) * r;
        const ants = [];
        for (const a of DN.ants.list) {
          if (a.hero) continue;
          if (a.col !== col) continue;
          if (a.outcome === 'culled') continue;
          if (a.state !== 'idle') continue;
          ants.push(a);
        }
        if (!ants.length) return;
        const sign = (ci % 2 === 0) ? 1 : -1;
        ants.forEach((a, i) => {
          // Negative tStart → ants wait at the entrance and emerge one
          // by one over ~5 seconds, walking the full path out.
          DN.ants.scriptWalk(
            a, col.entrance.x, col.entrance.z, tx, tz,
            {
              speed: 0.08,
              curl: 0.10,
              curlSign: sign,
              tStart: -(i / Math.max(1, ants.length - 1)) * 0.45,
              onArrive: roamHop
            }
          );
          a.laneOffset = (i % 2 === 0 ? -1 : 1) * 0.08;
          woke++;
        });
      });
      if (DN.logTerm) DN.logTerm.push('SYSTEM', woke + ' agents emerging in colony columns with their outcomes.');
      // App.exitColony fires its own short close-up flyTo to the colony
      // it dove into (~600ms later). Wait for that to settle, then ease
      // back to the same wide kickoff framing so the outcome cloud is
      // visible across every colony.
      setTimeout(() => {
        if (L.phase === 'egress_roam' && DN.camera && DN.camera.flyTo) {
          DN.camera.flyTo(new THREE.Vector3(0, 0, 0), 190, 120, 2.4);
        }
      }, 1200);
    }
  };

  async function settleRunEconomy() {
    if (!DN.databridge || !DN.databridge.setupForecastDemo || !DN.databridge.settleForecastDemo) {
      if (DN.logTerm) DN.logTerm.push('SETTLE', 'Skipping on-chain economy — forecast API unavailable.');
      return;
    }
    const meta = selectedGameMeta();
    const contract = configuredContract();
    const walletStore = configuredForecastWalletStore();
    // DON'T await startBackendRun() here — it polls until the scouting
    // run reaches "succeeded", which can be minutes (or never). Use
    // whatever run id we already have so settle + egress can proceed.
    const runId = L.runId || (DN.databridge && DN.databridge.runId) || null;
    const marketKey = runMarketKey(meta, runId);
    L.winner = selectedWinner();
    if (DN.logTerm) {
      DN.logTerm.push('STAKE', 'Creating Arc market and staking ant forecasts from ' + (runId || 'fallback demo') + ' …');
    }
    try {
      const setup = await DN.databridge.setupForecastDemo({
        contract: contract || undefined,
        market_key: marketKey,
        market_type: meta.market_type || 'three_way',
        metadata_uri: meta.market_key || marketKey,
        run_id: runId || undefined,
        wallet_store: walletStore || undefined,
        max_stakers: 12,
        wait_for_run_forecasts: true,
        run_forecast_timeout_seconds: 240,
        fee_bps: 1000
      });
      L.marketKey = (setup && setup.market_key) || marketKey;
      L.forecastStakes = (setup && setup.stakes) || [];
      const totals = (setup && setup.totals) || {};
      logForecastChainTrail('STAKE', setup);
      if (DN.logTerm) {
        DN.logTerm.push(
          'STAKE',
          'Stakes committed from ' + ((setup && setup.stake_source) || 'fallback') +
            ' · ' + (totals.total_usdc || '?') + ' USDC escrowed.'
        );
      }

      let winner = L.winner;
      let winnerSide = winnerSideFor(winner, meta);
      let winningAgents = L.forecastStakes
        .filter((stake) => stake.outcome === winnerSide)
        .map((stake) => stake.agent);
      if (!winningAgents.length && L.forecastStakes.length) {
        winnerSide = sideWithLargestStake(L.forecastStakes);
        winner = winnerNameForSide(winnerSide, meta);
        winningAgents = L.forecastStakes
          .filter((stake) => stake.outcome === winnerSide)
          .map((stake) => stake.agent);
        if (DN.logTerm) {
          DN.logTerm.push('SETTLE', 'Selected winner had no staked ants; resolving to staked side ' + winner + ' so payouts can claim.');
        }
      }
      L.winner = winner;
      if (DN.logTerm) DN.logTerm.push('SETTLE', 'Settling Arc market with winner = ' + winner + ' …');
      const settled = await DN.databridge.settleForecastDemo({
        contract: contract || undefined,
        market_key: L.marketKey,
        winner,
        home_team: meta.home_team,
        away_team: meta.away_team,
        wallet_store: walletStore || undefined,
        winning_agents: winningAgents
      });
      logForecastChainTrail('SETTLE', settled);
      const tx = (settled && settled.receipt && settled.receipt.tx_hash) ||
                 (settled && settled.steps && settled.steps.length && (settled.steps[settled.steps.length - 1].receipt || {}).tx_hash) ||
                 null;
      L.settleTxHash = tx;
      if (DN.logTerm) {
        DN.logTerm.push(
          'SETTLE',
          winner + ' settled · ' + winningAgents.length + ' winners claimed' +
            (tx ? ' · tx ' + tx.slice(0, 8) + '…' + tx.slice(-4) : '')
        );
      }
    } catch (err) {
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Economy settlement error: ' + (err && err.message || err));
    }
  }

  function deriveOutcomes() {
    const winnerSide = winnerSideFor(L.winner, selectedGameMeta());
    const forecasts = (DN.databridge && DN.databridge.getCommunications)
      ? DN.databridge.getCommunications().filter(e => e.event_type === 'forecast') : [];
    let correct = 0, wrong = 0;
    for (const f of forecasts) {
      const ant = DN.ants.list.find(a => a.agentRecord && a.agentRecord.agent_id === f.agent_id);
      if (!ant) continue;
      ant.forecast = f;
      if (f.side === 'pass') ant.outcome = 'pending';
      else if (f.side === winnerSide) { ant.outcome = 'correct'; correct++; }
      else { ant.outcome = 'wrong'; wrong++; }
    }
    if (DN.logTerm) DN.logTerm.push('OUTCOME', correct + ' agents correct · ' + wrong + ' wrong (winner = ' + (L.winner || '?') + ')');
    if (DN.ants && DN.ants.showOutcomeGlow) DN.ants.showOutcomeGlow();
    // simple frontend cull rule: wrong forecast + bankroll < 80 → die
    if (DN.ants && DN.ants.list) {
      let culled = 0;
      for (const a of DN.ants.list) {
        if (a.outcome === 'wrong' && a.agentRecord && (a.agentRecord.bankroll || 100) < 80) {
          a.outcome = 'culled';
          a.state = 'dead';
          a.deadTimer = 2.0;
          culled++;
        }
      }
      if (culled && DN.logTerm) DN.logTerm.push('CULL', culled + ' agents fell below the bankroll threshold.');
    }
  }

  // ---- public API -------------------------------------------------------
  L.init = function (scene) {
    L._scene = scene;
    // explicit idle entry
    L.phase = 'idle';
    L.phaseT = 0;
    if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Lifecycle ready — idle. Click Run to start.');
  };

  L.start = function () {
    // Hard reset, then enter phase 1.
    L.phase = 'idle';
    L.phaseT = 0;
    L.winner = null;
    L.settleTxHash = null;
    L.runId = null;
    L.marketKey = null;
    L.forecastStakes = [];
    L.runPromise = null;
    L.runError = null;
    L.phaseHold = false;
    if (ENTER.idle) ENTER.idle();
    enter('kickoff');
  };

  L.reset = function () {
    enter('idle');
  };

  L.getPhase = function () { return L.phase; };

  function enter(next) {
    L.phase = next;
    L.phaseT = 0;
    L.phaseHold = false;
    logPhase(next);
    try { if (ENTER[next]) ENTER[next](); }
    catch (err) { if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Phase enter error: ' + (err && err.message || err)); }
  }

  L.update = function (dt, elapsed) {
    L.phaseT += dt;
    // Per-phase per-frame work
    if (L.phase === 'kg_forming' && DN.crystal) {
      L._depositTimer = (L._depositTimer || 0) + dt;
      while (L._depositTimer > 0.7) {
        DN.crystal.depositOne();
        L._depositTimer -= 0.7;
      }
    }
    if (L.phase === 'debate' && DN.underground && DN.underground.tickDebate) {
      DN.underground.tickDebate(dt, elapsed);
    }
    if (L.phaseHold) return;
    const dur = DURATIONS[L.phase];
    if (isFinite(dur) && L.phaseT >= dur) {
      const next = NEXT[L.phase];
      if (next) enter(next);
    }
  };

  return L;
})();
