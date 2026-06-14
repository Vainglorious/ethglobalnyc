// WorldColony — data bridge: seeds the colonies' stats and the thoughts ticker
// from the REAL harness output. Non-invasive: main.js
// prefers DN.databridge.nextThought() when ready, and we seed DN.colony.list
// stats once the colonies exist. Everything degrades gracefully if the file
// is missing (the app falls back to its synthetic content).
window.DN = window.DN || {};

DN.databridge = (function () {
  const cfg = window.DN_CONFIG || {};
  const apiUrl = (cfg.API_URL || '').replace(/\/$/, '');
  const B = { ready: false, source: null, apiUrl, runId: null };
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
          ' agents (' + summary.home_bets + ' home · ' + (summary.draw_bets || 0) + ' draw · ' + summary.away_bets + ' away).',
        'Forecast', COL.economy,
      ]);
    }
    // real debate transcript lines (already human-readable)
    debates.forEach((d) => {
      if (d.message) q.push([d.message, 'Debate', COL.debate]);
    });
    // strongest real bets
    forecasts
      .filter((f) => f.side && f.stake > 0)
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

  function apiJson(path, options) {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    return fetch(apiUrl + path, options || {})
      .then((r) => {
        if (r.ok) return r.json();
        return r.text().then((t) => {
          let message = t || String(r.status);
          try {
            const parsed = JSON.parse(t);
            message = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail || parsed);
          } catch (err) {}
          throw new Error(message);
        });
      });
  }

  B.fetchForecastConfig = function () {
    return apiJson('/forecast/config');
  };

  B.fetchForecastGames = function () {
    return apiJson('/forecast/games')
      .then((payload) => {
        B.forecastGames = payload.games || [];
        return payload;
      });
  };

  B.deployForecastContract = function (opts) {
    return apiJson('/forecast/deploy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts || {}),
    });
  };

  B.setupForecastDemo = function (opts) {
    const body = Object.assign(
      {
        market_type: 'three_way',
        fee_bps: 1000,
      },
      opts || {},
    );
    return apiJson('/forecast/demo-setup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  };

  B.settleForecastDemo = function (opts) {
    return apiJson('/forecast/settle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(opts || {}),
    });
  };

  B.fetchForecastTotals = function (opts) {
    const params = new URLSearchParams();
    if (opts && opts.contract) params.set('contract', opts.contract);
    if (opts && opts.market_key) params.set('market_key', opts.market_key);
    return apiJson('/forecast/totals' + (params.toString() ? '?' + params.toString() : ''));
  };

  B.fetchX402Config = function () {
    return apiJson('/x402/config');
  };

  B.runX402DemoPayment = function (opts) {
    const body = Object.assign(
      {
        buyer: 'ant_0001',
        seller: 'ant_0002',
        service: 'finding_private',
        round_id: 'worldcup:2026:brazil-morocco:x402-demo',
        resource_id: 'kg:worldcup:brazil-morocco:private-scout-signal',
        topic: 'Brazil vs Morocco',
      },
      opts || {},
    );
    return apiJson('/x402/demo-payment', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  };

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

  B.reproduceAnt = function (opts) {
    const body = Object.assign(
      {
        mutation_rate: 0.08,
        fund_wallet: true,
        fund_amount: '0.05',
        broadcast_funding: true,
        publish_ens: true,
        broadcast_ens: true,
      },
      opts || {},
    );
    return apiJson('/ants/reproduce', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((payload) => {
      const child = payload.child || null;
      if (child) {
        records = records.filter((r) => r.agent_id !== child.agent_id).concat([child]);
        B.agents = records;
      }
      return payload;
    });
  };

  B.killAnt = function (agentId, opts) {
    if (!agentId) return Promise.reject(new Error('Missing agent id.'));
    const body = Object.assign({ reason: 'manual' }, opts || {});
    return apiJson('/ants/' + encodeURIComponent(agentId) + '/kill', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((payload) => {
      const ant = payload.ant || null;
      if (ant) {
        records = records.map((r) => (r.agent_id === ant.agent_id ? ant : r));
        if (!records.some((r) => r.agent_id === ant.agent_id)) records.push(ant);
        B.agents = records;
      }
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

  function kgMatchKey(value) {
    return String(value || '')
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  function runMatchesScoutingTarget(run, opts) {
    if (!run || run.kind !== 'scouting' || run.status !== 'succeeded') return false;
    opts = opts || {};
    const wantedId = opts.match_id || opts.market_key || '';
    const wantedName = kgMatchKey(opts.match || opts.name || '');
    const runId = run.match_id || '';
    const runName = kgMatchKey(run.match || '');
    if (wantedId && runId && wantedId === runId) return true;
    if (wantedName && runName && wantedName === runName) return true;
    const command = Array.isArray(run.command) ? run.command.map(String) : [];
    return Boolean(
      (wantedId && command.includes(wantedId)) ||
      (wantedName && command.some((part) => kgMatchKey(part) === wantedName))
    );
  }

  B.fetchRuns = function () {
    return apiJson('/runs')
      .then((payload) => {
        B.runs = payload.runs || [];
        return payload;
      });
  };

  B.fetchRunKg = function (runId) {
    if (!runId) return Promise.reject(new Error('run id required'));
    return apiJson('/runs/' + encodeURIComponent(runId) + '/kg')
      .then((payload) => {
        payload.source_run_id = runId;
        return payload;
      });
  };

  B.fetchScoutingKgForMatch = function (opts) {
    return B.fetchRuns()
      .then((payload) => {
        const runs = (payload.runs || []).filter((run) => runMatchesScoutingTarget(run, opts));
        function tryRun(index) {
          const run = runs[index];
          if (!run) return null;
          return B.fetchRunKg(run.id)
            .then((kg) => {
              kg.source_run = run;
              kg.source_run_id = run.id;
              return kg;
            })
            .catch(() => tryRun(index + 1));
        }
        return tryRun(0);
      });
  };

  function compactScoutingLabel(value, max) {
    const label = String(value || '').replace(/_/g, ' ');
    return label.length > max ? label.slice(0, max - 3) + '...' : label;
  }

  function scoutingEventLog(event, graphChange) {
    if (!event || !event.event_type) return null;
    if (event.event_type === 'run_log') {
      return {
        level: event.stream === 'stderr' ? 'STDERR' : 'RUN',
        message: event.message || '',
      };
    }
    if (event.event_type === 'kg_stage') {
      const stage = compactScoutingLabel(event.stage || 'kg_stage', 44);
      const match = event.match ? ' · ' + event.match : '';
      return { level: 'SCOUT', message: 'Stage: ' + stage + match };
    }
    if (event.event_type === 'kg_entity') {
      const action = graphChange && graphChange.action === 'updated' ? 'Updated node' : 'New node';
      const type = graphChange && graphChange.type ? ' · ' + compactScoutingLabel(graphChange.type, 24) : '';
      const label = graphChange && graphChange.label ? graphChange.label : 'KG entity';
      return { level: 'KG', message: action + ': ' + compactScoutingLabel(label, 72) + type };
    }
    if (event.event_type === 'kg_relationship') {
      const rel = graphChange && graphChange.relation ? compactScoutingLabel(graphChange.relation, 36) : 'related_to';
      const source = graphChange && graphChange.source ? compactScoutingLabel(graphChange.source, 28) : 'source';
      const target = graphChange && graphChange.target ? compactScoutingLabel(graphChange.target, 28) : 'target';
      return { level: 'KG', message: 'Linked nodes: ' + source + ' -> ' + target + ' · ' + rel };
    }
    if (event.event_type === 'kg_manifest') {
      const manifest = event.manifest || {};
      return {
        level: 'KG',
        message: 'Manifest ready: ' + (manifest.entity_count || 0) + ' entities · ' + (manifest.relationship_count || 0) + ' links',
      };
    }
    if (event.event_type === 'scouting_audit') {
      const backlog = event.backlog_count == null ? 'n/a' : event.backlog_count;
      return { level: 'SCOUT', message: 'Audit complete · backlog ' + backlog };
    }
    if (/scout|scouting/i.test(event.event_type)) {
      return { level: 'SCOUT', message: compactScoutingLabel(event.event_type, 48) };
    }
    return null;
  }

  function pushScoutingLog(event, graphChange) {
    if (!DN.logTerm) return;
    const row = scoutingEventLog(event, graphChange);
    if (row) DN.logTerm.push(row.level, row.message);
  }

  function showCompletedScoutingGraph(kg, opts) {
    if (!DN.kgview || !kg) return;
    opts = opts || {};
    if (DN.kgview.replayGraph) {
      DN.kgview.replayGraph(kg, 'Completed scouting KG', {
        entityChunk: 10,
        relationshipChunk: 80,
        delayMs: 220,
        onComplete: opts.onComplete,
      });
    } else {
      DN.kgview.showGraph(kg, 'Completed scouting KG');
      if (typeof opts.onComplete === 'function') opts.onComplete();
    }
  }

  B.startScoutingRun = function (opts) {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    const body = Object.assign(
      {
        match: 'Brazil vs Morocco',
        data_mode: 'openfootball',
        include_deepseek_scout: false,
        agents: 20,
        rooms: 4,
        seed: 12,
        voice_mode: 'template',
      },
      opts || {},
    );
    const showGraphOnComplete = body.show_completed_graph !== false;
    delete body.show_completed_graph;
    if (DN.logTerm) DN.logTerm.push('SCOUT', 'Submitting scouting run for ' + body.match + '...');
    return fetch(apiUrl + '/scouting/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then((r) => (r.ok ? r.json() : r.text().then((t) => Promise.reject(new Error(t || r.status)))))
      .then((run) => {
        B.runId = run.id;
        if (B.resetCommsRun) B.resetCommsRun(run.id);
        if (DN.kgview && DN.kgview.showScoutingProgress) {
          DN.kgview.showScoutingProgress({
            match: body.match,
            matchId: body.match_id,
          });
        } else if (DN.kgview) {
          DN.kgview.reset('Live scouting KG');
        }
        if (DN.logTerm) DN.logTerm.push('SCOUT', 'Run ' + run.id + ' queued · opening event stream.');
        if (!window.EventSource) return pollScoutingRun(run.id, { showGraphOnComplete });
        return streamScoutingRun(run.id, { showGraphOnComplete });
      });
  };

  // Recent ant-to-ant communication events (social_action, debate_claim,
  // forecast) from the latest backend run. The deployed Railway API only
  // exposes /runs and /runs/{run_id}/events (no /recent_communications
  // shortcut), so this method: 1) caches the latest run_id from /runs,
  // 2) downloads the run's events.jsonl, 3) filters client-side.
  let _commsRunId = null;
  let _commsRunId_at = 0;
  let _commsRunPinned = false;
  function pickLatestRunId() {
    return fetch(apiUrl + '/runs')
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(payload => {
        const runs = payload.runs || [];
        if (!runs.length) return null;
        const isScout = (r) => r && (r.kind === 'scouting' || String(r.id || '').startsWith('scout_'));
        for (const r of runs) {
          if (r.events_path && !isScout(r)) return r.id;
        }
        for (const r of runs) {
          if (r.events_path) return r.id;
        }
        return runs[0].id;
      });
  }
  B.fetchCommunications = function () {
    if (!apiUrl) return Promise.reject(new Error('No backend API configured.'));
    // Only fetch events for the run the lifecycle EXPLICITLY pinned
    // via resetCommsRun(id). Without an active run we return empty —
    // otherwise the page-load poll would auto-pick the most recent run
    // on the server (often a stale scout run from a previous demo) and
    // start replaying its DISPUTE/SPEAK rows the moment you load the
    // app, before the user has clicked Run.
    if (!_commsRunId) return Promise.resolve({ events: [] });
    const runId = _commsRunId;
    B.runId = runId;
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
      _commsRunPinned = true;
      B.runId = newId;
    } else {
      _commsRunId = null;
      _commsRunId_at = 0;
      _commsRunPinned = false;
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
      const timer = setInterval(() => {
        fetch(apiUrl + '/runs/' + runId)
          .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
          .then((run) => {
            if (run.status === 'succeeded') {
              clearInterval(timer);
              B.loadRun(runId).then(resolve, reject);
            } else if (run.status === 'failed') {
              clearInterval(timer);
              reject(new Error('Backend run failed.'));
            }
          })
          .catch((err) => {
            clearInterval(timer);
            reject(err);
          });
      }, 1000);
    });
  }

  function pollScoutingRun(runId, opts) {
    opts = opts || {};
    return new Promise((resolve, reject) => {
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
                if (opts.showGraphOnComplete !== false) showCompletedScoutingGraph(kg);
                resolve({ id: runId, run, kg, manifest, audit });
              });
            } else if (run.status === 'failed') {
              clearInterval(timer);
              reject(new Error('Scouting run failed.'));
            }
          })
          .catch((err) => {
            clearInterval(timer);
            reject(err);
          });
      }, 1000);
    });
  }

  function streamScoutingRun(runId, opts) {
    opts = opts || {};
    return new Promise((resolve, reject) => {
      const source = new EventSource(apiUrl + '/runs/' + runId + '/stream');
      let latestStatus = null;
      source.addEventListener('status', (e) => {
        try {
          latestStatus = JSON.parse(e.data);
          if (DN.kgview && latestStatus.status === 'running') DN.kgview.status('Scouting run is running...');
          if (DN.logTerm && latestStatus.status) DN.logTerm.push('SCOUT', 'Run status: ' + latestStatus.status);
        } catch (err) {}
      });
      source.addEventListener('colony_event', (e) => {
        try {
          const event = JSON.parse(e.data);
          const graphChange = DN.kgview && /^kg_|^scouting_/.test(event.event_type || '') ? DN.kgview.ingest(event) : null;
          pushScoutingLog(event, graphChange);
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
          if (opts.showGraphOnComplete !== false) showCompletedScoutingGraph(kg);
          resolve({ id: runId, run: latestStatus, kg, manifest, audit });
        }, reject);
      });
      source.onerror = () => {
        source.close();
        pollScoutingRun(runId, opts).then(resolve, reject);
      };
    });
  }

  function streamRun(runId) {
    return new Promise((resolve, reject) => {
      const source = new EventSource(apiUrl + '/runs/' + runId + '/stream');
      source.addEventListener('colony_event', (e) => {
        try {
          const event = JSON.parse(e.data);
          runEvents.push(event);
          pushScoutingLog(event);
        } catch (err) {}
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
    if (!apiUrl) return;
    loadLatestRailwayRun()
      .catch(() => {
        if (DN.logTerm) DN.logTerm.push('SYSTEM', 'No completed backend run loaded yet.');
      });
  }

  load();
  return B;
})();
