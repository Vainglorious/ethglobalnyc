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
    H.clearInspector();
    return H;
  };

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
    $('inspector').innerHTML =
      '<div class="insp-kicker">Inspector</div>' +
      '<div class="insp-empty" style="margin-top:12px">Hover any colony, agent or cache for live telemetry.<br><br>' +
      '<b>Click a colony</b> to open it and enter underground. <b>Click an ant</b> to inspect or follow a single agent.</div>';
  };

  H.showColony = function (col) {
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
    const c = hex(a.col.accent);
    const name = a.name || ('Worker ' + a.id.split('-').slice(-1));
    $('inspector').innerHTML =
      `<div class="insp-head"><div class="insp-icon" style="background:${c}22;box-shadow:inset 0 0 0 1px ${c}66">
        <div style="width:13px;height:13px;border-radius:3px;background:${c};box-shadow:0 0 10px ${c}"></div></div>
        <div><div class="insp-kicker">${a.role}${a.hero ? ' · Gen ' + a.gen : ''}</div><div class="insp-name">${name}</div></div></div>
      <div class="metrics">
        <div class="metric"><div class="mk">Forecast Acc</div><div class="mv">${a.accuracy || (52 + (a.inst % 30))}<small>%</small></div></div>
        <div class="metric"><div class="mk">Reputation</div><div class="mv">${a.reputation || (30 + (a.inst % 50))}</div></div>
        <div class="metric"><div class="mk">USDC Staked</div><div class="mv"><small>$</small>${a.staked || (10 + a.inst % 60) + '.0'}</div></div>
        <div class="metric"><div class="mk">Age</div><div class="mv">${a.age || (1 + a.inst % 12)}<small> sol</small></div></div>
      </div>
      <div class="vital-bar"><div class="vlabel"><span>Home colony</span><span style="color:${c}">${a.col.name}</span></div></div>
      <div class="vital-bar" style="margin-top:9px"><div class="vlabel"><span>Current task</span><span id="a-task">—</span></div></div>
      <div class="vital-bar" style="margin-top:9px"><div class="vlabel"><span>Carrying</span><span id="a-cargo">—</span></div></div>
      <div class="section-label">Recent activity</div>
      <div class="insp-empty" style="font-size:12px">${antBlurb(a)}</div>
      <button class="btn-primary" id="follow-ant" style="background:${following ? 'rgba(255,238,205,0.1)' : ''};color:${following ? 'var(--ink)' : ''};border-color:var(--border-strong)">
        <svg viewBox="0 0 24 24" style="fill:${following ? 'var(--ink)' : '#2a1d08'}"><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3" stroke="${following ? 'var(--ink)' : '#2a1d08'}" stroke-width="2" fill="none"/></svg>
        ${following ? 'Stop following' : 'Follow agent'}</button>`;
    $('follow-ant').addEventListener('click', () => DN.app.toggleFollow(a));
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
    $('inspector').innerHTML =
      `<div class="insp-head"><div class="insp-icon" style="background:${c}22;box-shadow:inset 0 0 0 1px ${c}66">
        <div style="width:13px;height:13px;border-radius:3px;background:${c}"></div></div>
        <div><div class="insp-kicker">${col.name} · Chamber</div><div class="insp-name">${room.name}</div></div></div>
      <div class="insp-empty" style="margin-top:14px">${blurbs[room.prop] || ''}</div>`;
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
    ['stats', 'hotbar', 'tools', 'transport', 'thoughts', 'cammode', 'brand', 'enterbanner', 'regions'].forEach(id => {
      const el = $(id); if (!el) return;
      el.style.display = on ? 'none' : '';
    });
    if (on) {
      H._open = null;
      $('inspector').innerHTML = '<div class="insp-kicker">Inside the colony</div>' +
        '<div class="insp-empty" style="margin-top:12px">A living cross-section of the civilization. <b>Click any chamber</b> to learn what its agents are doing — from the Queen seeding new lineages to the Staking Room settling USDC.</div>';
    } else {
      H.clearInspector();
    }
  };

  return H;
})();
