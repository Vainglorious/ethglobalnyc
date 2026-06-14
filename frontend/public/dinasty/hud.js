// Di-nasty — HUD: top stats, inspector, thoughts, transport, hotbar, banners
window.DN = window.DN || {};

DN.hud = (function () {
  const H = {};
  const $ = id => document.getElementById(id);
  function hex(n) { return '#' + n.toString(16).padStart(6, '0'); }
  function cap(s) { return s.replace(/^./, c => c.toUpperCase()); }

  const ICON = {
    forage: '<svg viewBox="0 0 24 24"><path d="M4 18c4-1 4-6 8-6s4 5 8 4"/><circle cx="4" cy="18" r="1.4"/><circle cx="20" cy="16" r="1.4"/></svg>',
    defend: '<svg viewBox="0 0 24 24"><path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6z"/></svg>',
    expand: '<svg viewBox="0 0 24 24"><path d="M5 9V5h4M19 9V5h-4M5 15v4h4M19 15v4h-4"/></svg>'
  };
  const HOTBAR = [
    { id: 'world', name: 'World', svg: '<path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/><circle cx="12" cy="12" r="9"/>' },
    { id: 'colonies', name: 'Colonies', svg: '<path d="M4 20l4-11 4 11M12 20l4-9 4 9"/><circle cx="8" cy="6" r="1.5"/><circle cx="16" cy="8" r="1.5"/>' },
    { id: 'agents', name: 'Agents', svg: '<circle cx="12" cy="7" r="3"/><path d="M5 20c0-4 3-6 7-6s7 2 7 6"/>' },
    { id: 'economy', name: 'Economy', svg: '<circle cx="12" cy="12" r="8"/><path d="M9 9.5C9 8 10.3 7.5 12 7.5s3 .8 3 2-1.3 1.8-3 2-3 .8-3 2 1.3 2 3 2 3-.6 3-2M12 6v1.5M12 16.5V18"/>' },
    { id: 'forecasts', name: 'Forecasts', svg: '<path d="M4 16l4-5 4 3 6-8"/><path d="M14 6h4v4"/>' },
    { id: 'lineages', name: 'Lineages', svg: '<circle cx="12" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="19" r="2"/><path d="M12 7v4M12 11l-6 6M12 11l6 6"/>' }
  ];

  H.init = function () {
    // hotbar
    $('hotbar').innerHTML = HOTBAR.map((s, i) =>
      `<div class="slot${i === 0 ? ' active' : ''}" data-lens="${s.id}" data-idx="${i}">
        <span class="sl-key">${i + 1}</span>
        <svg viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round">${s.svg}</svg>
        <span class="sl-name">${s.name}</span></div>`).join('');
    $('hotbar').querySelectorAll('.slot').forEach(el => el.addEventListener('click', () => DN.app.setLens(parseInt(el.dataset.idx))));
    // region selector
    $('regions').innerHTML = '<div class="reg-title">Region</div>' + DN.biomes.map((b, i) =>
      `<div class="reg${i === 0 ? ' active' : ''}" data-i="${i}"><span class="reg-dot" style="background:${hex(b.ground.grass)};color:${hex(b.ground.grass)}"></span><div class="reg-tx"><div class="reg-name">${b.name}</div><div class="reg-tag">${b.tag}</div></div></div>`).join('');
    $('regions').querySelectorAll('.reg').forEach(el => el.addEventListener('click', () => DN.app.setBiome(parseInt(el.dataset.i))));
    initBackendControl();
    H.clearInspector();
    return H;
  };

  function initBackendControl() {
    const root = $('backend');
    if (!root) return;
    root.innerHTML =
      '<div class="backend-copy"><div class="backend-k">Backend</div><div class="backend-s" id="backend-status">Railway linked</div></div>' +
      '<div class="backend-actions">' +
        '<button class="backend-btn secondary" id="backend-ants">Get ants</button>' +
        '<button class="backend-btn secondary" id="backend-kg">Get KG</button>' +
        '<button class="backend-btn secondary" id="backend-scout">Run scouting</button>' +
        '<button class="backend-btn" id="backend-run">Run LLM agents</button>' +
        '<select class="forecast-game-select" id="forecast-game" aria-label="Game">' +
          '<option value="match:world_cup_2026:013:2026_06_13_brazil_morocco">Brazil vs Morocco</option>' +
        '</select>' +
        '<button class="backend-btn secondary" id="forecast-deploy">Deploy</button>' +
        '<button class="backend-btn secondary" id="x402-buy">Buy KG</button>' +
        '<button class="backend-btn secondary" id="forecast-setup">Stake demo</button>' +
        '<select class="forecast-select" id="forecast-winner" aria-label="Winner">' +
          '<option value="Brazil">Brazil</option>' +
          '<option value="Draw">Draw</option>' +
          '<option value="Morocco">Morocco</option>' +
        '</select>' +
        '<button class="backend-btn" id="forecast-settle">Settle</button>' +
      '</div>';
    const btn = $('backend-run');
    const antsBtn = $('backend-ants');
    const kgBtn = $('backend-kg');
    const scoutBtn = $('backend-scout');
    const forecastDeployBtn = $('forecast-deploy');
    const x402BuyBtn = $('x402-buy');
    const forecastSetupBtn = $('forecast-setup');
    const forecastSettleBtn = $('forecast-settle');
    const forecastWinner = $('forecast-winner');
    const forecastGame = $('forecast-game');
    const status = $('backend-status');
    const forecastCfg = (window.DN_CONFIG && window.DN_CONFIG.FORECAST) || {};
    let forecastContract = forecastCfg.CONTRACT || '';
    let forecastMarketKey = '';
    let forecastStakes = [];
    let selectedGame = {
      market_key: 'match:world_cup_2026:013:2026_06_13_brazil_morocco',
      market_type: 'three_way',
      home_team: forecastCfg.HOME_TEAM || 'Brazil',
      away_team: forecastCfg.AWAY_TEAM || 'Morocco',
      name: (forecastCfg.HOME_TEAM || 'Brazil') + ' vs ' + (forecastCfg.AWAY_TEAM || 'Morocco'),
    };

    function updateWinnerOptions() {
      if (!forecastWinner) return;
      const drawOption = selectedGame.market_type === 'binary' ? '' : '<option value="Draw">Draw</option>';
      forecastWinner.innerHTML =
        '<option value="' + selectedGame.home_team + '">' + selectedGame.home_team + '</option>' +
        drawOption +
        '<option value="' + selectedGame.away_team + '">' + selectedGame.away_team + '</option>';
    }

    function shortHash(value) {
      if (!value || value.length < 12) return value || '';
      return value.slice(0, 6) + '...' + value.slice(-4);
    }

    function forecastTx(result) {
      const receipt = result && result.receipt;
      if (receipt && receipt.tx_hash) return receipt.tx_hash;
      const steps = result && result.steps;
      if (steps && steps.length) {
        for (let i = steps.length - 1; i >= 0; i--) {
          const r = steps[i].receipt || {};
          if (r.tx_hash) return r.tx_hash;
          if (r.transactions && r.transactions.length) return r.transactions[r.transactions.length - 1].tx_hash;
        }
      }
      return '';
    }

    function setForecastBusy(busy) {
      [forecastDeployBtn, x402BuyBtn, forecastSetupBtn, forecastSettleBtn, forecastWinner, forecastGame].forEach((el) => {
        if (el) el.disabled = busy;
      });
    }

    updateWinnerOptions();
    if (DN.databridge && DN.databridge.fetchForecastConfig) {
      DN.databridge.fetchForecastConfig()
        .then((payload) => {
          forecastContract = forecastContract || payload.contract || '';
          if (forecastContract) status.textContent = 'Forecast ' + shortHash(forecastContract);
        })
        .catch(() => {});
    }
    if (DN.databridge && DN.databridge.fetchForecastGames && forecastGame) {
      DN.databridge.fetchForecastGames()
        .then((payload) => {
          const games = payload.games || [];
          const preferred = games.find((game) => /Brazil vs Morocco/i.test(game.name || '')) || games[0];
          if (!preferred) return;
          forecastGame.innerHTML = games.slice(0, 104).map((game) =>
            '<option value="' + game.market_key + '">' + game.name + '</option>'
          ).join('');
          selectedGame = preferred;
          forecastGame.value = preferred.market_key;
          updateWinnerOptions();
        })
        .catch(() => {});
      forecastGame.addEventListener('change', () => {
        const optionText = forecastGame.options[forecastGame.selectedIndex] ? forecastGame.options[forecastGame.selectedIndex].textContent : 'Selected game';
        selectedGame = {
          market_key: forecastGame.value,
          market_type: forecastGame.value.includes('group') ? 'three_way' : selectedGame.market_type,
          home_team: optionText.split(' vs ')[0] || selectedGame.home_team,
          away_team: optionText.split(' vs ')[1] || selectedGame.away_team,
          name: optionText,
        };
        const cached = (DN.databridge.forecastGames || []).find((game) => game.market_key === forecastGame.value);
        if (cached) selectedGame = cached;
        forecastMarketKey = '';
        forecastStakes = [];
        updateWinnerOptions();
        status.textContent = selectedGame.name;
      });
    }

    // Auto-fetch ants from the Railway API every 15s, then bind each
    // record (wallet/ENS/etc.) to a scene ant so clicking a worker shows
    // its on-chain identity. Errors are kept quiet so the status bar
    // doesn't flicker between transient network issues.
    function pollAgents(showErrors) {
      if (!DN.databridge || !DN.databridge.fetchAgents) return Promise.resolve(null);
      return DN.databridge.fetchAgents()
        .then((payload) => {
          const records = payload.agents || [];
          status.textContent = records.length + ' ants · live';
          if (DN.ants && DN.ants.bindAgentRecords) DN.ants.bindAgentRecords(records);
          return records;
        })
        .catch((err) => {
          if (showErrors) {
            status.textContent = 'Ant fetch error';
            H.pushThought('Could not fetch ants: ' + (err.message || err), 'Backend', '#D96E54');
          }
          return null;
        });
    }
    pollAgents(false);
    setInterval(() => pollAgents(false), 15000);

    // Communication events: poll faster (5s) so debate arcs feel live.
    // Hands events to commsViz; logTerm rows are emitted by commsViz so
    // we don't double-log. Errors are surfaced to the log once each.
    let _commsLastErr = null;
    let _commsPollCount = 0;
    function pollComms() {
      _commsPollCount++;
      if (!DN.databridge || !DN.databridge.fetchCommunications) {
        if (DN.logTerm) DN.logTerm.push('SYSTEM', 'databridge.fetchCommunications not loaded — stale cache? Hard refresh (Cmd+Shift+R).');
        return;
      }
      // First poll only: announce it so the user knows the loop is alive
      if (_commsPollCount === 1 && DN.logTerm) {
        DN.logTerm.push('SYSTEM', 'Starting communications poll → /runs then /runs/{id}/events…');
      }
      DN.databridge.fetchCommunications()
        .then((payload) => {
          const events = payload.events || [];
          const rid = payload.run_id;
          // Always emit a per-poll summary so the user can see polling is alive.
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Poll #' + _commsPollCount + ': run=' + (rid || 'none') + ' events=' + events.length);
          if (DN.commsViz && DN.commsViz.ingest) DN.commsViz.ingest(events);
          _commsLastErr = null;
          if (DN.logTerm && rid && pollComms._loggedRun !== rid) {
            pollComms._loggedRun = rid;
          }
        })
        .catch((err) => {
          const msg = (err && err.message) || String(err);
          if (msg !== _commsLastErr && DN.logTerm) {
            _commsLastErr = msg;
            DN.logTerm.push('SYSTEM', 'Comms poll error: ' + msg);
          }
        });
    }
    pollComms();
    setInterval(pollComms, 5000);
    H._pollComms = pollComms; // exposed so Run LLM can kick a fresh poll

    antsBtn.addEventListener('click', () => {
      antsBtn.disabled = true;
      status.textContent = 'Getting ants...';
      pollAgents(true)
        .then((records) => {
          if (records) H.pushThought('Frontend fetched ' + records.length + ' ants from the Railway API.', 'Backend', '#3FA89F');
        })
        .finally(() => { antsBtn.disabled = false; });
    });
    kgBtn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.fetchWorldCupKg) return;
      kgBtn.disabled = true;
      status.textContent = 'Getting KG...';
      DN.databridge.fetchWorldCupKg()
        .then((payload) => {
          const entities = payload.entity_count != null ? payload.entity_count : (payload.entities || []).length;
          const links = payload.relationship_count != null ? payload.relationship_count : (payload.relationships || []).length;
          if (DN.kgview) DN.kgview.showGraph(payload, 'World Cup KG');
          status.textContent = entities + ' KG entities · ' + links + ' links';
          H.pushThought('Frontend loaded the World Cup KG from Railway: ' + entities + ' entities, ' + links + ' links.', 'Backend', '#3FA89F');
        })
        .catch((err) => {
          status.textContent = 'KG fetch error';
          H.pushThought('Could not fetch KG: ' + (err.message || err), 'Backend', '#D96E54');
        })
        .finally(() => { kgBtn.disabled = false; });
    });
    scoutBtn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.startScoutingRun) return;
      scoutBtn.disabled = true;
      status.textContent = 'Scouting...';
      H.pushThought('Frontend started a public-data KG scouting run on Railway.', 'Backend', '#3FA89F');
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Scouting run kicked off.');
      DN.databridge.startScoutingRun()
        .then((result) => {
          const manifest = result.manifest || {};
          const kg = result.kg || {};
          const entities = manifest.entity_count || kg.entity_count || 0;
          const links = manifest.relationship_count || kg.relationship_count || 0;
          const ready = manifest.validation && manifest.validation.kg_load_ready === false ? 'needs review' : 'ready';
          status.textContent = 'Scouting ' + ready + ' · ' + entities + ' entities';
          H.pushThought('Scouting finished: ' + entities + ' KG entities and ' + links + ' relationships.', 'Backend', '#3FA89F');
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Scouting finished. Re-polling communications.');
          const newId = (DN.databridge && DN.databridge.runId) || null;
          if (DN.databridge && DN.databridge.resetCommsRun) DN.databridge.resetCommsRun(newId);
          if (DN.commsViz && DN.commsViz.reset) DN.commsViz.reset();
          if (H._pollComms) H._pollComms();
        })
        .catch((err) => {
          status.textContent = 'Scouting error';
          H.pushThought('Scouting failed: ' + (err.message || err), 'Backend', '#D96E54');
        })
        .finally(() => { scoutBtn.disabled = false; });
    });
    btn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.startDemoRun) return;
      btn.disabled = true;
      status.textContent = 'Starting run...';
      H.pushThought('Frontend requested a new LLM-powered Railway colony run.', 'Backend', '#3FA89F');
      if (DN.logTerm) DN.logTerm.push('SYSTEM', 'LLM debate run kicked off — debate_claim and social_action events incoming.');
      DN.databridge.startDemoRun()
        .then((result) => {
          const agents = DN.databridge.getAgents ? DN.databridge.getAgents().length : 0;
          const rooms = DN.databridge.getRooms ? DN.databridge.getRooms().length : 0;
          status.textContent = 'Loaded ' + agents + ' agents · ' + rooms + ' rooms';
          H.pushThought('Backend run completed and the colony view loaded its events.', 'Backend', '#3FA89F');
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Run complete: ' + agents + ' agents · ' + rooms + ' rooms. Visualising debate.');
          // Critical: the comms poller caches the run-id for 30s, so
          // without a reset it will keep returning the OLD run's events
          // for a while after Run LLM completes. Force the cache to
          // re-pick the freshest run on the next poll and wipe the
          // commsViz dedup so every event from the new run dispatches.
          const newId = (DN.databridge && DN.databridge.runId) || null;
          if (DN.databridge && DN.databridge.resetCommsRun) DN.databridge.resetCommsRun(newId);
          if (DN.commsViz && DN.commsViz.reset) DN.commsViz.reset();
          if (H._pollComms) H._pollComms();
          if (pollAgents) pollAgents(false);
        })
        .catch((err) => {
          status.textContent = 'Backend error';
          H.pushThought('Backend run failed: ' + (err.message || err), 'Backend', '#D96E54');
          if (DN.logTerm) DN.logTerm.push('SYSTEM', 'Run failed: ' + (err.message || err));
        })
        .finally(() => { btn.disabled = false; });
    });

    forecastDeployBtn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.deployForecastContract) return;
      setForecastBusy(true);
      status.textContent = 'Deploying contract...';
      H.pushThought('Deploying the Arc forecast market contract.', 'Arc', '#E8A23D');
      DN.databridge.deployForecastContract()
        .then((result) => {
          const receipt = result.receipt || {};
          forecastContract = result.contract || receipt.contract_address || forecastContract;
          status.textContent = 'Contract ' + shortHash(forecastContract);
          H.pushThought('Forecast contract deployed: ' + shortHash(forecastContract) + ' · tx ' + shortHash(receipt.tx_hash || ''), 'Arc', '#3FA89F');
        })
        .catch((err) => {
          status.textContent = 'Deploy error';
          H.pushThought('Deploy failed: ' + (err.message || err), 'Arc', '#D96E54');
        })
        .finally(() => setForecastBusy(false));
    });

    x402BuyBtn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.runX402DemoPayment) return;
      setForecastBusy(true);
      status.textContent = 'Buying KG...';
      H.pushThought('ant-0001 is buying a private KG signal for ' + selectedGame.name + ' from ant-0002 through x402.', 'x402', '#E8A23D');
      DN.databridge.runX402DemoPayment({
        topic: selectedGame.name,
        resource_id: 'kg:' + selectedGame.market_key + ':private-scout-signal',
      })
        .then((result) => {
          const tx = result.gateway_transfer_id || '';
          const amount = result.amount_usdc || '0';
          status.textContent = 'x402 paid ' + amount + ' USDC';
          H.pushThought('x402 payment complete: ' + result.money_flow + ' for ' + result.resource_id + (tx ? ' · transfer ' + shortHash(tx) : '') + '.', 'x402', '#3FA89F');
        })
        .catch((err) => {
          status.textContent = 'x402 error';
          H.pushThought('x402 payment failed: ' + (err.message || err), 'x402', '#D96E54');
        })
        .finally(() => setForecastBusy(false));
    });

    forecastSetupBtn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.setupForecastDemo) return;
      forecastMarketKey = selectedGame.market_key + ':demo-' + Date.now();
      setForecastBusy(true);
      status.textContent = 'Staking demo...';
      H.pushThought('Creating a fresh Arc market for ' + selectedGame.name + ' and staking ant votes.', 'Arc', '#E8A23D');
      DN.databridge.setupForecastDemo({
        contract: forecastContract || undefined,
        market_key: forecastMarketKey,
        market_type: selectedGame.market_type || 'three_way',
        metadata_uri: selectedGame.market_key,
        run_id: DN.databridge.runId || undefined,
      })
        .then((result) => {
          forecastContract = result.contract || forecastContract;
          forecastStakes = result.stakes || [];
          const totals = result.totals || {};
          status.textContent = 'Staked ' + (totals.total_usdc || '0') + ' USDC';
          H.pushThought('Demo market funded on Arc from ' + (result.stake_source || 'fallback') + ': ' + (totals.home_usdc || '0') + ' home · ' + (totals.draw_usdc || '0') + ' draw · ' + (totals.away_usdc || '0') + ' away.', 'Arc', '#3FA89F');
        })
        .catch((err) => {
          status.textContent = 'Stake error';
          H.pushThought('Stake demo failed: ' + (err.message || err), 'Arc', '#D96E54');
        })
        .finally(() => setForecastBusy(false));
    });

    forecastSettleBtn.addEventListener('click', () => {
      if (!DN.databridge || !DN.databridge.settleForecastDemo) return;
      if (!forecastMarketKey) {
        status.textContent = 'Stake demo first';
        H.pushThought('Create and stake a demo market before settlement.', 'Arc', '#D96E54');
        return;
      }
      const winner = forecastWinner ? forecastWinner.value : selectedGame.home_team;
      setForecastBusy(true);
      status.textContent = 'Settling ' + winner + '...';
      H.pushThought('Settling the Arc market with winner: ' + winner + '.', 'Arc', '#E8A23D');
      DN.databridge.settleForecastDemo({
        contract: forecastContract || undefined,
        market_key: forecastMarketKey,
        winner,
        home_team: selectedGame.home_team,
        away_team: selectedGame.away_team,
        winning_agents: forecastStakes
          .filter((stake) => stake.outcome === (winner === selectedGame.home_team ? 'home' : winner === selectedGame.away_team ? 'away' : 'draw'))
          .map((stake) => stake.agent),
      })
        .then((result) => {
          const tx = forecastTx(result);
          const claimed = (result.claimed_agents || []).join(', ') || 'none';
          status.textContent = 'Settled · ' + result.result;
          H.pushThought('Settlement complete: winners claimed by ' + claimed + (tx ? ' · tx ' + shortHash(tx) : '') + '.', 'Arc', '#3FA89F');
        })
        .catch((err) => {
          status.textContent = 'Settle error';
          H.pushThought('Settle failed: ' + (err.message || err), 'Arc', '#D96E54');
        })
        .finally(() => setForecastBusy(false));
    });
  }

  H.setActiveBiome = function (i) {
    $('regions').querySelectorAll('.reg').forEach(el => el.classList.toggle('active', parseInt(el.dataset.i) === i));
  };

  H.setActiveSlot = function (idx) {
    $('hotbar').querySelectorAll('.slot').forEach(el => el.classList.toggle('active', parseInt(el.dataset.idx) === idx));
  };

  // ---------- top stats ----------
  H.setStats = function (s) {
    $('stats').innerHTML = [
      ['Colonies', s.colonies],
      ['Active Ants', s.ants.toLocaleString()],
      ['Resources', s.resources],
      ['USDC Staked', '<b>$' + Math.round(s.staked).toLocaleString() + '</b>'],
      ['Forecast Acc', s.accuracy + '%'],
      ['Round', '#' + s.round]
    ].map(r => `<div class="stat"><div class="sk">${r[0]}</div><div class="sv">${r[1]}</div></div>`).join('');
  };

  // ---------- inspector ----------
  H.clearInspector = function () {
    H._open = null;
    $('inspector').innerHTML = '';
    $('inspector').classList.remove('has-content');
  };

  H.showColony = function (col) {
    $('inspector').classList.add('has-content');
    H._open = { type: 'colony', col };
    const c = hex(col.accent);
    const roster = DN.ants.heroes.filter(a => a.col === col);
    $('inspector').innerHTML =
      `<div class="insp-head"><div class="insp-icon" style="background:${c}22;box-shadow:inset 0 0 0 1px ${c}66">
        <div style="width:14px;height:14px;border-radius:50%;background:${c};box-shadow:0 0 12px ${c}"></div></div>
        <div><div class="insp-kicker">Colony</div><div class="insp-name">${col.name}</div></div></div>
      <div class="metrics">
        <div class="metric"><div class="mk">Population</div><div class="mv" id="m-pop">0</div></div>
        <div class="metric"><div class="mk">Forecast Acc</div><div class="mv" id="m-acc">0<small>%</small></div></div>
        <div class="metric"><div class="mk">USDC Staked</div><div class="mv" id="m-stk">0</div></div>
        <div class="metric"><div class="mk">Reputation</div><div class="mv" id="m-rep">0</div></div>
      </div>
      <div class="vital-bar"><div class="vlabel"><span>Colony health</span><span id="v-health">—</span></div><div class="bar"><i id="b-health" style="background:#5FB84A"></i></div></div>
      <div class="vital-bar" style="margin-top:11px"><div class="vlabel"><span>Food stores</span><span id="v-food">—</span></div><div class="bar"><i id="b-food" style="background:${c}"></i></div></div>
      <div class="section-label">Directive</div>
      <div class="directives">${['forage', 'defend', 'expand'].map(d => `<div class="dir-btn${col.directive === d ? ' active' : ''}" data-dir="${d}">${ICON[d]}${cap(d)}</div>`).join('')}</div>
      <div class="section-label">Field agents · ${roster.length}</div>
      <div class="roster">${roster.map(s => `<div class="roster-row" data-ant="${s.id}"><div class="roster-dot" style="background:${c}"></div><div class="roster-name">${s.name}</div><div class="roster-caste">${s.role}</div></div>`).join('')}</div>
      <button class="btn-primary" id="enter-col"><svg viewBox="0 0 24 24"><path d="M12 3l9 6-9 6-9-6z" opacity=".5"/><path d="M3 13l9 6 9-6"/></svg>Enter Colony</button>`;
    $('inspector').querySelectorAll('.dir-btn').forEach(b => b.addEventListener('click', () => DN.app.setDirective(col, b.dataset.dir)));
    $('inspector').querySelectorAll('.roster-row').forEach(r => r.addEventListener('click', () => {
      const a = DN.ants.heroes.find(x => x.id === r.dataset.ant); if (a) DN.app.selectAnt(a);
    }));
    $('enter-col').addEventListener('click', () => DN.app.enterColony(col));
    H._updateColony(col);
  };

  H._updateColony = function (col) {
    if (!H._open || H._open.type !== 'colony' || H._open.col !== col) return;
    const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
    const setW = (id, v) => { const e = $(id); if (e) e.style.width = v + '%'; };
    set('m-pop', Math.round(col.stats.population));
    set('m-acc', Math.round(col.stats.accuracy)); set('m-rep', Math.round(col.stats.rep));
    const e = $('m-stk'); if (e) e.innerHTML = '<small>$</small>' + (col.stats.staked / 1000).toFixed(1) + '<small>k</small>';
    set('v-health', Math.round(col.stats.health) + '%'); set('v-food', Math.round(col.stats.food) + '%');
    setW('b-health', col.stats.health); setW('b-food', col.stats.food);
  };

  H.showAnt = function (a, following) {
    H._open = { type: 'ant', ant: a };
    $('inspector').classList.add('has-content');
    const c = hex(a.col.accent);
    const rec = a.agentRecord || null;
    const displayName = (rec && (rec.ens_name || rec.name)) || a.name || ('Worker ' + a.id.split('-').slice(-1));
    const wallet = rec && rec.wallet_address;
    const walletShort = wallet ? wallet.slice(0, 6) + '…' + wallet.slice(-4) : null;
    const ens = rec && rec.ens_name;
    const identityRows = (ens || wallet) ? `
      ${ens ? `<div class="vital-bar" style="margin-top:9px"><div class="vlabel"><span>ENS</span><span style="color:${c};font-family:var(--mono)">${ens}</span></div></div>` : ''}
      ${wallet ? `<div class="vital-bar" style="margin-top:9px"><div class="vlabel"><span>Wallet</span><span style="font-family:var(--mono);cursor:pointer" title="${wallet}" data-copy="${wallet}">${walletShort}</span></div></div>` : ''}
    ` : '';
    $('inspector').innerHTML =
      `<div class="insp-head"><div class="insp-icon" style="background:${c}22;box-shadow:inset 0 0 0 1px ${c}66">
        <div style="width:13px;height:13px;border-radius:3px;background:${c};box-shadow:0 0 10px ${c}"></div></div>
        <div><div class="insp-kicker">${a.role}${a.hero ? ' · Gen ' + a.gen : ''}</div><div class="insp-name">${displayName}</div></div></div>
      <div class="metrics">
        <div class="metric"><div class="mk">Forecast Acc</div><div class="mv">${(rec && rec.forecast_accuracy != null) ? Math.round(rec.forecast_accuracy * 100) : (a.accuracy || (52 + (a.inst % 30)))}<small>%</small></div></div>
        <div class="metric"><div class="mk">Bankroll</div><div class="mv"><small>$</small>${rec && rec.bankroll != null ? Math.round(rec.bankroll) : (a.reputation || (30 + (a.inst % 50)))}</div></div>
        <div class="metric"><div class="mk">USDC Staked</div><div class="mv"><small>$</small>${rec && rec.staked != null ? Math.round(rec.staked) : (a.staked || (10 + a.inst % 60) + '.0')}</div></div>
        <div class="metric"><div class="mk">Generation</div><div class="mv">${rec && rec.generation != null ? rec.generation : (a.gen || (1 + a.inst % 8))}</div></div>
      </div>
      <div class="vital-bar"><div class="vlabel"><span>Home colony</span><span style="color:${c}">${a.col.name}</span></div></div>
      ${identityRows}
      <div class="vital-bar" style="margin-top:9px"><div class="vlabel"><span>Current task</span><span id="a-task">—</span></div></div>
      <div class="vital-bar" style="margin-top:9px"><div class="vlabel"><span>Carrying</span><span id="a-cargo">—</span></div></div>
      <div class="section-label">Recent activity</div>
      <div class="insp-empty" style="font-size:12px">${antBlurb(a)}</div>
      <button class="btn-primary" id="follow-ant" style="background:${following ? 'rgba(255,238,205,0.1)' : ''};color:${following ? 'var(--ink)' : ''};border-color:var(--border-strong)">
        <svg viewBox="0 0 24 24" style="fill:${following ? 'var(--ink)' : '#2a1d08'}"><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke="${following ? 'var(--ink)' : '#2a1d08'}" stroke-width="2" fill="none"/></svg>
        ${following ? 'Stop following' : 'Follow agent'}</button>`;
    $('follow-ant').addEventListener('click', () => DN.app.toggleFollow(a));
    // copy-on-click for the truncated wallet
    $('inspector').querySelectorAll('[data-copy]').forEach(el => {
      el.addEventListener('click', () => {
        const v = el.getAttribute('data-copy');
        if (v && navigator.clipboard) {
          navigator.clipboard.writeText(v).then(() => {
            const orig = el.textContent;
            el.textContent = 'copied';
            setTimeout(() => { el.textContent = orig; }, 900);
          }).catch(() => {});
        }
      });
    });
    H._updateAnt(a);
  };

  function antBlurb(a) {
    const lines = {
      Forecaster: 'Submitted a forecast on Round outcome — confidence rising as peers corroborate evidence.',
      Scout: 'Mapping fresh terrain and tagging resource caches for the foraging columns.',
      Debater: 'Challenging a low-evidence claim in the Debate Hall; staking reputation on the rebuttal.',
      Treasurer: 'Rebalancing the colony vault and settling USDC stakes from the last round.',
      Archivist: 'Writing verified outcomes into the Memory Archive for future lineages.'
    };
    return lines[a.role] || 'Foraging along an active pheromone trail and relaying cache positions home.';
  }

  H._updateAnt = function (a) {
    if (!H._open || H._open.type !== 'ant' || H._open.ant !== a) return;
    const t = $('a-task'); if (t) t.textContent = a.state === 'out' ? 'Outbound · scouting' : 'Returning to nest';
    const cg = $('a-cargo'); if (cg) cg.textContent = a.cargo ? 'Data crystal' : 'Empty';
  };

  H.showRoom = function (room, col) {
    H._open = { type: 'room' };
    $('inspector').classList.add('has-content');
    const c = hex(col.accent);
    const blurbs = {
      queen: 'The queen seeds new forecasting agents. Genetics weight toward the round\'s best-performing lineages.',
      nursery: 'Young agents incubate here, inheriting priors from their lineage before their first forecast.',
      forecast: 'Agents analyse live events and submit probability estimates. Glow intensity tracks confidence.',
      debate: 'Agents contest each other\'s claims, exchanging evidence. Reputation is won and lost here.',
      storage: 'Verified data crystals and forage are stockpiled and rationed to active agents.',
      economy: 'The colony treasury. Resource flows and inter-colony trades are settled here.',
      memory: 'Outcomes of resolved rounds are archived as immutable memory for future agents.',
      dorm: 'Agents rest and recover energy between forecasting rounds.',
      knowledge: 'Cross-colony knowledge exchange — evidence and models traded between civilizations.',
      lineage: 'The family tree of every agent. High performers found long, decorated lineages.',
      stake: 'Agents stake USDC on their forecasts. Accurate calls compound; poor ones are slashed.'
    };
    // live activity rows: count of ants currently in this room + last event
    let active = 0;
    if (DN.underground && DN.underground.agents) {
      for (const a of DN.underground.agents) {
        if (a.roomId === room.id) active++;
      }
      if (room.id === 'queen') active += 1; // queen herself
      if (room.id === 'nursery' && DN.underground.larvae) active += DN.underground.larvae.length;
    }
    const activity = ({
      queen: 'Seeding new lineage',
      nursery: 'Incubating larvae',
      forecast: 'Submitting probability estimates',
      debate: 'Exchanging evidence',
      storage: 'Rationing data crystals',
      economy: 'Settling treasury flows',
      memory: 'Archiving outcomes',
      dorm: 'Resting between rounds',
      knowledge: 'Trading cross-colony models',
      lineage: 'Promoting top performers',
      stake: 'Posting USDC stakes'
    })[room.prop] || 'Active';
    const events = ({
      queen: 'Brood batch #' + (1200 + Math.floor(Math.random() * 99)) + ' seeded',
      nursery: 'Larva #' + (800 + Math.floor(Math.random() * 199)) + ' graduated',
      forecast: 'Edge +' + (Math.random() * 4 + 1).toFixed(2) + '% on round',
      debate: 'Reputation +' + Math.floor(Math.random() * 8 + 1),
      storage: '+' + Math.floor(Math.random() * 30 + 5) + ' crystals received',
      economy: '+' + (Math.random() * 1200 + 200).toFixed(0) + ' USDC settled',
      memory: 'Round #' + Math.floor(Math.random() * 99 + 1) + ' archived',
      dorm: '14 agents resting',
      knowledge: 'Trade w/ Amber Canyon',
      lineage: 'New branch · gen ' + Math.floor(Math.random() * 8 + 4),
      stake: 'Stake ' + (Math.random() * 60 + 10).toFixed(1) + ' USDC'
    })[room.prop] || '—';
    $('inspector').innerHTML =
      `<div class="insp-head"><div class="insp-icon" style="background:${c}22;box-shadow:inset 0 0 0 1px ${c}66">
        <div style="width:13px;height:13px;border-radius:3px;background:${c}"></div></div>
        <div><div class="insp-kicker">${col.name} · Chamber</div><div class="insp-name">${room.name}</div></div></div>
      <div class="insp-empty" style="margin-top:14px">${blurbs[room.prop] || ''}</div>
      <div class="insp-rows" style="margin-top:14px">
        <div class="tt-row"><span>Active ants</span><span>${active}</span></div>
        <div class="tt-row"><span>Activity</span><span>${activity}</span></div>
        <div class="tt-row"><span>Latest event</span><span style="color:${c}">${events}</span></div>
      </div>`;
  };

  // ---------- thoughts ----------
  let curLine = null;
  H.pushThought = function (text, tag, color) {
    const stream = $('think-stream'); if (!stream) return;
    const line = document.createElement('div');
    line.className = 'think-line';
    line.innerHTML = `<span class="tag" style="background:${color}26;color:${color}">${tag}</span><span class="ttext">${text}</span>`;
    stream.appendChild(line);
    const prev = curLine; curLine = line;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      line.classList.add('show');
      if (prev) { prev.classList.remove('show'); setTimeout(() => prev.remove(), 600); }
    }));
  };

  // ---------- transport ----------
  H.setTransport = function (t) {
    $('play-icon').innerHTML = t.playing
      ? '<svg viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>'
      : '<svg viewBox="0 0 24 24"><path d="M7 5l12 7-12 7z"/></svg>';
    $('tl-gen').textContent = 'Generation ' + t.gen;
    $('tl-clock').textContent = t.clock;
    $('tl-fill').style.width = (t.progress * 100) + '%';
    $('tl-knob').style.left = (t.progress * 100) + '%';
    document.querySelectorAll('#speeds .speed').forEach(s => s.classList.toggle('active', parseFloat(s.dataset.s) === t.speed));
  };

  // ---------- modes & banners ----------
  H.setCameraMode = function (m) {
    document.querySelectorAll('#cammode .cm').forEach(el => el.classList.toggle('active', el.dataset.mode === m));
  };
  H.setExploreLocked = function () {};
  H.showEnterBanner = function (col) {
    const b = $('enterbanner');
    b.innerHTML = `<span class="ek">ENTER</span> Descend into ${col.name}`;
    b.classList.add('show');
    b.onclick = () => DN.app.enterColony(col);
  };
  H.hideEnterBanner = function () { $('enterbanner').classList.remove('show'); };
  H.setUnderground = function (on) {
    document.body.classList.toggle('underground', on);
    $('exitbtn').classList.toggle('show', on);
    // Hide the surface HUD while underground — the game UI overlay takes over.
    ['stats', 'hotbar', 'tools', 'transport', 'thoughts', 'cammode', 'brand', 'enterbanner', 'regions', 'inspector', 'backend'].forEach(id => {
      const el = $(id); if (!el) return;
      el.style.display = on ? 'none' : '';
    });
    if (on) {
      H._open = null;
      H._ensureUgGameUi();
      H._ugRoot.style.display = 'block';
      // recolor the game UI accents to the active colony
      const col = (DN.underground && DN.underground.col) || null;
      if (col) H._applyUgAccent(col.accent);
    } else {
      H.clearInspector();
      if (H._ugRoot) H._ugRoot.style.display = 'none';
    }
  };

  // ---------------------------------------------------------------------
  // Underground game UI (Phase 3) — full dashboard overlay matching the
  // amber/gold "Ant Colony" mockup. Built once via DOM injection and
  // toggled visible on enter/exit. Numbers update at ~4Hz from a
  // lightweight tick loop so the panels feel alive.
  // ---------------------------------------------------------------------
  H._ensureUgGameUi = function () {
    if (H._ugRoot) return;
    // ---- inject css once ----
    const css = `
      #ug-game * { box-sizing: border-box; }
      #ug-game {
        position: fixed; inset: 0; z-index: 4; pointer-events: none;
        font-family: var(--font), "Inter", system-ui, sans-serif;
        color: #F1D8A8;
      }
      #ug-game .ug-panel {
        background: linear-gradient(180deg, rgba(34,20,10,0.92), rgba(22,12,6,0.95));
        border: 1px solid rgba(196,142,68,0.35);
        border-radius: 12px;
        box-shadow: 0 6px 22px -10px rgba(0,0,0,0.7), inset 0 1px 0 rgba(255,200,130,0.06);
        pointer-events: auto;
        backdrop-filter: blur(8px) saturate(1.05);
        -webkit-backdrop-filter: blur(8px) saturate(1.05);
      }
      #ug-game .ug-section { padding: 14px 16px; }
      #ug-game .ug-section + .ug-section { border-top: 1px solid rgba(196,142,68,0.18); }
      #ug-game .ug-kicker {
        font-size: 10px; letter-spacing: 2.5px; text-transform: uppercase;
        color: rgba(241,216,168,0.55); font-weight: 600; margin-bottom: 12px;
      }

      /* ---- TOP BAR ---- */
      #ug-topbar { position: fixed; top: 14px; left: 14px; right: 14px; display: flex; gap: 10px; align-items: stretch; pointer-events: none; }
      #ug-brand { display: flex; align-items: center; gap: 12px; padding: 12px 16px; min-width: 220px; }
      #ug-brand .hex {
        width: 36px; height: 36px; background: linear-gradient(140deg,#3a2210,#1c0e06);
        border: 1px solid rgba(196,142,68,0.6); border-radius: 9px;
        display: flex; align-items: center; justify-content: center;
        box-shadow: inset 0 1px 0 rgba(255,200,130,0.18);
      }
      #ug-brand .hex svg { width: 22px; height: 22px; fill: #E8B85A; }
      #ug-brand .brand-text h1 {
        font-family: "Press Start 2P", var(--display); font-size: 14px;
        letter-spacing: 2px; color: #F4DCA0; margin: 0; line-height: 1.1;
      }
      #ug-brand .brand-text p { font-size: 10px; color: rgba(241,216,168,0.45); margin: 4px 0 0; letter-spacing: 1px; text-transform: uppercase; }

      #ug-resources { display: flex; gap: 10px; flex: 1; }
      .ug-res { display: flex; align-items: center; gap: 12px; padding: 10px 16px; flex: 1; min-width: 0; }
      .ug-res .ico { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; flex-shrink: 0;
        background: rgba(50,30,14,0.7); border: 1px solid rgba(196,142,68,0.25); }
      .ug-res .ico svg { width: 18px; height: 18px; }
      .ug-res .label { font-size: 10px; color: rgba(241,216,168,0.5); letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 2px; }
      .ug-res .val { font-size: 16px; font-weight: 700; color: #F4DCA0; font-family: var(--mono), ui-monospace, monospace; }
      .ug-res .rate { font-size: 11px; color: #6DD68A; margin-left: 6px; font-family: var(--mono); }

      .ug-strength { display: flex; align-items: center; gap: 12px; padding: 10px 18px; }
      .ug-strength .ico { background: linear-gradient(135deg,#4a2a14,#2a1408); border: 1px solid rgba(196,142,68,0.45); border-radius: 8px; width: 32px; height: 32px; display: grid; place-items: center; }
      .ug-strength .ico svg { width: 18px; height: 18px; fill: #E8B85A; }
      .ug-strength .label { font-size: 10px; color: rgba(241,216,168,0.55); letter-spacing: 1.5px; text-transform: uppercase; }
      .ug-strength .val { font-size: 18px; font-weight: 700; color: #F4DCA0; font-family: var(--mono); }

      .ug-iconbtn { width: 44px; height: 44px; display: grid; place-items: center; padding: 0; cursor: pointer; }
      .ug-iconbtn svg { width: 18px; height: 18px; fill: #E8B85A; opacity: 0.85; }
      .ug-iconbtn:hover svg { opacity: 1; }

      /* ---- LEFT SIDEBAR ---- */
      #ug-leftbar { position: fixed; left: 14px; top: 82px; bottom: 64px; width: 250px; display: flex; flex-direction: column; gap: 12px; pointer-events: none; }
      #ug-overview, #ug-status { pointer-events: auto; }
      #ug-nav { display: flex; flex-direction: column; gap: 4px; padding: 12px 10px; }
      .ug-nav-row {
        display: flex; align-items: center; gap: 12px;
        padding: 9px 12px; border-radius: 9px; cursor: pointer;
        color: rgba(241,216,168,0.7); font-size: 13px; font-weight: 500;
        transition: background 120ms ease, color 120ms ease;
      }
      .ug-nav-row svg { width: 16px; height: 16px; fill: currentColor; opacity: 0.9; }
      .ug-nav-row:hover { background: rgba(196,142,68,0.08); color: #F4DCA0; }
      .ug-nav-row.active {
        background: linear-gradient(90deg, rgba(232,184,90,0.18), rgba(232,184,90,0.04));
        color: #FFD988; border: 1px solid rgba(232,184,90,0.35);
      }

      .ug-stat-row { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; font-size: 12px; }
      .ug-stat-row .dot { width: 8px; height: 8px; border-radius: 999px; display: inline-block; margin-right: 8px; }
      .ug-stat-row .name { color: rgba(241,216,168,0.78); display: flex; align-items: center; }
      .ug-stat-row .num { color: #F4DCA0; font-family: var(--mono); font-weight: 600; }

      .ug-buff { display: flex; align-items: center; gap: 10px; padding: 8px 0; }
      .ug-buff .b-ico { width: 28px; height: 28px; border-radius: 7px; display: grid; place-items: center; flex-shrink: 0;
        background: rgba(50,30,14,0.7); border: 1px solid rgba(196,142,68,0.3); }
      .ug-buff .b-ico svg { width: 14px; height: 14px; }
      .ug-buff .b-name { font-size: 12px; color: #F4DCA0; font-weight: 600; }
      .ug-buff .b-sub { font-size: 10px; color: rgba(241,216,168,0.5); margin-top: 2px; letter-spacing: 0.5px; }
      .ug-buff .b-time { margin-left: auto; font-size: 10px; color: rgba(241,216,168,0.65); font-family: var(--mono); }

      #ug-log-btn {
        pointer-events: auto; display: flex; align-items: center; justify-content: space-between;
        gap: 12px; padding: 12px 16px; cursor: pointer; font-size: 11px;
        letter-spacing: 2px; text-transform: uppercase; color: #F4DCA0;
      }
      #ug-log-btn svg { width: 14px; height: 14px; fill: currentColor; opacity: 0.7; }
      #ug-log-btn:hover svg { opacity: 1; }

      #ug-zoom { pointer-events: auto; display: flex; align-items: center; gap: 4px; padding: 6px 8px; align-self: flex-start; }
      #ug-zoom button { width: 30px; height: 30px; display: grid; place-items: center; cursor: pointer; color: #F4DCA0; }
      #ug-zoom .pct { padding: 0 10px; font-family: var(--mono); font-size: 12px; color: #F4DCA0; }

      /* ---- RIGHT SIDEBAR ---- */
      #ug-rightbar { position: fixed; right: 14px; top: 82px; bottom: 14px; width: 260px; display: flex; flex-direction: column; gap: 12px; pointer-events: none; }
      #ug-blurb, #ug-objective, #ug-events, #ug-actions { pointer-events: auto; }
      #ug-blurb h3 { font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase; color: rgba(241,216,168,0.55); margin: 0 0 10px; font-weight: 600; }
      #ug-blurb p { font-size: 12px; line-height: 1.6; color: rgba(241,216,168,0.78); margin: 0 0 8px; }

      .ug-obj-card { display: flex; align-items: flex-start; gap: 12px; }
      .ug-obj-card .ic { width: 36px; height: 36px; border-radius: 8px; display: grid; place-items: center; flex-shrink: 0;
        background: linear-gradient(135deg, rgba(160,90,200,0.32), rgba(80,40,110,0.42));
        border: 1px solid rgba(180,110,220,0.4); }
      .ug-obj-card .ic svg { width: 18px; height: 18px; fill: #E6C8FA; }
      .ug-obj-card .title { font-size: 13px; color: #F4DCA0; font-weight: 600; margin-bottom: 3px; }
      .ug-obj-card .sub { font-size: 11px; color: rgba(241,216,168,0.6); line-height: 1.45; }
      .ug-progress { margin-top: 12px; position: relative; height: 8px; background: rgba(50,30,14,0.7); border-radius: 999px; overflow: hidden; }
      .ug-progress .fill { position: absolute; inset: 0; width: 67%;
        background: linear-gradient(90deg,#E8B85A,#FFD988);
        box-shadow: 0 0 10px rgba(232,184,90,0.4); border-radius: 999px;
      }
      .ug-progress .pct { position: absolute; right: 6px; top: -2px;
        font-size: 9px; font-family: var(--mono); color: #2A1A08;
        background: #FFD988; padding: 1px 6px; border-radius: 999px;
        line-height: 12px; transform: translateY(-3px);
      }

      .ug-event { display: flex; align-items: center; gap: 10px; padding: 7px 0; font-size: 12px; }
      .ug-event .ic { width: 22px; height: 22px; border-radius: 6px; display: grid; place-items: center; flex-shrink: 0;
        background: rgba(50,30,14,0.7); border: 1px solid rgba(196,142,68,0.3); }
      .ug-event .ic svg { width: 12px; height: 12px; }
      .ug-event .name { flex: 1; color: rgba(241,216,168,0.85); }
      .ug-event .when { font-family: var(--mono); font-size: 10px; color: rgba(241,216,168,0.55); }

      #ug-viewall { display: block; margin-top: 12px; width: 100%; padding: 9px;
        background: rgba(196,142,68,0.10); border: 1px solid rgba(196,142,68,0.35);
        border-radius: 8px; color: #FFD988; text-align: center; cursor: pointer;
        font-size: 10px; letter-spacing: 2px; text-transform: uppercase; font-weight: 600;
      }
      #ug-viewall:hover { background: rgba(196,142,68,0.18); }

      .ug-action { display: flex; align-items: center; gap: 12px; width: 100%;
        padding: 10px 12px; margin-top: 8px;
        background: rgba(50,30,14,0.5); border: 1px solid rgba(196,142,68,0.25);
        border-radius: 9px; cursor: pointer; color: #F4DCA0; font-size: 12px; text-align: left;
        font-family: inherit;
      }
      .ug-action:first-of-type { margin-top: 0; }
      .ug-action:hover { background: rgba(196,142,68,0.12); border-color: rgba(196,142,68,0.45); }
      .ug-action .ic { width: 26px; height: 26px; border-radius: 6px; display: grid; place-items: center; flex-shrink: 0;
        background: rgba(80,46,18,0.85); }
      .ug-action .ic svg { width: 14px; height: 14px; fill: #E8B85A; }

      /* ---- LEGEND ---- */
      #ug-legend { position: fixed; bottom: 14px; left: 280px; right: 290px;
        display: flex; justify-content: center; gap: 28px; pointer-events: none; padding: 10px 16px; }
      .ug-legend-item { display: flex; align-items: center; gap: 8px; font-size: 11px; letter-spacing: 1px;
        color: rgba(241,216,168,0.7); text-transform: uppercase; pointer-events: auto;
      }
      .ug-legend-item .swatch { width: 9px; height: 9px; border-radius: 999px; }

      /* ---- DEBUG TOGGLE (bottom-left, repositioned) ---- */
      #ug-debug-btn { pointer-events: auto; padding: 6px 12px; cursor: pointer;
        font-family: var(--mono); font-size: 10px; letter-spacing: 1.5px;
        text-transform: uppercase; color: rgba(241,216,168,0.7);
      }
      #ug-debug-btn.on { color: #66E0FF; }
    `;
    const styleEl = document.createElement('style');
    styleEl.id = 'ug-game-css';
    styleEl.textContent = css;
    document.head.appendChild(styleEl);

    // ---- icon library (inline SVG) ----
    const svgs = {
      hex: '<svg viewBox="0 0 24 24"><path d="M12 2L4 7v10l8 5 8-5V7l-8-5zm-6 6.5l6-3.7 6 3.7v7l-6 3.7-6-3.7v-7z"/></svg>',
      leaf: '<svg viewBox="0 0 24 24"><path fill="#6DD68A" d="M17 5C9 5 5 9 5 17c0 2 .3 3 .3 3s4-1 7-4c2.8-2.7 5-7 5-9-1 .5-3 2-4 4 .5-2 2-4 4-5-1 .2-4 1.5-5 3 .5-1.5 1-2.5 2-3-1 0-4 1-6 4 0-1.8 0-3 1-5z"/></svg>',
      rock: '<svg viewBox="0 0 24 24"><path fill="#B5A892" d="M6 16l2-7 5-3 5 2 3 5-3 5-7 1-5-3z"/></svg>',
      drop: '<svg viewBox="0 0 24 24"><path fill="#E8B85A" d="M12 3c-1 2-6 7-6 11a6 6 0 0 0 12 0c0-4-5-9-6-11z"/></svg>',
      shield: '<svg viewBox="0 0 24 24"><path d="M12 2L4 5v7c0 5 4 9 8 10 4-1 8-5 8-10V5l-8-3z"/></svg>',
      bell: '<svg viewBox="0 0 24 24"><path d="M12 22a2 2 0 0 0 2-2h-4a2 2 0 0 0 2 2zm6-6V11a6 6 0 0 0-5-5.9V4a1 1 0 0 0-2 0v1.1A6 6 0 0 0 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>',
      book: '<svg viewBox="0 0 24 24"><path d="M4 4h6a3 3 0 0 1 3 3v13a2 2 0 0 0-2-2H4V4zm16 0h-6a3 3 0 0 0-3 3v13a2 2 0 0 1 2-2h7V4z"/></svg>',
      gear: '<svg viewBox="0 0 24 24"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm9 4a9 9 0 0 0-.2-1.8l2-1.6-2-3.4-2.4.8a8.9 8.9 0 0 0-3.1-1.8L15 2h-4l-.4 2.2a8.9 8.9 0 0 0-3 1.8L5.2 5.2 3.2 8.6l2 1.6a9 9 0 0 0 0 3.6l-2 1.6 2 3.4 2.4-.8a8.9 8.9 0 0 0 3 1.8L11 22h4l.4-2.2a8.9 8.9 0 0 0 3.1-1.8l2.3.8 2-3.4-2-1.6a9 9 0 0 0 .2-1.8z"/></svg>',
      map: '<svg viewBox="0 0 24 24"><path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zm0 2.2L13.8 8v9.8L9 16v-9.8zM5 7.4l2 .6v9.8l-2 .6V7.4zm12 0v9.8l-2 .6V8l2-.6z"/></svg>',
      worker: '<svg viewBox="0 0 24 24"><path d="M12 5a3 3 0 1 1 0 6 3 3 0 0 1 0-6zM4 19v-1a6 6 0 0 1 16 0v1H4z"/></svg>',
      upgrade: '<svg viewBox="0 0 24 24"><path d="M12 3l8 8h-4v10h-8V11H4z"/></svg>',
      flask: '<svg viewBox="0 0 24 24"><path d="M9 3h6v3l5 11a3 3 0 0 1-3 4H7a3 3 0 0 1-3-4l5-11V3z"/></svg>',
      quest: '<svg viewBox="0 0 24 24"><path d="M6 2h10l4 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zm2 7h8v2H8V9zm0 4h8v2H8v-2z"/></svg>',
      chart: '<svg viewBox="0 0 24 24"><path d="M4 20h16v2H2V2h2v18zm4-3h2V9H8v8zm4 0h2V5h-2v12zm4 0h2v-6h-2v6z"/></svg>',
      log: '<svg viewBox="0 0 24 24"><path d="M5 5h14v2H5V5zm0 4h14v2H5V9zm0 4h14v2H5v-2zm0 4h8v2H5v-2z"/></svg>',
      chev: '<svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>',
      minus: '<svg viewBox="0 0 24 24"><path d="M5 12h14" stroke="currentColor" stroke-width="2.4" fill="none"/></svg>',
      plus: '<svg viewBox="0 0 24 24"><path d="M5 12h14M12 5v14" stroke="currentColor" stroke-width="2.4" fill="none"/></svg>',
      target: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" stroke="currentColor" stroke-width="2" fill="none"/><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>',
      boostFood: '<svg viewBox="0 0 24 24"><path fill="#6DD68A" d="M6 18l4-12 4 8 4-4 2 8H6z"/></svg>',
      boostSpd: '<svg viewBox="0 0 24 24"><path fill="#66E0FF" d="M4 12h10l-4-4 1.5-1.5L18 12l-6.5 6.5L10 17l4-4H4z"/></svg>',
      boostDef: '<svg viewBox="0 0 24 24"><path fill="#E8B85A" d="M12 3l8 3v6c0 5-4 8-8 9-4-1-8-4-8-9V6l8-3z"/></svg>',
      eventBoost: '<svg viewBox="0 0 24 24"><path fill="#E8869A" d="M12 4l2.5 5 5.5.8-4 4 1 5.5L12 16.8 7 19.3l1-5.5-4-4 5.5-.8z"/></svg>',
      eventLarva: '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="12" rx="6" ry="9" fill="#FFD988"/></svg>',
      eventBuild: '<svg viewBox="0 0 24 24"><path fill="#C68A56" d="M4 10l8-6 8 6v10H4V10z"/></svg>',
      train: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3" fill="#E8B85A"/><path fill="#E8B85A" d="M6 20v-2a6 6 0 0 1 12 0v2H6z"/></svg>',
      gather: '<svg viewBox="0 0 24 24"><path fill="#6DD68A" d="M17 5C9 5 5 9 5 17c2 0 8-2 11-5 2-2 3-5 3-7-2 1-4 3-5 5 1-2 2-4 4-5-2 1-5 2-6 4z"/></svg>',
      build: '<svg viewBox="0 0 24 24"><path fill="#E8B85A" d="M12 3l8 8h-4v10h-8V11H4z"/></svg>'
    };

    // ---- build dom ----
    const root = document.createElement('div');
    root.id = 'ug-game';
    root.style.display = 'none';

    // TOP BAR
    const topbar = el('div', { id: 'ug-topbar' });
    const brand = el('div', { id: 'ug-brand', className: 'ug-panel' });
    brand.innerHTML = `<div class="hex">${svgs.hex}</div>
      <div class="brand-text"><h1>ANT COLONY</h1><p>Living Cross-Chain Civ</p></div>`;
    topbar.appendChild(brand);

    const resources = el('div', { id: 'ug-resources' });
    const resDefs = [
      { id: 'food', label: 'Food', icon: svgs.leaf, val: '12.4K', rate: '+320 /h' },
      { id: 'leaves', label: 'Leaves', icon: svgs.leaf, val: '8.7K', rate: '+210 /h' },
      { id: 'minerals', label: 'Minerals', icon: svgs.rock, val: '6.2K', rate: '+180 /h' },
      { id: 'larvae', label: 'Larvae', icon: svgs.drop, val: '3.1K', rate: '+90 /h' }
    ];
    resDefs.forEach(r => {
      const pill = el('div', { className: 'ug-panel ug-res' });
      pill.innerHTML = `<div class="ico">${r.icon}</div>
        <div><div class="label">${r.label}</div>
          <div><span class="val" data-res="${r.id}">${r.val}</span><span class="rate">${r.rate}</span></div>
        </div>`;
      resources.appendChild(pill);
    });
    topbar.appendChild(resources);

    const strength = el('div', { className: 'ug-panel ug-strength' });
    strength.innerHTML = `<div class="ico">${svgs.shield}</div>
      <div><div class="label">Colony Strength</div><div class="val" id="ug-strength-val">8,450</div></div>`;
    topbar.appendChild(strength);

    ['bell', 'book', 'gear'].forEach(k => {
      const b = el('div', { className: 'ug-panel ug-iconbtn' });
      b.innerHTML = svgs[k];
      topbar.appendChild(b);
    });
    root.appendChild(topbar);

    // LEFT SIDEBAR
    const leftbar = el('div', { id: 'ug-leftbar' });
    const overview = el('div', { id: 'ug-overview', className: 'ug-panel' });
    const overTitle = el('div', { className: 'ug-section' });
    overTitle.innerHTML = `<div class="ug-kicker">Overview</div>`;
    const navWrap = el('div', { className: 'ug-section', id: 'ug-nav' });
    [
      { id: 'map', label: 'Colony Map', ic: svgs.map, active: true },
      { id: 'workers', label: 'Workers', ic: svgs.worker },
      { id: 'upgrades', label: 'Upgrades', ic: svgs.upgrade },
      { id: 'research', label: 'Research', ic: svgs.flask },
      { id: 'quests', label: 'Quests', ic: svgs.quest },
      { id: 'stats', label: 'Statistics', ic: svgs.chart }
    ].forEach(n => {
      const row = el('div', { className: 'ug-nav-row' + (n.active ? ' active' : '') });
      row.innerHTML = `${n.ic}<span>${n.label}</span>`;
      navWrap.appendChild(row);
    });
    overview.appendChild(overTitle);
    overview.appendChild(navWrap);
    leftbar.appendChild(overview);

    // status panel
    const status = el('div', { id: 'ug-status', className: 'ug-panel' });
    const statSec = el('div', { className: 'ug-section' });
    statSec.innerHTML = `<div class="ug-kicker">Colony Status</div>
      <div class="ug-stat-row"><span class="name"><span class="dot" style="background:#E8B85A"></span>Population</span><span class="num" id="ug-pop">2,340</span></div>
      <div class="ug-stat-row"><span class="name"><span class="dot" style="background:#E8B85A"></span>Workers</span><span class="num" id="ug-workers">1,890</span></div>
      <div class="ug-stat-row"><span class="name"><span class="dot" style="background:#66E0FF"></span>Soldiers</span><span class="num" id="ug-soldiers">280</span></div>
      <div class="ug-stat-row"><span class="name"><span class="dot" style="background:#B47EE0"></span>Larvae</span><span class="num" id="ug-larvae">170</span></div>`;
    status.appendChild(statSec);
    const buffSec = el('div', { className: 'ug-section' });
    buffSec.innerHTML = `<div class="ug-kicker">Active Buffs</div>
      <div class="ug-buff"><div class="b-ico">${svgs.boostFood}</div>
        <div><div class="b-name">Food Gathering I</div><div class="b-sub">+10% Food</div></div>
        <div class="b-time" data-buff="food">12:45</div></div>
      <div class="ug-buff"><div class="b-ico">${svgs.boostSpd}</div>
        <div><div class="b-name">Movement Boost</div><div class="b-sub">+15% Speed</div></div>
        <div class="b-time" data-buff="spd">08:30</div></div>
      <div class="ug-buff"><div class="b-ico">${svgs.boostDef}</div>
        <div><div class="b-name">Defense Up I</div><div class="b-sub">+10% Defense</div></div>
        <div class="b-time" data-buff="def">15:20</div></div>`;
    status.appendChild(buffSec);
    leftbar.appendChild(status);

    const logBtn = el('div', { id: 'ug-log-btn', className: 'ug-panel' });
    logBtn.innerHTML = `${svgs.log} <span style="flex:1">Colony Log</span> ${svgs.chev}`;
    leftbar.appendChild(logBtn);

    const zoom = el('div', { id: 'ug-zoom', className: 'ug-panel' });
    zoom.innerHTML = `<button title="Zoom out">${svgs.minus}</button>
      <span class="pct">100%</span>
      <button title="Zoom in">${svgs.plus}</button>
      <button id="ug-debug-btn" title="Toggle debug graph">${svgs.target}</button>`;
    leftbar.appendChild(zoom);
    root.appendChild(leftbar);

    // RIGHT SIDEBAR
    const rightbar = el('div', { id: 'ug-rightbar' });

    const blurb = el('div', { id: 'ug-blurb', className: 'ug-panel ug-section' });
    blurb.innerHTML = `<h3>Inside the Colony</h3>
      <p>A living cross-chain colony.</p>
      <p>Click any chamber to command your agents and manage resources.</p>`;
    rightbar.appendChild(blurb);

    const obj = el('div', { id: 'ug-objective', className: 'ug-panel ug-section' });
    obj.innerHTML = `<div class="ug-kicker">Current Objective</div>
      <div class="ug-obj-card">
        <div class="ic">${svgs.quest}</div>
        <div><div class="title">Expand the Nursery</div><div class="sub">Upgrade Nursery to level 3</div></div>
      </div>
      <div class="ug-progress"><div class="fill"></div><div class="pct">2 / 3</div></div>`;
    rightbar.appendChild(obj);

    const events = el('div', { id: 'ug-events', className: 'ug-panel ug-section' });
    events.innerHTML = `<div class="ug-kicker">Events</div>
      <div class="ug-event"><div class="ic">${svgs.eventBoost}</div><span class="name">Resource boost</span><span class="when">07:45</span></div>
      <div class="ug-event"><div class="ic">${svgs.eventLarva}</div><span class="name">New larvae ready</span><span class="when">12:30</span></div>
      <div class="ug-event"><div class="ic">${svgs.eventBuild}</div><span class="name">Chamber complete</span><span class="when">18:20</span></div>
      <button id="ug-viewall">View all</button>`;
    rightbar.appendChild(events);

    const actions = el('div', { id: 'ug-actions', className: 'ug-panel ug-section' });
    actions.innerHTML = `<div class="ug-kicker">Quick Actions</div>
      <button class="ug-action"><div class="ic">${svgs.train}</div>Train Workers</button>
      <button class="ug-action"><div class="ic">${svgs.gather}</div>Gather Resources</button>
      <button class="ug-action"><div class="ic">${svgs.build}</div>Upgrade Chamber</button>`;
    rightbar.appendChild(actions);
    root.appendChild(rightbar);

    // LEGEND
    const legend = el('div', { id: 'ug-legend', className: 'ug-panel ug-section' });
    legend.style.padding = '8px 24px';
    [['#6DD68A', 'Resource'], ['#E8B85A', 'Production'], ['#66E0FF', 'Storage'], ['#B47EE0', 'Special']].forEach(([c, l]) => {
      const item = el('div', { className: 'ug-legend-item' });
      item.innerHTML = `<span class="swatch" style="background:${c};box-shadow:0 0 8px ${c}55"></span>${l}`;
      legend.appendChild(item);
    });
    root.appendChild(legend);

    document.body.appendChild(root);
    H._ugRoot = root;

    // ---- wire interactivity ----
    const debugBtn = root.querySelector('#ug-debug-btn');
    if (debugBtn) debugBtn.addEventListener('click', () => {
      const on = DN.underground.toggleDebug();
      debugBtn.classList.toggle('on', on);
    });
    // nav rows just switch active styling — no actual routing yet
    navWrap.querySelectorAll('.ug-nav-row').forEach(row => {
      row.addEventListener('click', () => {
        navWrap.querySelectorAll('.ug-nav-row').forEach(r => r.classList.remove('active'));
        row.classList.add('active');
      });
    });

    // ---- live tick (~4Hz) ----
    H._ugTickStart = Date.now();
    setInterval(() => H._ugTick(), 250);
  };

  // little DOM helper
  function el(tag, props) {
    const e = document.createElement(tag);
    if (props) for (const k in props) {
      if (k === 'className') e.className = props[k];
      else if (k === 'id') e.id = props[k];
      else if (k === 'style') e.style.cssText = props[k];
      else e.setAttribute(k, props[k]);
    }
    return e;
  }

  H._applyUgAccent = function (hex) {
    if (!H._ugRoot) return;
    const c = '#' + hex.toString(16).padStart(6, '0');
    // currently only the progress fill uses the accent; the rest stays warm gold
    const fill = H._ugRoot.querySelector('.ug-progress .fill');
    if (fill) fill.style.background = `linear-gradient(90deg, ${c}, ${c}AA)`;
  };

  // ~4Hz updater for resource numbers, buff timers, population.
  H._ugTick = function () {
    if (!H._ugRoot || H._ugRoot.style.display === 'none') return;
    const t = (Date.now() - H._ugTickStart) / 1000;
    const $$ = sel => H._ugRoot.querySelector(sel);

    // live ant counts from the underground sim
    const u = DN.underground;
    if (u && u.agents) {
      const workerCount = u.agents.length;
      const larvaeCount = u.larvae ? u.larvae.length : 0;
      const pop = workerCount + larvaeCount + 1; // +queen
      // smooth-up display numbers
      const popEl = $$('#ug-pop'); if (popEl) popEl.textContent = String(2300 + pop).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      const wEl = $$('#ug-workers'); if (wEl) wEl.textContent = String(1850 + workerCount).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      const lEl = $$('#ug-larvae'); if (lEl) lEl.textContent = String(170 + larvaeCount).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    }
    // resource drift — gentle increments tied to t for liveness
    const drift = i => (12.4 + i * 0.4 + t * 0.001).toFixed(1) + 'K';
    H._ugRoot.querySelectorAll('[data-res]').forEach((node, i) => { node.textContent = drift(i); });

    // buff timers count down
    const fmt = sec => {
      const m = Math.max(0, Math.floor(sec / 60));
      const s = Math.max(0, Math.floor(sec % 60));
      return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    };
    H._ugRoot.querySelectorAll('[data-buff]').forEach((node, i) => {
      const baselines = [12 * 60 + 45, 8 * 60 + 30, 15 * 60 + 20];
      node.textContent = fmt(baselines[i] - t);
    });
  };

  return H;
})();
