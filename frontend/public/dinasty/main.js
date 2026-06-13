// Di-nasty — app orchestrator: sim clock, environment, transitions, controls
window.DN = window.DN || {};

DN.app = (function () {
  const App = { view: 'surface', selection: null, following: null };
  const S = { playing: true, speed: 1, simTime: 20, GEN: 60, DAY: 200, lastThought: 0, lastWeather: -100, wIdx: 0 };
  const WEATHER = [
    { name: 'Clear skies', fog: [180, 660], temp: 24 },
    { name: 'Soft fog', fog: [110, 380], temp: 19 },
    { name: 'Golden haze', fog: [150, 520], temp: 27 },
    { name: 'Bright sun', fog: [200, 720], temp: 29 }
  ];
  let world, clock, lastHud = 0;

  const THOUGHTS = [
    () => { const c = rc(); return [c.name + ' reinforced a pheromone highway to its richest data cache.', 'Forage', '#E8A23D']; },
    () => { const c = rc(); return [c.name + ' resolved Round #' + S.gen + ' at ' + c.stats.accuracy + '% accuracy — staking pays out.', 'Forecast', '#3FA89F']; },
    () => { const c = rc(); return ['Agents in ' + c.name + ' debated a low-evidence claim; reputation reallocated.', 'Debate', '#8E79C4']; },
    () => { const c = rc(); return [c.name + ' queen seeded ' + (2 + Math.floor(Math.random() * 6)) + ' new agents from top lineages.', 'Lineage', '#D96E54']; },
    () => ['Cross-colony knowledge exchange settled — evidence priced into the next round.', 'Economy', '#E8A23D'],
    () => { const c = lowFood(); return c ? [c.name + ' stores low (' + Math.round(c.stats.food) + '%) — biasing toward forage.', 'Forage', '#E8A23D'] : null; }
  ];
  function rc() { const a = DN.colony.list; return a[Math.floor(Math.random() * a.length)]; }
  function lowFood() { return DN.colony.list.slice().sort((a, b) => a.stats.food - b.stats.food)[0]; }

  function evolve(simDt) {
    DN.colony.list.forEach(c => {
      const s = c.stats;
      let consume = s.population * 0.0006 * simDt;
      if (c.directive === 'defend') consume *= 1.2; if (c.directive === 'expand') consume *= 1.15;
      s.food = Math.max(0, s.food - consume);
      let target = 40 + s.food * 0.5; if (c.directive === 'defend') target += 8;
      s.health += (target - s.health) * Math.min(1, 0.04 * simDt);
      s.health = Math.max(10, Math.min(100, s.health));
      s.population = Math.max(40, s.population + (s.food > 35 && s.health > 45 ? 0.8 : -0.6) * simDt * (c.directive === 'expand' ? 1.4 : 1));
      s.accuracy = Math.max(45, Math.min(96, s.accuracy + (Math.random() - 0.5) * 0.4 * simDt));
      s.staked = Math.max(80, s.staked + (Math.random() - 0.45) * 8 * simDt);
    });
  }

  function fmtClock() {
    const phase = (S.simTime % S.DAY) / S.DAY, mins = Math.floor(phase * 1440);
    return String(Math.floor(mins / 60)).padStart(2, '0') + ':' + String(mins % 60).padStart(2, '0');
  }
  function period(p) { return p < 0.22 ? 'Dawn' : p < 0.5 ? 'Midday' : p < 0.72 ? 'Dusk' : 'Night'; }

  function frame() {
    requestAnimationFrame(frame);
    const dt = Math.min(0.05, clock.getDelta());
    const el = clock.elapsedTime;
    const timeScale = S.playing ? S.speed : 0;
    const simDt = dt * timeScale;
    if (S.playing) S.simTime += simDt;
    S.gen = Math.floor(S.simTime / S.GEN) + 1;
    const phase = (S.simTime % S.DAY) / S.DAY;

    world.setDaylight(phase);
    if (S.simTime - S.lastWeather > 32) {
      S.lastWeather = S.simTime; S.wIdx = (S.wIdx + 1 + Math.floor(Math.random() * 2)) % WEATHER.length;
      const w = WEATHER[S.wIdx]; if (world.scene.fog) { world.scene.fog.near = w.fog[0]; world.scene.fog.far = w.fog[1]; }
    }

    evolve(simDt);

    if (App.view === 'surface') {
      world.update(dt, el);
      DN.flora.update(dt, el);
      DN.resources.update(dt, el);
      DN.colony.update(dt, el);
      DN.ants.update(dt, el, Math.max(0.0001, timeScale));
      DN.trails.update(dt, el);
      if (App.following) DN.camera.follow(() => DN.ants.heroPos(App.following));
      DN.camera.update(dt);
      DN.interactions.update();
      world.renderer.render(world.scene, world.camera);
    } else {
      DN.underground.update(dt, el);
      DN.interactions.update();
      world.renderer.render(DN.underground.scene, DN.underground.camera);
    }

    if (el - lastHud > 0.25) {
      lastHud = el;
      let staked = 0, acc = 0;
      DN.colony.list.forEach(c => { staked += c.stats.staked; acc += c.stats.accuracy; });
      DN.hud.setStats({
        colonies: DN.colony.list.length, ants: DN.ants.list.length, resources: DN.resources.list.filter(r => !r.depleted).length,
        staked, accuracy: Math.round(acc / DN.colony.list.length), round: S.gen
      });
      DN.hud.setTransport({ playing: S.playing, speed: S.speed, gen: S.gen, clock: 'Sol ' + (Math.floor(S.simTime / S.DAY) + 1) + ' · ' + fmtClock(), progress: (S.simTime % S.GEN) / S.GEN });
      const o = DN.hud._open;
      if (o && o.type === 'colony') DN.hud._updateColony(o.col);
      if (o && o.type === 'ant') DN.hud._updateAnt(o.ant);
      if (S.playing && S.simTime - S.lastThought > 6 / Math.max(0.5, S.speed)) {
        S.lastThought = S.simTime; let t = null, n = 0;
        if (DN.databridge && DN.databridge.ready) t = DN.databridge.nextThought();
        while (!t && n++ < 6) t = THOUGHTS[Math.floor(Math.random() * THOUGHTS.length)]();
        if (t) DN.hud.pushThought(t[0], t[1], t[2]);
      }
    }
  }

  // ---- public actions ----
  App.selectColony = function (col) {
    DN.colony.list.forEach(c => c.selected = (c === col));
    DN.ants.heroes.forEach(a => a.selected = false);
    App.selection = col; App.following = null;
    DN.hud.showColony(col);
    DN.camera.flyTo(col.corePos, 30, 18);
  };
  App.selectAnt = function (a) {
    DN.colony.list.forEach(c => c.selected = false);
    DN.ants.heroes.forEach(x => x.selected = (x === a));
    App.selection = a;
    DN.hud.showAnt(a, App.following === a);
    if (a.hero) DN.camera.flyTo(DN.ants.heroPos(a), 12, 6);
    else { const p = new THREE.Vector3(a.x, DN.world.heightAt(a.x, a.z), a.z); DN.camera.flyTo(p, 10, 5); }
  };
  App.toggleFollow = function (a) {
    App.following = (App.following === a) ? null : a;
    if (!App.following) DN.camera.stopFollow();
    DN.hud.showAnt(a, App.following === a);
  };
  App.setDirective = function (col, d) {
    col.directive = d;
    document.querySelectorAll('#inspector .dir-btn').forEach(b => b.classList.toggle('active', b.dataset.dir === d));
    const msg = { forage: 'Foraging columns dispatched toward the richest caches.', defend: 'Soldiers forming a defensive ring around the mound.', expand: 'Pioneers pushing the frontier to scout fresh ground.' };
    DN.hud.pushThought(col.name + ': ' + msg[d], d.replace(/^./, c => c.toUpperCase()), d === 'forage' ? '#E8A23D' : d === 'defend' ? '#3FA89F' : '#D96E54');
  };
  App.dropFood = function (p) {
    const res = DN.resources.spawn(p.x, p.z, 90);
    if (res) { DN.trails.rebuild(); DN.hud.pushThought('New forage cache detected — nearest foragers rerouting.', 'Forage', '#E8A23D'); }
  };

  App.enterColony = function (col) {
    if (App.view !== 'surface') return;
    App.selection = col;
    const fade = document.getElementById('fade'); fade.classList.add('show');
    DN.hud.hideEnterBanner();
    setTimeout(() => {
      App.view = 'underground';
      DN.camera.controls.enabled = false;
      DN.underground.resize();
      DN.underground.enter(col);
      DN.hud.setUnderground(true);
      DN.hud.pushThought('Descending into ' + col.name + ' — ' + Math.round(col.stats.population) + ' agents at work below.', 'World', '#E8A23D');
      requestAnimationFrame(() => fade.classList.remove('show'));
    }, 560);
  };
  App.exitColony = function () {
    if (App.view !== 'underground') return;
    const fade = document.getElementById('fade'); fade.classList.add('show');
    setTimeout(() => {
      App.view = 'surface';
      DN.camera.controls.enabled = (DN.camera.mode === 'cinematic');
      DN.hud.setUnderground(false);
      const col = DN.underground.col;
      DN.underground.exit();
      if (col) DN.camera.flyTo(col.corePos, 34, 20);
      requestAnimationFrame(() => fade.classList.remove('show'));
    }, 560);
  };

  App.setBiome = function (i) {
    if (App.view !== 'surface') return;
    const b = DN.biomes[i];
    if (!b || b === DN.world.biome) return;
    const fade = document.getElementById('fade'); fade.classList.add('show');
    DN.hud.setActiveBiome(i);
    setTimeout(() => {
      DN.world.applyBiome(b);
      DN.flora.rebuild();
      DN.hud.pushThought('Surveying ' + b.name + ' — ' + b.tag.toLowerCase() + ' conditions shift across the basin.', 'World', '#E8A23D');
      requestAnimationFrame(() => fade.classList.remove('show'));
    }, 560);
  };

  App.setCameraMode = function (m) {
    if (App.view === 'underground') return;
    DN.camera.setMode(m);
    if (m === 'explore') App.following = null;
  };

  const LENS = {
    world: () => { App.clearSelection(); DN.camera.flyTo(new THREE.Vector3(0, 4, 0), 320, 180, 2); DN.camera.autoRotate(true); },
    colonies: () => { const i = (DN.colony.list.indexOf(App.selection) + 1) % DN.colony.list.length; App.selectColony(DN.colony.list[i < 0 ? 0 : i]); },
    agents: () => { const h = DN.ants.heroes; const i = (h.indexOf(App.selection) + 1) % h.length; const a = h[i < 0 ? 0 : i]; App.selectAnt(a); App.toggleFollow(a); },
    economy: () => { DN.hud.pushThought('Treasury overview — total USDC staked across all colonies is compounding.', 'Economy', '#E8A23D'); },
    forecasts: () => { DN.hud.pushThought('Forecast board — agents are pricing the next round\'s outcome live.', 'Forecast', '#3FA89F'); },
    lineages: () => { DN.hud.pushThought('Lineage view — top-performing families dominate the gene pool.', 'Lineage', '#D96E54'); }
  };
  App.setLens = function (idx) {
    DN.hud.setActiveSlot(idx);
    const ids = ['world', 'colonies', 'agents', 'economy', 'forecasts', 'lineages'];
    if (LENS[ids[idx]]) LENS[ids[idx]]();
  };
  App.clearSelection = function () {
    DN.colony.list.forEach(c => c.selected = false);
    DN.ants.heroes.forEach(a => a.selected = false);
    App.selection = null; App.following = null; DN.camera.stopFollow();
    DN.hud.clearInspector();
  };

  function wire() {
    document.getElementById('play-btn').addEventListener('click', () => { S.playing = !S.playing; DN.camera.autoRotate(S.playing && !App.selection && !App.following); });
    document.querySelectorAll('#speeds .speed').forEach(s => s.addEventListener('click', () => { S.speed = parseFloat(s.dataset.s); }));
    const track = document.getElementById('tl-track'); let scrub = false;
    const doScrub = e => { const r = track.getBoundingClientRect(); const k = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)); S.simTime = Math.floor(S.simTime / S.GEN) * S.GEN + k * S.GEN; };
    track.addEventListener('pointerdown', e => { scrub = true; doScrub(e); track.setPointerCapture(e.pointerId); });
    track.addEventListener('pointermove', e => { if (scrub) doScrub(e); });
    track.addEventListener('pointerup', () => scrub = false);
    document.querySelectorAll('#tools .tool[data-tool]').forEach(t => t.addEventListener('click', () => DN.interactions.setTool(t.dataset.tool)));
    document.getElementById('tool-recenter').addEventListener('click', () => App.setLens(0));
    document.querySelectorAll('#cammode .cm').forEach(el => el.addEventListener('click', () => App.setCameraMode(el.dataset.mode)));
    document.getElementById('exitbtn').addEventListener('click', App.exitColony);

    addEventListener('keydown', e => {
      if (e.code === 'Space') { e.preventDefault(); document.getElementById('play-btn').click(); }
      else if (e.key >= '1' && e.key <= '6' && App.view === 'surface' && DN.camera.mode !== 'explore') App.setLens(parseInt(e.key) - 1);
      else if (e.key === 'f' || e.key === 'F') DN.interactions.setTool(DN.interactions.tool === 'food' ? 'inspect' : 'food');
      else if (e.key === 'c' || e.key === 'C') App.setCameraMode(DN.camera.mode === 'explore' ? 'cinematic' : 'explore');
      else if (e.key === 'e' || e.key === 'E') { if (App.selection && App.selection.stats) App.enterColony(App.selection); }
      else if (e.key === 'Escape') { if (App.view === 'underground') App.exitColony(); else if (DN.camera.mode === 'explore') App.setCameraMode('cinematic'); else App.clearSelection(); }
    });
    addEventListener('resize', () => DN.underground.resize());
  }

  App.boot = function () {
    world = DN.world.init(document.getElementById('scene'));
    DN.flora.init(world.scene);
    DN.resources.init(world.scene);
    DN.colony.init(world.scene);
    DN.ants.init(world.scene, DN.colony.list);
    DN.trails.init(world.scene, DN.colony.list);
    DN.underground.init();
    DN.camera.init();
    DN.hud.init();
    DN.interactions.init();
    DN.interactions.setTool('inspect');
    DN.hud.setCameraMode('cinematic');
    wire();

    clock = new THREE.Clock();
    frame();

    DN.hud.pushThought('Di-nasty online — four AI ant civilizations awakening across the basin.', 'World', '#E8A23D');
    setTimeout(() => DN.hud.pushThought('Foragers fanning out along fresh pheromone trails.', 'Forage', '#E8A23D'), 3000);

    setTimeout(() => { document.getElementById('intro').classList.add('hide'); DN.camera.flyTo(new THREE.Vector3(0, 4, 0), 300, 165, 2.4); DN.camera.autoRotate(true); }, 900);
    setTimeout(() => { document.getElementById('intro').style.display = 'none'; }, 2100);
  };

  return App;
})();

if (document.readyState === 'loading') addEventListener('DOMContentLoaded', DN.app.boot);
else DN.app.boot();
