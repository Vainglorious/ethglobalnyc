// Di-nasty — data bridge: seeds the colonies' stats and the thoughts ticker
// from the REAL harness output. Non-invasive: main.js
// prefers DN.databridge.nextThought() when ready, and we seed DN.colony.list
// stats once the colonies exist. Everything degrades gracefully if the file
// is missing (the app falls back to its synthetic content).
window.DN = window.DN || {};

DN.databridge = (function () {
  const cfg = window.DN_CONFIG || {};
  const apiUrl = (cfg.API_URL || '').replace(/\/$/, '');
  const B = { ready: false, source: '/data/demo.jsonl', apiUrl, runId: null };
  let thoughts = [];
  let ti = 0;
  let records = [], forecasts = [], summary = null;
  let runEvents = [];
  const COL = { debate: '#8E79C4', forecast: '#3FA89F', economy: '#E8A23D', lineage: '#D96E54' };

  const r1 = (n) => Math.round((n || 0) * 10) / 10;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function build(events) {
    records = events.filter((e) => e.event_type === 'agent_record');
    forecasts = events.filter((e) => e.event_type === 'forecast');
    const debates = events.filter((e) => e.event_type === 'debate_claim');
    summary = events.find((e) => e.event_type === 'round_summary') || null;

    const q = [];
    if (summary) {
      q.push([
        'Round resolved — market home probability ' +
          Math.round(summary.market_home_probability * 100) +
          '%, $' + r1(summary.total_staked) + ' staked across ' + summary.population +
          ' agents (' + summary.home_bets + ' home · ' + summary.away_bets + ' away · ' + summary.passes + ' pass).',
        'Forecast', COL.economy,
      ]);
    }
    // real debate transcript lines (already human-readable)
    debates.forEach((d) => {
      if (d.message) q.push([d.message, 'Debate', COL.debate]);
    });
    // strongest real bets
    forecasts
      .filter((f) => f.side && f.side !== 'pass' && f.stake > 0)
      .sort((a, b) => b.stake - a.stake)
      .slice(0, 8)
      .forEach((f) => {
        const nm = (f.agent_id || 'agent').replace('_', '-');
        q.push([
          nm + ' commits ' + r1(f.stake) + ' USDC ' + f.side + ' @ ' +
            Math.round(f.home_probability * 100) + '% (edge ' + r1(f.edge) + ')',
          'Forecast', COL.forecast,
        ]);
      });
    // lineage leader
    const top = records.slice().sort((a, b) => b.bankroll - a.bankroll)[0];
    if (top) {
      q.push([
        (top.name || top.agent_id) + ' leads the gene pool — ' +
          Math.round(top.accuracy * 100) + '% accuracy, ' + r1(top.bankroll) + ' USDC bankroll.',
        'Lineage', COL.lineage,
      ]);
    }
    if (q.length) thoughts = q;
    B.ready = thoughts.length > 0;
  }

  // seed colony stats from the real agents, split across the factions
  function applyStats() {
    if (!DN.colony || !DN.colony.list || !DN.colony.list.length || !records.length) return false;
    const stakeByAgent = {};
    forecasts.forEach((f) => { stakeByAgent[f.agent_id] = f.stake || 0; });
    const n = DN.colony.list.length;
    DN.colony.list.forEach((c, i) => {
      const grp = records.filter((_, idx) => idx % n === i);
      if (!grp.length) return;
      const accAvg = grp.reduce((s, r) => s + r.accuracy, 0) / grp.length;
      const bankAvg = grp.reduce((s, r) => s + r.bankroll, 0) / grp.length;
      const treasury = grp.reduce((s, r) => s + r.bankroll, 0); // ~real USDC held
      const stakedNow = grp.reduce((s, r) => s + (stakeByAgent[r.agent_id] || 0), 0);
      c.stats.population = grp.length;
      c.stats.accuracy = Math.round(accAvg * 100);
      c.stats.rep = clamp(Math.round(accAvg * 100), 5, 99);
      c.stats.staked = treasury + stakedNow * 50; // displayed as $/1000 → ~1.0k
      c.stats.food = clamp(Math.round((bankAvg - 80) * 3.2), 12, 100);
      c.stats.health = clamp(Math.round(40 + (accAvg - 0.4) * 200), 25, 99);
      c.stats.gen = (records[0] && records[0].generation != null ? records[0].generation : 0) + 1;
    });
    return true;
  }

  B.nextThought = function () {
    if (!thoughts.length) return null;
    const t = thoughts[ti % thoughts.length];
    ti++;
    return t;
  };

  function parseJsonl(txt) {
    return txt
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => { try { return JSON.parse(l); } catch (e) { return null; } })
      .filter(Boolean);
  }

  function seedStats() {
    let tries = 0;
    const seed = setInterval(() => {
      if (applyStats() || ++tries > 60) clearInterval(seed);
    }, 250);
  }

  function loadEvents(source) {
    return fetch(source)
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then((txt) => {
        const events = parseJsonl(txt);
        build(events);
        seedStats();
      });
  }

  function loadLatestRailwayRun() {
    if (!apiUrl) return Promise.reject(new Error('no api url configured'));
    return fetch(apiUrl + '/runs')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((payload) => {
        const runs = (payload.runs || []).filter((run) => run.status === 'succeeded');
        if (!runs.length) throw new Error('no successful runs yet');
        const latest = runs[0];
        B.runId = latest.id;
        B.source = apiUrl + '/runs/' + latest.id + '/events';
        return loadEvents(B.source);
      });
  }

  B.loadRun = function (runId) {
    if (!apiUrl || !runId) return Promise.reject(new Error('api url and run id required'));
    B.runId = runId;
    B.source = apiUrl + '/runs/' + runId + '/events';
    return loadEvents(B.source);
  };

  B.startDemoRun = function (opts) {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    const body = Object.assign({ agents: 20, rooms: 4, seed: Math.floor(Math.random() * 10000), voice_mode: 'llm' }, opts || {});
    runEvents = [];
    B.ready = false;
    return fetch(apiUrl + '/runs/demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => (r.ok ? r.json() : r.text().then((t) => Promise.reject(new Error(t || r.status)))))
      .then((run) => {
        B.runId = run.id;
        B.source = apiUrl + '/runs/' + run.id + '/events';
        if (!window.EventSource) return pollRun(run.id);
        return streamRun(run.id);
      });
  };

  function pollRun(runId) {
    return new Promise((resolve, reject) => {
      let tries = 0;
      const timer = setInterval(() => {
        fetch(apiUrl + '/runs/' + runId)
          .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
          .then((run) => {
            if (run.status === 'succeeded') {
              clearInterval(timer);
              B.loadRun(runId).then(resolve, reject);
            } else if (run.status === 'failed' || ++tries > 120) {
              clearInterval(timer);
              reject(new Error(run.status === 'failed' ? 'Backend run failed.' : 'Backend run timed out.'));
            }
          })
          .catch((err) => {
            clearInterval(timer);
            reject(err);
          });
      }, 1000);
    });
  }

  function streamRun(runId) {
    return new Promise((resolve, reject) => {
      const source = new EventSource(apiUrl + '/runs/' + runId + '/stream');
      source.addEventListener('colony_event', (e) => {
        try { runEvents.push(JSON.parse(e.data)); } catch (err) {}
      });
      source.addEventListener('done', () => {
        source.close();
        if (runEvents.length) {
          build(runEvents);
          seedStats();
          resolve({ id: runId, events: runEvents.length });
        } else {
          B.loadRun(runId).then(resolve, reject);
        }
      });
      source.onerror = () => {
        source.close();
        pollRun(runId).then(resolve, reject);
      };
    });
  }

  function load() {
    loadLatestRailwayRun()
      .catch(() => loadEvents('/data/demo.jsonl'))
      .catch(() => { /* no data file — app keeps its synthetic content */ });
  }

  load();
  return B;
})();
