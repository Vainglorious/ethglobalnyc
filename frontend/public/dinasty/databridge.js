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
  let records = [], forecasts = [], rooms = [], summary = null;
  let runEvents = [];
  const COL = { debate: '#8E79C4', forecast: '#3FA89F', economy: '#E8A23D', lineage: '#D96E54' };

  const r1 = (n) => Math.round((n || 0) * 10) / 10;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function build(events) {
    records = events.filter((e) => e.event_type === 'agent_record');
    forecasts = events.filter((e) => e.event_type === 'forecast');
    rooms = events.filter((e) => e.event_type === 'debate_room');
    const debates = events.filter((e) => e.event_type === 'debate_claim');
    summary = events.find((e) => e.event_type === 'round_summary') || null;
    B.agents = records;
    B.forecasts = forecasts;
    B.rooms = rooms;
    B.summary = summary;

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
        const agent = records.find((r) => r.agent_id === f.agent_id);
        const nm = (agent && (agent.ens_name || agent.name)) || (f.agent_id || 'agent').replace('_', '-');
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
        (top.ens_name || top.name || top.agent_id) + ' leads the gene pool — ' +
          Math.round(top.accuracy * 100) + '% accuracy, ' + r1(top.bankroll) + ' USDC bankroll.',
        'Lineage', COL.lineage,
      ]);
      if (top.wallet_address) {
        q.push([
          (top.ens_name || top.agent_id) + ' resolves to wallet ' + top.wallet_address.slice(0, 6) + '...' + top.wallet_address.slice(-4) + '.',
          'Identity', COL.lineage,
        ]);
      }
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

  B.getAgents = function () { return records.slice(); };
  B.getRooms = function () { return rooms.slice(); };
  B.getForecasts = function () { return forecasts.slice(); };
  B.getSummary = function () { return summary; };
  B.getAgent = function (agentId) { return records.find((r) => r.agent_id === agentId) || null; };
  B.fetchAgents = function () {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    return fetch(apiUrl + '/ants')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((payload) => {
        records = payload.agents || [];
        B.agents = records;
        return payload;
      });
  };
  B.fetchWorldCupKg = function () {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    return fetch(apiUrl + '/kg/world-cup')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((payload) => {
        B.worldCupKg = payload;
        return payload;
      });
  };
  B.startScoutingRun = function (opts) {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    const body = Object.assign(
      {
        match: 'Brazil vs Morocco',
        data_mode: 'public',
        include_deepseek_scout: true,
        agents: 20,
        rooms: 5,
        seed: 12,
        voice_mode: 'template',
      },
      opts || {},
    );
    return fetch(apiUrl + '/scouting/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => (r.ok ? r.json() : r.text().then((t) => Promise.reject(new Error(t || r.status)))))
      .then((run) => {
        B.runId = run.id;
        if (DN.kgview) DN.kgview.reset('Live scouting KG');
        if (!window.EventSource) return pollScoutingRun(run.id);
        return streamScoutingRun(run.id);
      });
  };

  // Recent ant-to-ant communication events (social_action, debate_claim,
  // forecast) from the latest backend run. The deployed Railway API only
  // exposes /runs and /runs/{run_id}/events (no /recent_communications
  // shortcut), so this method: 1) caches the latest run_id from /runs,
  // 2) downloads the run's events.jsonl, 3) filters client-side.
  let _commsRunId = null;
  let _commsRunId_at = 0;
  function pickLatestRunId() {
    return fetch(apiUrl + '/runs')
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(payload => {
        const runs = payload.runs || [];
        if (!runs.length) return null;
        // The /runs endpoint sorts newest-first; pick the freshest run
        // that has an events.jsonl. Prefer the most recent so in-flight
        // demo runs become visible as soon as they start producing events.
        for (const r of runs) {
          if (r.events_path) return r.id;
        }
        return runs[0].id;
      });
  }
  B.fetchCommunications = function () {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    const now = Date.now();
    const needRunId = !_commsRunId || (now - _commsRunId_at) > 30000;
    const runIdP = needRunId
      ? pickLatestRunId().then(id => { _commsRunId = id; _commsRunId_at = now; B.runId = id; return id; })
      : Promise.resolve(_commsRunId);
    return runIdP.then(runId => {
      if (!runId) return { events: [] };
      return fetch(apiUrl + '/runs/' + encodeURIComponent(runId) + '/events')
        .then(r => r.ok ? r.text() : Promise.reject(r.status))
        .then(txt => {
          const events = parseJsonl(txt).filter(ev => {
            const t = ev && ev.event_type;
            return t === 'social_action' || t === 'debate_claim' || t === 'forecast';
          });
          B._commsEvents = events;
          return { run_id: runId, events };
        });
    });
  };
  B.getCommunications = function () { return B._commsEvents || []; };
  B.getCommsRunId = function () { return _commsRunId; };
  // Bust the cached run id so the next fetchCommunications() re-queries
  // /runs. Called after Run-LLM / scouting completes so we pick up the
  // freshly-created run instead of sticking with the previous one.
  B.resetCommsRun = function (newId) {
    if (newId) {
      _commsRunId = newId;
      _commsRunId_at = Date.now();
      B.runId = newId;
    } else {
      _commsRunId = null;
      _commsRunId_at = 0;
    }
    B._commsEvents = [];
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
    return latestSuccessfulRunId()
      .then((runId) => {
        B.runId = runId;
        B.source = apiUrl + '/runs/' + runId + '/events';
        return loadEvents(B.source);
      });
  }

  function latestSuccessfulRunId() {
    if (!apiUrl) return Promise.reject(new Error('no api url configured'));
    if (B.runId) return Promise.resolve(B.runId);
    return fetch(apiUrl + '/runs')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((payload) => {
        const runs = (payload.runs || []).filter((run) => run.status === 'succeeded');
        if (!runs.length) throw new Error('no successful runs yet');
        return runs[0].id;
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
    const body = Object.assign(
      { agents: 20, rooms: 4, seed: Math.floor(Math.random() * 10000), voice_mode: 'llm' },
      cfg.RUN || {},
      opts || {},
    );
    if (!body.agent_wallets) delete body.wallet_provider;
    if (!body.agent_wallets) delete body.wallet_store;
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

  function pollScoutingRun(runId) {
    return new Promise((resolve, reject) => {
      let tries = 0;
      const timer = setInterval(() => {
        fetch(apiUrl + '/runs/' + runId)
          .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
          .then((run) => {
            if (run.status === 'succeeded') {
              clearInterval(timer);
              Promise.all([
                fetch(apiUrl + '/runs/' + runId + '/kg').then((r) => (r.ok ? r.json() : null)).catch(() => null),
                fetch(apiUrl + '/runs/' + runId + '/kg/manifest').then((r) => (r.ok ? r.json() : null)).catch(() => null),
                fetch(apiUrl + '/runs/' + runId + '/scouting-audit').then((r) => (r.ok ? r.json() : null)).catch(() => null),
              ]).then(([kg, manifest, audit]) => {
                if (DN.kgview && kg) DN.kgview.showGraph(kg, 'Completed scouting KG');
                resolve({ id: runId, run, kg, manifest, audit });
              });
            } else if (run.status === 'failed' || ++tries > 300) {
              clearInterval(timer);
              reject(new Error(run.status === 'failed' ? 'Scouting run failed.' : 'Scouting run timed out.'));
            }
          })
          .catch((err) => {
            clearInterval(timer);
            reject(err);
          });
      }, 1000);
    });
  }

  function streamScoutingRun(runId) {
    return new Promise((resolve, reject) => {
      const source = new EventSource(apiUrl + '/runs/' + runId + '/stream');
      let latestStatus = null;
      source.addEventListener('status', (e) => {
        try {
          latestStatus = JSON.parse(e.data);
          if (DN.kgview && latestStatus.status === 'running') DN.kgview.status('Scouting run is running...');
        } catch (err) {}
      });
      source.addEventListener('colony_event', (e) => {
        try {
          const event = JSON.parse(e.data);
          if (DN.kgview && /^kg_|^scouting_/.test(event.event_type || '')) DN.kgview.ingest(event);
        } catch (err) {}
      });
      source.addEventListener('done', () => {
        source.close();
        if (latestStatus && latestStatus.status === 'failed') {
          reject(new Error('Scouting run failed.'));
          return;
        }
        Promise.all([
          fetch(apiUrl + '/runs/' + runId + '/kg').then((r) => (r.ok ? r.json() : null)).catch(() => null),
          fetch(apiUrl + '/runs/' + runId + '/kg/manifest').then((r) => (r.ok ? r.json() : null)).catch(() => null),
          fetch(apiUrl + '/runs/' + runId + '/scouting-audit').then((r) => (r.ok ? r.json() : null)).catch(() => null),
        ]).then(([kg, manifest, audit]) => {
          if (DN.kgview && kg) DN.kgview.showGraph(kg, 'Completed scouting KG');
          resolve({ id: runId, run: latestStatus, kg, manifest, audit });
        }, reject);
      });
      source.onerror = () => {
        source.close();
        pollScoutingRun(runId).then(resolve, reject);
      };
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
