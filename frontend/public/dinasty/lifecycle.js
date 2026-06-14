// Di-nasty — lifecycle controller. State machine for the demo arc:
//   0 idle → 1 kickoff → 2 scouting → 3 kg_forming → 4 recruitment →
//   5 converge → 6 ingress → 7 debate → 8 resolution → 9 egress_roam
// Frontend-paced (synthetic timing). Owns ant activation + crystal show.
// Phases 4–9 currently no-op except for logging — subsequent passes
// will wire on-chain calls there.
window.DN = window.DN || {};

console.log('[dinasty] lifecycle.js loaded · build 2026-06-14');

DN.lifecycle = (function () {
  const L = { phase: 'idle', phaseT: 0, winner: null, settleTxHash: null, runId: null };

  // duration per phase in seconds; 'idle' and 'egress_roam' are open-ended
  const DURATIONS = {
    idle:        Infinity,
    kickoff:      1.5,
    scouting:     8.0,
    kg_forming:  10.0,
    recruitment:  4.0,
    converge:     6.0,
    ingress:      4.0,
    debate:      10.0,   // user-tuned: 10s of fast multi-agent debate
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

  // Look up the currently selected game's cached metadata (home/away
  // team etc.) so settleForecastDemo has the right `home_team` /
  // `away_team` for the API.
  function selectedGameMeta() {
    const games = (DN.databridge && DN.databridge.forecastGames) || [];
    const key = selectedMatch();
    const found = games.find((g) => g.market_key === key);
    if (found) return found;
    return { market_key: key, home_team: 'Brazil', away_team: 'Morocco' };
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
      { speed: 0.22, curl: 0.1, onArrive: scoutArrivedAtCrystal }
    );
  }
  function scoutArrivedAtCrystal(a) {
    if (DN.crystal && DN.crystal.depositOne) DN.crystal.depositOne();
    // walk back to colony entrance, then disappear (idle)
    DN.ants.scriptWalk(
      a, a.x, a.z, a.col.entrance.x, a.col.entrance.z,
      { speed: 0.24, curl: 0.08, onArrive: hideAnt }
    );
  }
  function convergerArrivedAtCrystal(a) {
    a.hasShard = true;
    DN.ants.scriptWalk(
      a, a.x, a.z, a.col.entrance.x, a.col.entrance.z,
      { speed: 0.20, curl: 0.06, onArrive: hideAnt }
    );
  }
  function hideAnt(a) {
    a.state = 'idle';
    a._idleWritten = false;
    a.scout = false;
    a.hasShard = false;
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
      const col = DN.colony && DN.colony.list && DN.colony.list[0];
      if (col && DN.camera && DN.camera.flyTo) {
        DN.camera.flyTo(col.pos, 38, 26, 1.4);
      }
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Match: ' + selectedMatch());
    },
    scouting: () => {
      // Wake a small scout party per colony, send each on a dedicated
      // Bezier walk to a forest target. On arrival they linger briefly,
      // then return to the crystal in the next phase.
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
            { speed: 0.20, curl: 0.12, onArrive: scoutArrivedAtForest }
          );
        });
        total += arr.length;
      });
      if (DN.logTerm) DN.logTerm.push('SCOUT', total + ' scouts dispatched from ' + DN.colony.list.length + ' colonies.');
      if (DN.camera && DN.camera.follow) {
        DN.camera.follow(() => {
          let cx = 0, cz = 0, n = 0;
          for (const a of DN.ants.list) if (a.scout && a.state !== 'idle') { cx += a.x; cz += a.z; n++; }
          if (!n) return DN.colony.list[0].pos.clone();
          return new THREE.Vector3(cx / n, (DN.world && DN.world.heightAt) ? DN.world.heightAt(cx / n, cz / n) + 1 : 0, cz / n);
        });
      }
    },
    kg_forming: () => {
      if (DN.crystal) DN.crystal.show();
      if (DN.camera && DN.camera.flyTo && DN.crystal) {
        DN.camera.flyTo(DN.crystal.position(), 30, 20, 1.4);
      }
      // Scouts now drop real deposits when they reach the crystal via
      // their scoutArrivedAtCrystal callback — so no synthetic timer.
      L._depositTimer = 0;
    },
    recruitment: () => {
      // Wake the remaining workers.
      let total = 0;
      (DN.colony.list || []).forEach(col => {
        total += DN.ants.activate({ colony: col });
      });
      if (DN.logTerm) DN.logTerm.push('BIRTH', 'Population activated (' + total + ' workers across all colonies).');
      if (DN.camera && DN.camera.flyTo) DN.camera.flyTo(new THREE.Vector3(0, 0, 0), 80, 60, 1.6);
      // On-chain stake setup so the SETTLE call in resolution actually
      // has a market to resolve. Fire-and-forget — we capture the
      // returned market_key on L for later.
      if (DN.databridge && DN.databridge.setupForecastDemo) {
        const meta = selectedGameMeta();
        const contract = configuredContract();
        if (DN.logTerm) DN.logTerm.push('STAKE', 'Staking demo market on ' + (meta.home_team || '?') + ' vs ' + (meta.away_team || '?') + ' …');
        DN.databridge.setupForecastDemo({
          contract: contract || undefined,
          market_key: meta.market_key,
          market_type: meta.market_type || 'three_way',
          home_team: meta.home_team,
          away_team: meta.away_team,
          fee_bps: 1000
        }).then((res) => {
          L.marketKey = (res && res.market_key) || meta.market_key;
          L.forecastStakes = (res && res.stakes) || [];
          if (DN.logTerm) DN.logTerm.push('STAKE', 'Stakes committed · market_key ' + (L.marketKey || '?').slice(-12));
        }).catch((err) => {
          // Non-fatal — settle will skip if no market_key was captured.
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Stake demo error: ' + (err && err.message || err));
        });
      }
    },
    converge: () => {
      // Kick the backend LLM debate run now so it has phases 5→7 (~22s)
      // to compute while ants walk to the crystal and back. The promise
      // resolves only when the run FINISHES (streamRun/pollRun), so we
      // log "ready" then, not "started".
      if (DN.databridge && DN.databridge.startDemoRun) {
        if (DN.logTerm) DN.logTerm.push('SYSTEM', 'LLM debate run kicked off in the background.');
        DN.databridge.startDemoRun().then(res => {
          if (res && res.id) {
            L.runId = res.id;
            if (DN.databridge.resetCommsRun) DN.databridge.resetCommsRun(res.id);
            if (DN.commsViz && DN.commsViz.reset) DN.commsViz.reset();
            if (DN.hud && DN.hud._pollComms) DN.hud._pollComms();
            if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Backend run ' + res.id + ' complete — debate events ready.');
          }
        }).catch(err => {
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Backend run failed: ' + (err && err.message || err));
        });
      }
      // Send every visible worker to the crystal, then home to its
      // colony entrance, where it disappears underground.
      const crystal = DN.crystal ? DN.crystal.position() : new THREE.Vector3(0, 0, 0);
      let count = 0;
      for (const a of DN.ants.list) {
        if (a.hero) continue;                    // heroes stay
        if (a.state === 'idle' || a.state === 'dead') continue;
        DN.ants.scriptWalk(
          a, a.x, a.z, crystal.x, crystal.z,
          { speed: 0.22, curl: 0.08, onArrive: convergerArrivedAtCrystal }
        );
        count++;
      }
      if (DN.logTerm) DN.logTerm.push('SYSTEM', count + ' workers converging on the knowledge crystal.');
      if (DN.camera && DN.camera.flyTo && DN.crystal) {
        DN.camera.flyTo(crystal, 32, 22, 1.2);
      }
    },
    ingress: () => {
      // Workers are mid-walk back from the crystal — point any still
      // outside straight to their entrance at a brisk pace so the
      // surface is clean by the time we dive.
      let homing = 0;
      for (const a of DN.ants.list) {
        if (a.hero) continue;
        if (a.state === 'idle' || a.state === 'dead') continue;
        DN.ants.scriptWalk(
          a, a.x, a.z, a.col.entrance.x, a.col.entrance.z,
          { speed: 0.36, curl: 0.04, onArrive: hideAnt }
        );
        homing++;
      }
      if (homing && DN.logTerm) DN.logTerm.push('SYSTEM', homing + ' workers heading underground.');
      // Crystal's job is done.
      if (DN.crystal) DN.crystal.hide();
      // Dive into the closest colony.
      const col = DN.colony && DN.colony.list && DN.colony.list[0];
      if (col && DN.app && DN.app.enterColony) {
        DN.app.enterColony(col);
      }
    },
    debate: () => {
      // Underground ants already mill + debate via commsViz arcs as the
      // backend events arrive. We also paint a fast burst of in-chamber
      // glow arcs so the user visibly sees agents arguing for ~10 sec.
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Chambers in session — agents exchanging claims.');
      if (DN.underground && DN.underground.startDebate) DN.underground.startDebate();
    },
    resolution: async () => {
      // Stop the in-chamber debate animation; chambers fall quiet.
      if (DN.underground && DN.underground.stopDebate) DN.underground.stopDebate();
      const winner = selectedWinner();
      L.winner = winner;
      if (!L.marketKey) {
        if (DN.logTerm) DN.logTerm.push('SETTLE', 'Skipping on-chain settle — no market_key captured (stake demo failed?).');
        return;
      }
      const meta = selectedGameMeta();
      const contract = configuredContract();
      const winnerSide = WINNER_TO_SIDE[winner] || 'home';
      const winningAgents = (L.forecastStakes || [])
        .filter((s) => s.outcome === winnerSide)
        .map((s) => s.agent);
      if (DN.logTerm) DN.logTerm.push('SETTLE', 'Settling market with winner = ' + winner + ' …');
      try {
        const r = await DN.databridge.settleForecastDemo({
          contract: contract || undefined,
          market_key: L.marketKey,
          winner,
          home_team: meta.home_team,
          away_team: meta.away_team,
          winning_agents: winningAgents
        });
        const tx = (r && r.receipt && r.receipt.tx_hash) ||
                   (r && r.steps && r.steps.length && (r.steps[r.steps.length - 1].receipt || {}).tx_hash) ||
                   null;
        L.settleTxHash = tx;
        if (DN.logTerm) DN.logTerm.push('SETTLE', winner + ' settled' + (tx ? ' · tx ' + tx.slice(0, 8) + '…' + tx.slice(-4) : ''));
      } catch (err) {
        if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Settle error: ' + (err && err.message || err));
      }
    },
    egress_roam: () => {
      // Back to surface; derive per-agent outcome from settled winner +
      // their forecast.side. Sets a.outcome on every bound ant, then
      // walks ants out of their colonies to roam.
      if (DN.app && DN.app.exitColony) DN.app.exitColony();
      deriveOutcomes();
      // Wake everyone (except culled) and put them on a small roam loop.
      let woke = 0;
      for (const a of DN.ants.list) {
        if (a.hero) continue;
        if (a.outcome === 'culled') continue;
        if (a.state !== 'idle') continue;
        // Pick a random roam destination 18-35 units from the colony.
        const ang = Math.random() * Math.PI * 2;
        const r = 18 + Math.random() * 18;
        const tx = a.col.entrance.x + Math.cos(ang) * r;
        const tz = a.col.entrance.z + Math.sin(ang) * r;
        DN.ants.scriptWalk(
          a, a.col.entrance.x, a.col.entrance.z, tx, tz,
          { speed: 0.10, curl: 0.16, onArrive: roamHop }
        );
        woke++;
      }
      if (DN.logTerm) DN.logTerm.push('SYSTEM', woke + ' agents emerging with their outcomes.');
      if (DN.camera && DN.camera.flyTo) DN.camera.flyTo(new THREE.Vector3(0, 0, 0), 80, 60, 1.4);
    }
  };

  // Map UI winner → backend forecast.side
  const WINNER_TO_SIDE = { Brazil: 'home', Morocco: 'away', Draw: 'pass' };

  function deriveOutcomes() {
    const winnerSide = WINNER_TO_SIDE[L.winner] || 'home';
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
    const dur = DURATIONS[L.phase];
    if (isFinite(dur) && L.phaseT >= dur) {
      const next = NEXT[L.phase];
      if (next) enter(next);
    }
  };

  return L;
})();
