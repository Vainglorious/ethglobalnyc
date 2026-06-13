// Di-nasty — surface colonies: voxel mounds + tunnel entrances, faction identity, stats
window.DN = window.DN || {};

DN.colony = (function () {
  const C = { list: [] };
  let scene, group;
  const P = DN.palette;
  function ground(x, z) { return DN.world.heightAt(x, z); }

  const DEFS = [
    { angle: -0.6, dist: 72 },
    { angle: 2.0, dist: 100 },
    { angle: 3.5, dist: 82 },
    { angle: 5.0, dist: 112 }
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

  C.init = function (sceneRef) {
    scene = sceneRef;
    group = new THREE.Group();
    scene.add(group);

    DEFS.forEach((def, idx) => {
      const cx = Math.cos(def.angle) * def.dist;
      const cz = Math.sin(def.angle) * def.dist;
      const cy = ground(cx, cz);
      const accent = P.factions[idx];
      const g = new THREE.Group();
      g.position.set(cx, cy, cz);
      g.rotation.y = def.angle + Math.PI; // entrance faces outward-ish
      const yaw = g.rotation.y;

      const mound = new THREE.Mesh(buildMound(accent, 50 + idx), DN.util.voxelMat({ roughness: 1.0 }));
      mound.castShadow = true; mound.receiveShadow = true;
      g.add(mound);

      // accent crystal marker on the crater
      const cb = new DN.util.VoxelBuilder();
      cb.box([0.9, 2.2, 0.9], [0, 0, 0], accent);
      cb.box([0.5, 1.0, 0.5], [0, 1.4, 0], accent);
      const marker = new THREE.Mesh(cb.geometry(), DN.util.voxelMat({ roughness: 0.3, emissive: new THREE.Color(accent), emissiveIntensity: 0.25 }));
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

      // entrance world position (front of mound, +z in local rotated by yaw)
      const ex = cx + Math.sin(yaw) * 7.5, ez = cz + Math.cos(yaw) * 7.5;
      const entrance = new THREE.Vector3(ex, ground(ex, ez), ez);

      // pick target over the mound
      const pick = new THREE.Mesh(new THREE.SphereGeometry(9, 16, 12), new THREE.MeshBasicMaterial({ visible: false }));
      pick.position.set(cx, cy + 4, cz);
      scene.add(pick);

      const col = {
        id: 'col-' + idx, idx, name: P.factionNames[idx], accent,
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
    });

    return C;
  };

  C.update = function (dt, elapsed) {
    C.list.forEach(c => {
      c._t += dt;
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
