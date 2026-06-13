// Di-nasty — underground colony: cinematic cutaway, 11 chambers, tunnels, moving ants
window.DN = window.DN || {};

DN.underground = (function () {
  const U = { active: false, col: null };
  let scene, camera, controls, dom;
  const P = DN.palette;
  const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _s = new THREE.Vector3(), _p = new THREE.Vector3();

  const ROOMS = [
    { id: 'queen', name: 'Queen Chamber', x: 0, y: -11, r: 7.5, prop: 'queen' },
    { id: 'nursery', name: 'Nursery', x: -17, y: -8, r: 5, prop: 'eggs' },
    { id: 'forecast', name: 'Forecast Chamber', x: 17, y: -10, r: 5.5, prop: 'forecast' },
    { id: 'debate', name: 'Debate Hall', x: -25, y: -20, r: 5.5, prop: 'debate' },
    { id: 'storage', name: 'Resource Storage', x: 25, y: -21, r: 5, prop: 'storage' },
    { id: 'economy', name: 'Economy Vault', x: 9, y: -25, r: 5, prop: 'coins' },
    { id: 'memory', name: 'Memory Archives', x: -9, y: -27, r: 5, prop: 'archive' },
    { id: 'dorm', name: 'Agent Dormitories', x: -27, y: -33, r: 5, prop: 'beds' },
    { id: 'knowledge', name: 'Knowledge Exchange', x: -2, y: -34, r: 5, prop: 'exchange' },
    { id: 'lineage', name: 'Lineage Hall', x: 24, y: -33, r: 5.5, prop: 'lineage' },
    { id: 'staking', name: 'Staking Room', x: 13, y: -39, r: 5, prop: 'stake' }
  ];
  const TUNNELS = [
    ['ent', 'queen'], ['queen', 'nursery'], ['queen', 'forecast'], ['nursery', 'debate'],
    ['forecast', 'storage'], ['queen', 'economy'], ['queen', 'memory'], ['debate', 'dorm'],
    ['memory', 'knowledge'], ['economy', 'lineage'], ['economy', 'staking'], ['forecast', 'economy'],
    ['knowledge', 'dorm'], ['storage', 'lineage']
  ];
  const ENT = { id: 'ent', x: 0, y: 2 };
  function node(id) { return id === 'ent' ? ENT : ROOMS.find(r => r.id === id); }

  function labelSprite(text, accent) {
    const c = document.createElement('canvas'); c.width = 256; c.height = 64;
    const ctx = c.getContext('2d');
    ctx.fillStyle = 'rgba(20,13,7,0.82)';
    roundRect(ctx, 6, 14, 244, 36, 18); ctx.fill();
    ctx.fillStyle = '#' + accent.toString(16).padStart(6, '0');
    ctx.beginPath(); ctx.arc(28, 32, 6, 0, 6.28); ctx.fill();
    ctx.fillStyle = '#F4ECE0'; ctx.font = '600 22px -apple-system, system-ui, sans-serif';
    ctx.textBaseline = 'middle'; ctx.fillText(text, 46, 33);
    const tex = new THREE.CanvasTexture(c);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false }));
    sp.scale.set(11, 2.75, 1);
    return sp;
  }
  function roundRect(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }

  function buildProp(kind, accent) {
    const b = new DN.util.VoxelBuilder();
    const acc = accent, gold = 0xE8C24A, white = 0xEDE3D2, dark = P.antDark;
    if (kind === 'queen') {
      b.box([2.2, 1.6, 3.2], [0, 0.8, -0.5], P.ant);
      b.box([1.4, 1.2, 1.4], [0, 1.0, 1.4], dark);
      b.box([1.6, 0.5, 0.4], [0, 2.0, 1.4], gold); // crown
      b.box([0.3, 0.7, 0.3], [-0.5, 2.4, 1.4], gold); b.box([0.3, 0.7, 0.3], [0.5, 2.4, 1.4], gold);
    } else if (kind === 'eggs') {
      for (let i = 0; i < 5; i++) b.box([0.8, 1.1, 0.8], [(i - 2) * 1.0, 0.6, (i % 2) * 0.8], white);
    } else if (kind === 'forecast') {
      for (let i = 0; i < 5; i++) b.box([0.7, 0.6 + i * 0.5, 0.7], [(i - 2) * 0.9, (0.6 + i * 0.5) / 2, 0], i % 2 ? acc : 0x66C6E0);
    } else if (kind === 'debate') {
      b.box([1, 0.9, 1.6], [-1.4, 0.5, 0], P.ant); b.box([1, 0.9, 1.6], [1.4, 0.5, 0], P.ant);
      b.box([0.7, 0.7, 0.2], [0, 1.6, 0], acc);
    } else if (kind === 'storage') {
      for (let i = 0; i < 4; i++) { const a = i / 4 * 6.28; b.box([0.9, 1.6, 0.9], [Math.cos(a) * 1.2, 0.8, Math.sin(a) * 1.2], 0x66C6E0); }
    } else if (kind === 'coins') {
      for (let i = 0; i < 3; i++) for (let j = 0; j < 3 - i; j++) b.box([1.3, 0.4, 1.3], [(j - (2 - i) / 2) * 1.5, 0.2 + i * 0.42, 0], gold);
    } else if (kind === 'archive') {
      for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) b.box([1.0, 1.0, 0.9], [(i - 1) * 1.2, 0.5 + j * 1.1, 0], j % 2 ? white : acc);
    } else if (kind === 'beds') {
      for (let i = 0; i < 3; i++) b.box([1.6, 0.4, 0.9], [(i - 1) * 2.0, 0.2, 0], white);
    } else if (kind === 'exchange') {
      b.box([1.0, 1.4, 1.0], [-1.5, 0.7, 0], acc); b.box([1.0, 1.4, 1.0], [1.5, 0.7, 0], 0x66C6E0);
      b.box([2.2, 0.2, 0.2], [0, 1.0, 0], gold);
    } else if (kind === 'lineage') {
      b.box([0.5, 2.4, 0.5], [0, 1.2, 0], P.trunk);
      for (let i = 0; i < 4; i++) { const a = i / 4 * 6.28; b.box([0.7, 0.7, 0.7], [Math.cos(a) * 1.8, 2.2 + Math.sin(a), Math.sin(a) * 0.5], acc); }
    } else if (kind === 'stake') {
      b.box([2.4, 2.0, 2.0], [0, 1.0, 0], 0x2E7D6B);
      b.box([1.2, 1.2, 0.3], [0, 1.0, 1.1], gold); // USDC face
    }
    return b.geometry();
  }

  U.init = function () {
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1c1208);
    scene.fog = new THREE.Fog(0x1c1208, 50, 140);
    camera = new THREE.PerspectiveCamera(50, innerWidth / innerHeight, 0.1, 600);
    dom = DN.world.renderer.domElement;

    // soil backdrop
    const wallMat = DN.util.voxelMat({ roughness: 1.0, flatShading: false });
    const wall = new THREE.Mesh(new THREE.BoxGeometry(120, 90, 8), wallMat);
    const wpos = wall.geometry.attributes.position;
    const wcol = new Float32Array(wpos.count * 3);
    const cd = new THREE.Color(0x3a2614), cd2 = new THREE.Color(0x4a3018);
    const nz = new DNNoise(13);
    for (let i = 0; i < wpos.count; i++) {
      const t = nz.n2(wpos.getX(i) * 0.12, wpos.getY(i) * 0.12) * 0.5 + 0.5;
      const c = cd.clone().lerp(cd2, t);
      wcol[i * 3] = c.r; wcol[i * 3 + 1] = c.g; wcol[i * 3 + 2] = c.b;
    }
    wall.geometry.setAttribute('color', new THREE.BufferAttribute(wcol, 3));
    wall.position.set(0, -22, -5);
    wall.receiveShadow = true;
    scene.add(wall);

    scene.add(new THREE.AmbientLight(0x6b4a2a, 0.7));
    const key = new THREE.DirectionalLight(0xFFE3B0, 0.8);
    key.position.set(20, 30, 40); scene.add(key);
    // shaft light from the surface
    const shaft = new THREE.SpotLight(0xFFF0CE, 1.4, 80, 0.7, 0.6);
    shaft.position.set(0, 18, 12); shaft.target.position.set(0, -12, 0);
    scene.add(shaft); scene.add(shaft.target);

    // tunnels (dark rounded tubes)
    TUNNELS.forEach(t => {
      const a = node(t[0]), b = node(t[1]);
      const ax = new THREE.Vector3(a.x, a.y, 0), bx = new THREE.Vector3(b.x, b.y, 0);
      const len = ax.distanceTo(bx);
      const tube = new THREE.Mesh(new THREE.CylinderGeometry(1.1, 1.1, len, 10), new THREE.MeshStandardMaterial({ color: 0x180f06, roughness: 1 }));
      tube.position.copy(ax).lerp(bx, 0.5); tube.position.z = -0.5;
      tube.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), bx.clone().sub(ax).normalize());
      scene.add(tube);
    });

    // chambers
    U.rooms = {};
    ROOMS.forEach(r => {
      const accent = 0xE3A53C;
      const g = new THREE.Group(); g.position.set(r.x, r.y, 0);
      // cavity interior (lighter warm dirt disc)
      const inner = new THREE.Mesh(new THREE.CircleGeometry(r.r, 40), new THREE.MeshStandardMaterial({ color: 0x6b4a28, roughness: 1 }));
      inner.position.z = 0.2; g.add(inner);
      // floor slab
      const floor = new THREE.Mesh(new THREE.BoxGeometry(r.r * 1.8, 0.6, 2), DN.util.voxelMat());
      floor.geometry.setAttribute('color', flat(floor.geometry, 0x5a3a1e));
      floor.position.set(0, -r.r * 0.7, 0.6); g.add(floor);
      // rim ring
      const rim = new THREE.Mesh(new THREE.TorusGeometry(r.r, 0.5, 8, 40), new THREE.MeshStandardMaterial({ color: 0x2a1a0c, roughness: 1 }));
      rim.position.z = 0.3; g.add(rim);
      U.roomAccent = U.roomAccent || {};
      r._accent = accent;
      g._roomDef = r;
      scene.add(g);
      U.rooms[r.id] = g;
    });

    // build agents
    buildAgents();

    // ambient floating spores
    const sn = 120, sp = new Float32Array(sn * 3);
    for (let i = 0; i < sn; i++) { sp[i * 3] = (Math.random() - .5) * 90; sp[i * 3 + 1] = -Math.random() * 50; sp[i * 3 + 2] = (Math.random() - .5) * 10; }
    const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.BufferAttribute(sp, 3));
    U.spores = new THREE.Points(sg, new THREE.PointsMaterial({ size: 0.5, map: DN.util.softSprite(), color: 0xFFD98A, transparent: true, opacity: 0.4, depthWrite: false, blending: THREE.AdditiveBlending }));
    U.spores.frustumCulled = false; scene.add(U.spores); U._sporeBase = sp.slice();

    U.scene = scene; U.camera = camera;
    return U;
  };

  function flat(geo, hex) {
    const c = new THREE.Color(hex), arr = new Float32Array(geo.attributes.position.count * 3);
    for (let i = 0; i < geo.attributes.position.count; i++) { arr[i * 3] = c.r; arr[i * 3 + 1] = c.g; arr[i * 3 + 2] = c.b; }
    return new THREE.BufferAttribute(arr, 3);
  }

  let agents, agentMesh, propGroups = [];
  function buildAgents() {
    // small voxel ants traveling tunnels / milling in rooms
    const b = new DN.util.VoxelBuilder();
    b.box([0.5, 0.4, 0.5], [0, 0.2, -0.3], P.ant);
    b.box([0.35, 0.3, 0.35], [0, 0.22, 0.2], P.antDark);
    const geo = b.geometry();
    const N = 120;
    agentMesh = new THREE.InstancedMesh(geo, DN.util.voxelMat({ roughness: 0.7 }), N);
    agentMesh.frustumCulled = false;
    scene.add(agentMesh);
    agents = [];
    const ids = ROOMS.map(r => r.id);
    for (let i = 0; i < N; i++) {
      const room = ROOMS[Math.floor(Math.random() * ROOMS.length)];
      agents.push({
        room, mode: Math.random() < 0.6 ? 'mill' : 'travel',
        x: room.x + (Math.random() - .5) * room.r, y: room.y - room.r * 0.5 + Math.random() * 2,
        tx: 0, ty: 0, t: Math.random(), from: room, to: ROOMS[Math.floor(Math.random() * ROOMS.length)],
        sp: 0.3 + Math.random() * 0.4, phase: Math.random() * 6.28
      });
    }
  }

  U.enter = function (col) {
    U.active = true; U.col = col;
    // recolor accents to the colony
    ROOMS.forEach(r => { const g = U.rooms[r.id]; r._accent = col.accent; });
    propGroups.forEach(p => scene.remove(p)); propGroups = [];
    ROOMS.forEach(r => {
      const g = U.rooms[r.id];
      // (re)build prop + light + label with colony accent
      if (g._extra) g._extra.forEach(o => g.remove(o));
      const extra = [];
      const prop = new THREE.Mesh(buildProp(r.prop, col.accent), DN.util.voxelMat({ roughness: 0.7 }));
      prop.position.set(0, -r.r * 0.4 + 0.6, 0.8); prop.scale.setScalar(0.85); g.add(prop); extra.push(prop);
      const pl = new THREE.PointLight(col.accent, 0.9, r.r * 4); pl.position.set(0, 0, 4); g.add(pl); extra.push(pl);
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: DN.util.softSprite(), color: col.accent, transparent: true, opacity: 0.25, depthWrite: false, blending: THREE.AdditiveBlending }));
      glow.scale.set(r.r * 2.4, r.r * 2.4, 1); glow.position.z = 1; g.add(glow); extra.push(glow);
      const label = labelSprite(r.name, col.accent); label.position.set(0, r.r + 1.4, 2); g.add(label); extra.push(label);
      g._extra = extra;
    });
    // frame camera: dive from top
    camera.position.set(0, 14, 64);
    camera.lookAt(0, -22, 0);
    U._camTarget = new THREE.Vector3(0, -20, 0);
    U._camPos = new THREE.Vector3(2, -16, 58);
    U._diveT = 0;
  };

  U.exit = function () { U.active = false; };

  U.pickables = function () {
    return ROOMS.map(r => { const g = U.rooms[r.id]; g.userData.room = r; return g.children[0]; });
  };

  U.update = function (dt, elapsed) {
    if (!U.active) return;
    // dive-in ease
    if (U._diveT < 1) {
      U._diveT = Math.min(1, U._diveT + dt * 0.6);
      const k = 1 - Math.pow(1 - U._diveT, 3);
      camera.position.lerpVectors(new THREE.Vector3(0, 14, 70), U._camPos, k);
    }
    camera.lookAt(0, -21, 0);

    // agents
    for (const a of agents) {
      if (a.mode === 'mill') {
        a.x += Math.cos(elapsed * a.sp + a.phase) * dt * 1.5;
        a.y += Math.sin(elapsed * a.sp * 1.3 + a.phase) * dt * 1.0;
        const dx = a.x - a.room.x, dy = a.y - (a.room.y - a.room.r * 0.4);
        if (Math.hypot(dx, dy) > a.room.r * 0.7) { a.x -= dx * 0.1; a.y -= dy * 0.1; }
        if (Math.random() < 0.002) { a.mode = 'travel'; a.from = a.room; a.to = ROOMS[Math.floor(Math.random() * ROOMS.length)]; a.t = 0; }
      } else {
        a.t += dt * a.sp * 0.5;
        a.x = a.from.x + (a.to.x - a.from.x) * a.t;
        a.y = (a.from.y - 1) + ((a.to.y - 1) - (a.from.y - 1)) * a.t + Math.sin(a.t * Math.PI) * 2;
        if (a.t >= 1) { a.mode = 'mill'; a.room = a.to; }
      }
      const ang = Math.atan2((a.to.x - a.from.x), 1);
      _p.set(a.x, a.y, 0.9); _e.set(0, 0, a.mode === 'travel' ? ang * 0.3 : 0); _q.setFromEuler(_e); _s.setScalar(1);
      _m.compose(_p, _q, _s);
      agentMesh.setMatrixAt(agents.indexOf(a), _m);
    }
    agentMesh.instanceMatrix.needsUpdate = true;

    // room glow pulse
    ROOMS.forEach(r => {
      const g = U.rooms[r.id];
      if (g._extra) { const glow = g._extra[2]; if (glow) glow.material.opacity = 0.2 + Math.sin(elapsed * 1.5 + r.x) * 0.08; }
    });
    // spores drift
    if (U.spores) {
      const p = U.spores.geometry.attributes.position;
      for (let i = 0; i < p.count; i++) { p.array[i * 3 + 1] = U._sporeBase[i * 3 + 1] + Math.sin(elapsed * 0.3 + i) * 1.5; }
      p.needsUpdate = true;
    }
  };

  U.resize = function () { if (camera) { camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); } };

  return U;
})();
