// WorldColony — surface colonies: voxel mounds + tunnel entrances, faction identity, stats
window.DN = window.DN || {};

DN.colony = (function () {
  const C = { list: [] };
  let scene, group;
  const P = DN.palette;
  function ground(x, z) { return DN.world.heightAt(x, z); }

  // Seven colonies spread evenly around the play area so the player
  // always sees a few from any orbit angle. Distances vary so they don't
  // form a perfect circle.
  const DEFS = [
    { angle: -0.6, dist: 76 },
    { angle: 0.7,  dist: 118 },
    { angle: 1.8,  dist: 92 },
    { angle: 2.9,  dist: 130 },
    { angle: 3.9,  dist: 84 },
    { angle: 4.9,  dist: 120 },
    { angle: 5.9,  dist: 96 }
  ];

  function buildMound(accent, seed) {
    const b = new DN.util.VoxelBuilder();
    const rng = (function (a) { return function () { a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; })(seed);
    // stacked tapering rings of dirt blocks -> rounded mound
    const layers = 6;
    for (let l = 0; l < layers; l++) {
      const t = l / layers;
      const R = 7.5 * (1 - t * 0.85);
      const y = l * 1.0;
      const blocks = Math.max(4, Math.round(R * 2.4));
      for (let i = 0; i < blocks; i++) {
        const a = (i / blocks) * 6.28 + l * 0.4;
        const rr = R + (rng() - 0.5) * 0.8;
        const bx = Math.cos(a) * rr, bz = Math.sin(a) * rr;
        const s = 1.5 + rng() * 0.8;
        b.box([s, 1.3, s], [bx, y + 0.5, bz], rng() < 0.3 ? P.dirtDark : P.dirt);
      }
    }
    // crater rim cap
    b.box([3.2, 1.0, 3.2], [0, layers * 1.0, 0], P.dirtDark);
    // dark entrance throat (front, +z)
    b.box([2.6, 2.4, 2.6], [0, 1.0, 7.2], 0x140d07);
    b.box([3.4, 0.8, 1.6], [0, 0.4, 8.0], P.dirtDark);
    return b.geometry();
  }

  // Build a single colony at (angle, dist) and register it. Returns the
  // colony object (already pushed onto C.list). Pulled out of C.init so
  // founding new colonies post-startup can reuse this codepath.
  C._buildOne = function (angle, dist, idx, accent, name) {
    const cx = Math.cos(angle) * dist;
    const cz = Math.sin(angle) * dist;
    const cy = ground(cx, cz);
    const g = new THREE.Group();
    g.position.set(cx, cy, cz);
    g.rotation.y = angle + Math.PI;
    const yaw = g.rotation.y;

    const mound = new THREE.Mesh(buildMound(accent, 50 + idx), DN.util.voxelMat({ roughness: 1.0 }));
    mound.castShadow = true; mound.receiveShadow = true;
    g.add(mound);

    // accent crystal marker on the crater
    const cb = new DN.util.VoxelBuilder();
    cb.box([0.9, 2.2, 0.9], [0, 0, 0], accent);
    cb.box([0.5, 1.0, 0.5], [0, 1.4, 0], accent);
    const markerMat = DN.util.voxelMat({ roughness: 0.3, emissive: new THREE.Color(accent), emissiveIntensity: 0.25 });
    markerMat.transparent = true;
    const marker = new THREE.Mesh(cb.geometry(), markerMat);
    marker.position.set(0, 7.4, 0);
    g.add(marker);
    const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: DN.util.softSprite(), color: accent, transparent: true, opacity: 0.4, depthWrite: false, blending: THREE.AdditiveBlending }));
    glow.scale.set(10, 10, 1); glow.position.set(0, 8, 0);
    g.add(glow);

    // ground footprint ring (accent), grows when selected
    const ringGeo = new THREE.RingGeometry(9, 10.4, 56);
    ringGeo.rotateX(-Math.PI / 2);
    const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: accent, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }));
    ring.position.y = 0.4;
    g.add(ring);

    group.add(g);

    const ex = cx + Math.sin(yaw) * 7.5, ez = cz + Math.cos(yaw) * 7.5;
    const entrance = new THREE.Vector3(ex, ground(ex, ez), ez);

    const pick = new THREE.Mesh(new THREE.SphereGeometry(9, 16, 12), new THREE.MeshBasicMaterial({ visible: false }));
    pick.position.set(cx, cy + 4, cz);
    scene.add(pick);

    const col = {
      id: 'col-' + idx, idx, name, accent,
      pos: new THREE.Vector3(cx, cy, cz),
      corePos: new THREE.Vector3(cx, cy + 7, cz),
      entrance,
      group: g, mound, marker, glow, ring, pickTarget: pick,
      directive: 'forage', selected: false, _t: Math.random() * 6,
      stats: {
        population: 180 + Math.round(Math.random() * 220),
        health: 70 + Math.round(Math.random() * 24),
        food: 45 + Math.round(Math.random() * 40),
        accuracy: 56 + Math.round(Math.random() * 32),
        staked: (180 + Math.random() * 900),
        rep: 50 + Math.round(Math.random() * 45),
        gen: 1
      }
    };
    pick.userData.colony = col;
    mound.userData.colony = col;
    C.list.push(col);
    return col;
  };

  C.init = function (sceneRef) {
    scene = sceneRef;
    group = new THREE.Group();
    scene.add(group);

    DEFS.forEach((def, idx) => {
      const accent = P.factions[idx];
      const name = P.factionNames[idx];
      C._buildOne(def.angle, def.dist, idx, accent, name);
    });

    // Auto-founding disabled for now — re-enable by uncommenting below.
    // scheduleNextFounding();

    return C;
  };

  function scheduleNextFounding() {
    setTimeout(() => {
      let col = null;
      try { col = C.foundColony({}); } catch (_) {}
      // Fly the camera over the new colony so the founding animation
      // happens centre-frame instead of off-screen somewhere.
      if (col && DN.camera && DN.camera.flyTo && DN.app && DN.app.view === 'surface') {
        // Higher + further so canopy trees in the foreground can't block
        // the rising mound mid-animation.
        DN.camera.flyTo(col.pos, 56, 44, 2.0);
      }
      scheduleNextFounding();
    }, 15000);
  }

  // ---- Founding a NEW colony with a cinematic animation. -------------
  // Mound rises from flat → tall, marker materialises with a glow burst,
  // a shockwave ring pulses outward, then the colony's foragers start
  // emerging. Pass {} to randomly place the founding in a clear spot.
  C.foundColony = function (opts) {
    opts = opts || {};
    const idx = C.list.length;
    if (idx >= 14) return null; // hard cap so the world doesn't fill forever
    const accent = opts.accent != null ? opts.accent : P.factions[idx % P.factions.length];
    const factionName = opts.name || (P.factionNames[idx % P.factionNames.length] + ' II');

    // pick a clear (angle, dist) — at least 60 units from existing colonies
    let angle = opts.angle, dist = opts.dist;
    if (angle == null || dist == null) {
      for (let tries = 0; tries < 40; tries++) {
        const ta = Math.random() * Math.PI * 2;
        const td = 70 + Math.random() * 70;
        const tx = Math.cos(ta) * td, tz = Math.sin(ta) * td;
        let clear = true;
        for (const c of C.list) {
          if (Math.hypot(c.pos.x - tx, c.pos.z - tz) < 60) { clear = false; break; }
        }
        if (clear) { angle = ta; dist = td; break; }
      }
      if (angle == null) return null;
    }
    const col = C._buildOne(angle, dist, idx, accent, factionName);

    if (DN.logTerm) DN.logTerm.push('FOUND', 'Colony "' + factionName + '" founded.');

    // Founder colony: the nearest existing colony whose workers will
    // migrate over to seed the new mound. Without this the new ants
    // would just spawn at the entrance, which feels static.
    let parent = null, pd = Infinity;
    for (const c of C.list) {
      if (c === col) continue;
      const d = c.pos.distanceTo(col.pos);
      if (d < pd) { pd = d; parent = c; }
    }
    col._parent = parent;

    // Clear surrounding trees + rocks + ground cover so the new mound
    // isn't buried in forest. Generous radius so the camera flight in
    // never lands a frame with a tree blocking the mound.
    if (DN.flora && DN.flora.clearAround) {
      DN.flora.clearAround(col.pos.x, col.pos.z, 48);
    }

    // Hide / pre-set everything for the animation.
    col.mound.scale.set(0.5, 0.001, 0.5);
    col.marker.material.opacity = 0;
    col.marker.scale.setScalar(0.01);
    col.marker.material.emissiveIntensity = 0;
    col.glow.material.opacity = 0;
    col.ring.material.opacity = 0;

    // Shockwave ring (separate from the footprint ring so it animates
    // independently). Lives on the colony group and is removed when the
    // animation finishes.
    const swGeo = new THREE.RingGeometry(2, 2.4, 64);
    swGeo.rotateX(-Math.PI / 2);
    const sw = new THREE.Mesh(swGeo, new THREE.MeshBasicMaterial({
      color: accent, transparent: true, opacity: 0.0, side: THREE.DoubleSide,
      depthWrite: false, blending: THREE.AdditiveBlending
    }));
    sw.position.y = 0.45;
    col.group.add(sw);

    // Dust burst — a temporary Points cloud puffing outward from the
    // mound centre. Particles fall back to ground over ~3s.
    const N = 40;
    const dustPos = new Float32Array(N * 3);
    const dustVel = [];
    for (let i = 0; i < N; i++) {
      dustPos[i * 3] = 0; dustPos[i * 3 + 1] = 1; dustPos[i * 3 + 2] = 0;
      const a = Math.random() * Math.PI * 2;
      const r = 2 + Math.random() * 4;
      dustVel.push({ vx: Math.cos(a) * r, vy: 5 + Math.random() * 4, vz: Math.sin(a) * r, age: Math.random() * 0.4 });
    }
    const dustGeo = new THREE.BufferGeometry();
    dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
    const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({
      size: 1.4, map: DN.util.softSprite(), color: 0xA8845A,
      transparent: true, opacity: 0.95, depthWrite: false
    }));
    dust.frustumCulled = false;
    col.group.add(dust);

    col._foundAnim = { t: 0, sw, dust, dustVel, antsSpawned: false };

    // Kick the migration off RIGHT NOW so the founder column is already
    // marching across the field while the mound rises. By the time the
    // animation completes, the lead ants are arriving at the new entrance.
    if (DN.ants && DN.ants.addColony) {
      DN.ants.addColony(col, parent);
      col._foundAnim.antsSpawned = true;
      if (DN.logTerm && parent) {
        DN.logTerm.push('MIGRATE', 'Founder column dispatched from ' + parent.name + ' → ' + factionName + '.');
      }
    }
    return col;
  };

  C.update = function (dt, elapsed) {
    C.list.forEach(c => {
      c._t += dt;

      // ---- founding animation ---------------------------------------
      if (c._foundAnim) {
        const an = c._foundAnim;
        an.t += dt;
        const T = an.t;
        // Phase 0 (0–0.8s): site glow + dust puff
        // Phase 1 (0.8–3.8s): mound rises with eased growth
        // Phase 2 (3.8–5.0s): crystal materialises with marker glow burst
        // Phase 3 (5.0–6.5s): shockwave ring expands and fades
        // Done (6.5s+): finalise + spawn ants
        if (T < 0.8) {
          const p = T / 0.8;
          c.glow.material.opacity = p * 0.55;
        } else if (T < 3.8) {
          const p = (T - 0.8) / 3.0;
          const e = 1 - Math.pow(1 - p, 3); // ease-out cubic
          c.mound.scale.y = 0.001 + e * 0.999;
          c.mound.scale.x = 0.5 + e * 0.5;
          c.mound.scale.z = 0.5 + e * 0.5;
          c.glow.material.opacity = 0.55 + Math.sin(T * 5) * 0.08;
        } else if (T < 5.0) {
          c.mound.scale.set(1, 1, 1);
          const p = (T - 3.8) / 1.2;
          const e = Math.sin(p * Math.PI * 0.5); // ease-out sine
          c.marker.scale.setScalar(e);
          c.marker.material.opacity = e;
          c.marker.material.emissiveIntensity = 0.25 + (1 - p) * 1.2; // bright pop then settle
          c.glow.material.opacity = 0.55 + (1 - p) * 0.35;
        } else if (T < 6.5) {
          const p = (T - 5.0) / 1.5;
          // shockwave expands outward
          const s = 1 + p * 8;
          an.sw.scale.set(s, 1, s);
          an.sw.material.opacity = (1 - p) * 0.9;
          c.marker.material.emissiveIntensity = 0.25 + (1 - p) * 0.4;
        } else {
          // finalise
          c.mound.scale.set(1, 1, 1);
          c.marker.scale.setScalar(1);
          c.marker.material.opacity = 1;
          c.marker.material.emissiveIntensity = 0.25;
          if (an.sw) { c.group.remove(an.sw); an.sw.geometry.dispose(); an.sw.material.dispose(); }
          if (an.dust) { c.group.remove(an.dust); an.dust.geometry.dispose(); an.dust.material.dispose(); }
          // ants already spawned at the start of founding (see foundColony)
          c._foundAnim = null;
        }
        // dust particle physics: outward + up, gravity pull, fade
        if (an.dust) {
          const arr = an.dust.geometry.attributes.position.array;
          for (let i = 0; i < an.dustVel.length; i++) {
            const v = an.dustVel[i];
            v.age = (v.age || 0) + dt;
            arr[i * 3] += v.vx * dt;
            arr[i * 3 + 1] += v.vy * dt;
            arr[i * 3 + 2] += v.vz * dt;
            v.vy -= 16 * dt; // gravity
            // slight drag
            v.vx *= 0.96; v.vz *= 0.96;
          }
          an.dust.geometry.attributes.position.needsUpdate = true;
          an.dust.material.opacity = Math.max(0, 0.95 * (1 - T / 3.5));
        }
        return; // skip normal pulses while founding
      }

      // ---- normal idle pulses ---------------------------------------
      c.glow.material.opacity = (c.selected ? 0.55 : 0.34) + Math.sin(c._t * 1.4) * 0.06;
      c.marker.material.emissiveIntensity = 0.25 + Math.sin(c._t * 2) * 0.12;
      if (c.selected) {
        c.ring.material.opacity = Math.min(0.55, c.ring.material.opacity + dt * 1.6);
        c.ring.rotation.y += dt * 0.4;
      } else c.ring.material.opacity = Math.max(0, c.ring.material.opacity - dt * 2);
    });
  };

  return C;
})();
