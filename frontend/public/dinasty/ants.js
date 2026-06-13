// Di-nasty — ant agents: instanced voxel ants w/ shader-animated legs, behavior, hero ants
window.DN = window.DN || {};

DN.ants = (function () {
  const A = { perCol: 150, list: [], heroes: [], byMesh: {} };
  let scene, noise;
  const P = DN.palette;
  const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), _s = new THREE.Vector3(), _p = new THREE.Vector3();
  function ground(x, z) { return DN.world.heightAt(x, z); }

  // ---- ant geometry builder with leg-animation attributes ----
  function AntBuilder() { this.pos = []; this.norm = []; this.col = []; this.leg = []; this.root = []; this.phase = []; this._c = new THREE.Color(); }
  const FACES = [
    [[0, 0, 1], [[-.5, -.5, .5], [.5, -.5, .5], [.5, .5, .5], [-.5, .5, .5]]],
    [[0, 0, -1], [[.5, -.5, -.5], [-.5, -.5, -.5], [-.5, .5, -.5], [.5, .5, -.5]]],
    [[1, 0, 0], [[.5, -.5, .5], [.5, -.5, -.5], [.5, .5, -.5], [.5, .5, .5]]],
    [[-1, 0, 0], [[-.5, -.5, -.5], [-.5, -.5, .5], [-.5, .5, .5], [-.5, .5, -.5]]],
    [[0, 1, 0], [[-.5, .5, .5], [.5, .5, .5], [.5, .5, -.5], [-.5, .5, -.5]]],
    [[0, -1, 0], [[-.5, -.5, -.5], [.5, -.5, -.5], [.5, -.5, .5], [-.5, -.5, .5]]]
  ];
  AntBuilder.prototype.box = function (size, position, color, isLeg, root, phase, rot) {
    const c = this._c.set(color);
    const [sx, sy, sz] = size, [px, py, pz] = position;
    let ra = 0, rax = 'z'; if (rot) { ra = rot.a; rax = rot.axis; }
    const ca = Math.cos(ra), sa = Math.sin(ra);
    const R = (x, y, z) => {
      if (!ra) return [x, y, z];
      if (rax === 'z') return [x * ca - y * sa, x * sa + y * ca, z];
      if (rax === 'x') return [x, y * ca - z * sa, y * sa + z * ca];
      return [x * ca + z * sa, y, -x * sa + z * ca];
    };
    const lf = isLeg ? 1 : 0, rt = root || [0, 0, 0], ph = phase || 0;
    for (let f = 0; f < 6; f++) {
      const nm = FACES[f][0], corners = FACES[f][1];
      const rn = R(nm[0], nm[1], nm[2]);
      const vv = corners.map(v => { const r = R(v[0] * sx, v[1] * sy, v[2] * sz); return [r[0] + px, r[1] + py, r[2] + pz]; });
      const tri = [0, 1, 2, 0, 2, 3];
      for (let t = 0; t < 6; t++) {
        const v = vv[tri[t]];
        this.pos.push(v[0], v[1], v[2]); this.norm.push(rn[0], rn[1], rn[2]); this.col.push(c.r, c.g, c.b);
        this.leg.push(lf); this.root.push(rt[0], rt[1], rt[2]); this.phase.push(ph);
      }
    }
  };
  AntBuilder.prototype.geometry = function () {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(this.pos), 3));
    g.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(this.norm), 3));
    g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(this.col), 3));
    g.setAttribute('aLeg', new THREE.BufferAttribute(new Float32Array(this.leg), 1));
    g.setAttribute('aLegRoot', new THREE.BufferAttribute(new Float32Array(this.root), 3));
    g.setAttribute('aLegPhase', new THREE.BufferAttribute(new Float32Array(this.phase), 1));
    return g;
  };

  function buildAntGeo(mark) {
    const b = new AntBuilder();
    const body = P.ant, dark = P.antDark, light = P.antLight;
    // gaster (abdomen) — tapered teardrop from 3 segments
    b.box([0.5, 0.5, 0.5], [0, 0.42, -0.34], body);
    b.box([0.6, 0.58, 0.5], [0, 0.42, -0.66], body);
    b.box([0.42, 0.42, 0.34], [0, 0.42, -0.98], body);
    b.box([0.34, 0.26, 0.4], [0, 0.54, -0.6], mark);         // dorsal faction stripe
    // petiole (waist) + thorax hump
    b.box([0.18, 0.16, 0.22], [0, 0.4, -0.04], dark);
    b.box([0.42, 0.4, 0.56], [0, 0.4, 0.18], dark);
    b.box([0.3, 0.34, 0.32], [0, 0.52, 0.06], dark);
    // head
    b.box([0.5, 0.46, 0.44], [0, 0.44, 0.66], dark);
    b.box([0.1, 0.14, 0.08], [0.2, 0.5, 0.86], 0x0e0e0e);    // eyes
    b.box([0.1, 0.14, 0.08], [-0.2, 0.5, 0.86], 0x0e0e0e);
    // mandibles (angled forward)
    b.box([0.06, 0.07, 0.26], [0.13, 0.36, 0.98], dark, false, null, 0, { axis: 'y', a: 0.32 });
    b.box([0.06, 0.07, 0.26], [-0.13, 0.36, 0.98], dark, false, null, 0, { axis: 'y', a: -0.32 });
    // antennae (animated, gentle)
    b.box([0.05, 0.05, 0.5], [0.13, 0.62, 1.02], light, true, [0.1, 0.58, 0.8], 1.4, { axis: 'x', a: -0.5 });
    b.box([0.05, 0.05, 0.5], [-0.13, 0.62, 1.02], light, true, [-0.1, 0.58, 0.8], 1.9, { axis: 'x', a: -0.5 });
    // 6 legs (tripod gait phases)
    const hipY = 0.34, legZ = [0.34, 0.04, -0.28];
    for (let s = 0; s < 2; s++) {
      const sign = s ? -1 : 1;
      for (let i = 0; i < 3; i++) {
        const hx = 0.22 * sign, hz = legZ[i];
        const root = [hx, hipY, hz];
        const ph = ((s + i) % 2) * Math.PI;
        // upper segment angled out
        b.box([0.06, 0.06, 0.46], [hx + 0.3 * sign, hipY + 0.05, hz], dark, true, root, ph, { axis: 'z', a: sign * 0.7 });
        // foot segment down to ground
        b.box([0.05, 0.4, 0.05], [hx + 0.54 * sign, hipY - 0.2, hz], dark, true, root, ph);
      }
    }
    return b.geometry();
  }

  function antMaterial() {
    const mat = DN.util.voxelMat({ roughness: 0.42, metalness: 0.12, flatShading: false });
    mat.onBeforeCompile = function (sh) {
      sh.uniforms.uTime = { value: 0 };
      sh.vertexShader = sh.vertexShader.replace('#include <common>', `#include <common>
        attribute float aLeg;
        attribute vec3 aLegRoot;
        attribute float aLegPhase;
        attribute vec2 aInst;
        uniform float uTime;`);
      sh.vertexShader = sh.vertexShader.replace('#include <begin_vertex>', `#include <begin_vertex>
        if(aLeg > 0.5){
          float walk = uTime * aInst.y + aInst.x;
          float sw = sin(walk + aLegPhase);
          float ang = sw * 0.55;
          vec3 lp = transformed - aLegRoot;
          float ca = cos(ang), sa = sin(ang);
          lp = vec3(lp.x*ca + lp.z*sa, lp.y, -lp.x*sa + lp.z*ca);
          lp.y += max(0.0, sw) * 0.14;
          transformed = aLegRoot + lp;
        }
        transformed.y += sin(uTime*aInst.y*2.0 + aInst.x)*0.018;`);
      mat.userData.sh = sh;
    };
    return mat;
  }

  A.init = function (sceneRef, colonies) {
    scene = sceneRef;
    noise = new DNNoise(404);
    const mat = antMaterial();
    A.material = mat;
    A.meshes = [];

    colonies.forEach((col, ci) => {
      const geo = buildAntGeo(col.accent);
      const n = A.perCol;
      const mesh = new THREE.InstancedMesh(geo, mat, n);
      mesh.castShadow = false;
      mesh.frustumCulled = false;
      mesh.userData.colIndex = ci;
      const inst = new Float32Array(n * 2);
      for (let i = 0; i < n; i++) {
        inst[i * 2] = Math.random() * 6.28;        // phase
        inst[i * 2 + 1] = 7 + Math.random() * 4;    // gait rate
        const ang = Math.random() * 6.28, rr = Math.random() * 8;
        const dockA = Math.random() * 6.28, dockR = 4 + Math.random() * 11;
        const ant = {
          id: 'w-' + ci + '-' + i, ci, col, inst: i, mesh,
          x: col.pos.x + Math.cos(ang) * rr, z: col.pos.z + Math.sin(ang) * rr,
          yaw: Math.random() * 6.28, speed: 5.5 + Math.random() * 3.5,
          state: Math.random() < 0.5 ? 'out' : 'home',
          target: new THREE.Vector3(), wob: Math.random() * 6.28,
          dockA, dockR,
          scale: 0.62 + Math.random() * 0.4, hero: false, cargo: 0,
          role: ['Forager', 'Forager', 'Scout', 'Worker'][i % 4]
        };
        pickTarget(ant);
        A.list.push(ant);
      }
      mesh.geometry.setAttribute('aInst', new THREE.InstancedBufferAttribute(inst, 2));
      scene.add(mesh);
      A.meshes.push(mesh);
      A.byMesh[mesh.uuid] = ci;
      col._antMesh = mesh;
    });

    // ---- hero (named) ants ----
    const greek = ['Δ', 'Σ', 'Ω', 'Φ', 'Ψ', 'Θ'];
    const roles = ['Forecaster', 'Scout', 'Forecaster', 'Debater', 'Treasurer', 'Archivist'];
    const heroPool = [];
    for (let h = 0; h < 6; h++) {
      const col = colonies[h % colonies.length];
      const ant = A.list.filter(a => a.col === col && !a.hero)[h < colonies.length ? 0 : 1];
      if (!ant) continue;
      ant.hero = true;
      ant.scale = 1.15;
      ant.role = roles[h];
      ant.name = roles[h].slice(0, 1) + 'gent ' + greek[h] + '-' + String(7 + h * 13).padStart(2, '0');
      ant.accuracy = 58 + Math.round(Math.random() * 34);
      ant.reputation = 40 + Math.round(Math.random() * 55);
      ant.staked = (40 + Math.random() * 220).toFixed(1);
      ant.age = 1 + Math.round(Math.random() * 24);
      ant.gen = 1 + Math.round(Math.random() * 5);
      // glow + pick target follow this ant
      const glow = new THREE.Sprite(new THREE.SpriteMaterial({
        map: DN.util.softSprite(), color: col.accent, transparent: true, opacity: 0.6,
        depthWrite: false, blending: THREE.AdditiveBlending
      }));
      glow.scale.set(5, 5, 1);
      scene.add(glow);
      const pick = new THREE.Mesh(new THREE.SphereGeometry(2.2, 10, 10), new THREE.MeshBasicMaterial({ visible: false }));
      pick.userData.ant = ant;
      scene.add(pick);
      ant.glow = glow; ant.pickTarget = pick;
      A.heroes.push(ant);
    }

    // ---- carried cargo (instanced little crystals above carrying ants) ----
    const cb = new DN.util.VoxelBuilder();
    cb.box([0.4, 0.4, 0.4], [0, 0, 0], 0xE8C24A);
    const cargoMesh = new THREE.InstancedMesh(cb.geometry(), DN.util.voxelMat({ roughness: 0.35 }), A.list.length);
    cargoMesh.frustumCulled = false; cargoMesh.castShadow = false;
    scene.add(cargoMesh);
    A.cargoMesh = cargoMesh;

    return A;
  };

  function pickTarget(a) {
    if (a.state === 'out') {
      const res = DN.resources && DN.resources.nearest(a.col.pos);
      if (res) { a.target.set(res.pos.x + (Math.random() - .5) * 4, 0, res.pos.z + (Math.random() - .5) * 4); a._res = res; }
      else {
        const ang = Math.random() * 6.28, rr = 22 + Math.random() * 34;
        a.target.set(a.col.pos.x + Math.cos(ang) * rr, 0, a.col.pos.z + Math.sin(ang) * rr);
        a._res = null;
      }
    } else {
      const e = a.col.entrance || a.col.pos;
      a.target.set(e.x + Math.cos(a.dockA) * a.dockR, 0, e.z + Math.sin(a.dockA) * a.dockR);
    }
  }

  A.update = function (dt, elapsed, timeScale) {
    if (A.material.userData.sh) A.material.userData.sh.uniforms.uTime.value = elapsed;
    let cargoN = 0;
    const meshDirty = {};
    for (let k = 0; k < A.list.length; k++) {
      const a = A.list[k];
      let dx = a.target.x - a.x, dz = a.target.z - a.z;
      let dist = Math.hypot(dx, dz) || 0.001;
      if (dist < 2.6) {
        if (a.state === 'out') {
          if (a._res && !a._res.depleted) { a._res.amount -= 0.06 * timeScale; a.cargo = 1; }
          a.state = 'home';
        } else {
          if (a.cargo) { a.col.stats.food = Math.min(100, a.col.stats.food + 0.04); a.cargo = 0; }
          a.state = 'out';
        }
        pickTarget(a);
        dx = a.target.x - a.x; dz = a.target.z - a.z; dist = Math.hypot(dx, dz) || 0.001;
      }
      // steering: toward target + curl wander
      const inv = 1 / dist; let sx = dx * inv, sz = dz * inv;
      const w = noise.n3(a.x * 0.05, a.z * 0.05, elapsed * 0.3 + a.wob);
      const wa = w * Math.PI * 2, mix = 0.34;
      sx = sx * (1 - mix) + Math.cos(wa) * mix; sz = sz * (1 - mix) + Math.sin(wa) * mix;
      const sl = Math.hypot(sx, sz) || 1; sx /= sl; sz /= sl;
      const sp = a.speed * timeScale;
      a.x += sx * sp * dt; a.z += sz * sp * dt;
      const ty = Math.atan2(sx, sz);
      let d = ty - a.yaw; while (d > Math.PI) d -= 6.283; while (d < -Math.PI) d += 6.283;
      a.yaw += d * Math.min(1, dt * 8);
      const gy = ground(a.x, a.z);
      _p.set(a.x, gy + 0.05, a.z);
      _e.set(0, a.yaw, 0); _q.setFromEuler(_e);
      _s.setScalar(a.scale);
      _m.compose(_p, _q, _s);
      a.mesh.setMatrixAt(a.inst, _m);
      meshDirty[a.mesh.uuid] = a.mesh;
      // cargo crystal
      if (a.cargo && !a.hero) {
        _p.set(a.x, gy + 0.05 + 0.7 * a.scale, a.z);
        _m.compose(_p, _q, _s);
        A.cargoMesh.setMatrixAt(cargoN++, _m);
      }
      // hero glow + pick follow
      if (a.hero) {
        a.glow.position.set(a.x, gy + 0.9, a.z);
        a.glow.material.opacity = a.selected ? 0.85 : 0.45 + Math.sin(elapsed * 3 + a.wob) * 0.12;
        a.glow.scale.setScalar(a.selected ? 4.5 : 3);
        a.pickTarget.position.set(a.x, gy + 1, a.z);
        a.wx = a.x; a.wy = gy; a.wz = a.z;
      }
    }
    for (const id in meshDirty) meshDirty[id].instanceMatrix.needsUpdate = true;
    A.cargoMesh.count = cargoN;
    A.cargoMesh.instanceMatrix.needsUpdate = true;
  };

  // resolve an instanced raycast hit into an ant object
  A.antFromHit = function (mesh, instanceId) {
    const ci = A.byMesh[mesh.uuid];
    if (ci === undefined) return null;
    return A.list.find(a => a.ci === ci && a.inst === instanceId) || null;
  };
  A.heroPos = function (a) { return new THREE.Vector3(a.wx || a.x, (a.wy || ground(a.x, a.z)) + 1, a.wz || a.z); };

  return A;
})();
