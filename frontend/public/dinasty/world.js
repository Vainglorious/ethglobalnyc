// Di-nasty — world: renderer, gradient sky, sunlight, fog, voxel terrain, water, atmosphere
window.DN = window.DN || {};

DN.world = (function () {
  const W = {};
  const SIZE = 880;
  const SEG = 320;
  const AMP = 34;
  const SCALE = 0.009;
  // Skirt plane parameters — a vast flat ground extending to the horizon
  // so the finite terrain never reveals the sky/void at its edges.
  const SKIRT_SIZE = 6000;
  const SKIRT_Y = -1.6;
  // Edge falloff thresholds (radius from world center) where the detailed
  // terrain smoothly melts down to the skirt level.
  const EDGE_START = SIZE * 0.34;
  const EDGE_END = SIZE * 0.49;
  let noise, fireflies, dust, cn;

  // ---- shared height field (metres-ish units) ----
  function heightAt(x, z) {
    const n = noise.fbm2(x * SCALE, z * SCALE, 5, 2.0, 0.5); // ~ -1..1
    let h = (n * 0.5 + 0.2) * AMP;
    // gentle terracing -> voxel feel
    const step = 2.2;
    h = h * 0.7 + (Math.round(h / step) * step) * 0.3;
    // flatten a central clearing so colonies + trails read clearly
    const r = Math.sqrt(x * x + z * z);
    const clearing = Math.max(0, 1 - r / 165);
    h *= 1 - clearing * clearing * 0.72;
    // a meandering shallow streambed
    const stream = Math.abs(Math.sin(x * 0.018 + Math.cos(z * 0.012) * 1.6) + z * 0.004);
    if (stream < 0.16) h -= (0.16 - stream) * 18;
    // edge falloff — smoothly drop to the surrounding skirt so the boundary
    // is invisible from any camera angle.
    const edgeR = Math.max(Math.abs(x), Math.abs(z));
    if (edgeR > EDGE_START) {
      const t = Math.min(1, (edgeR - EDGE_START) / (EDGE_END - EDGE_START));
      const smooth = t * t * (3 - 2 * t);
      h = h * (1 - smooth) + SKIRT_Y * smooth;
    }
    return h;
  }
  W.heightAt = heightAt;
  W.WATER_LEVEL = -3.2;

  function makeSky(scene) {
    const geo = new THREE.SphereGeometry(4800, 64, 40);
    const mat = new THREE.ShaderMaterial({
      side: THREE.BackSide, depthWrite: false, fog: false,
      uniforms: {
        top: { value: new THREE.Color(DN.palette.skyTop) },
        mid: { value: new THREE.Color(DN.palette.skyMid) },
        bot: { value: new THREE.Color(DN.palette.horizon) },
        sunCol: { value: new THREE.Color(DN.palette.sun) },
        sunDir: { value: new THREE.Vector3(-0.5, 0.5, 0.4).normalize() }
      },
      vertexShader: `varying vec3 vDir; void main(){ vDir = normalize(position); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);}`,
      fragmentShader: `
        varying vec3 vDir; uniform vec3 top,mid,bot,sunCol,sunDir;
        void main(){
          float h = normalize(vDir).y;
          vec3 col = mix(bot, top, clamp(h*0.55+0.4, 0.0, 1.0));
          col = mix(col, mid, pow(1.0 - clamp(abs(h*1.4),0.0,1.0), 3.0)*0.6);
          float s = max(dot(normalize(vDir), normalize(sunDir)), 0.0);
          col += sunCol * (pow(s, 480.0)*0.7 + pow(s, 9.0)*0.14);
          gl_FragColor = vec4(col, 1.0);
        }`
    });
    const sky = new THREE.Mesh(geo, mat);
    sky.frustumCulled = false;
    scene.add(sky);
    W.skyMat = mat;
  }

  W.init = function (canvas) {
    noise = new DNNoise(11);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(DN.palette.horizon);
    // No fog. The green horizon/background (palette.horizon + biome bg/sky.bot)
    // keeps the surround green so the finite terrain never reveals a white void.
    scene.fog = null;

    const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.1, 8000);
    camera.position.set(40, 14, 70);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(innerWidth, innerHeight);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputEncoding = THREE.LinearEncoding;
    renderer.toneMapping = THREE.NoToneMapping;

    makeSky(scene);

    // ---- lighting: warm directional sun + sky hemi ----
    const hemi = new THREE.HemisphereLight(0xDCEBFF, 0x4A5A28, 0.45);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xFFEFC8, 1.5);
    sun.position.set(-110, 150, 80);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.near = 20;
    sun.shadow.camera.far = 620;
    const sc = 260;
    sun.shadow.camera.left = -sc; sun.shadow.camera.right = sc;
    sun.shadow.camera.top = sc; sun.shadow.camera.bottom = -sc;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.6;
    scene.add(sun);
    scene.add(sun.target);
    const amb = new THREE.AmbientLight(0xffffff, 0.16);
    scene.add(amb);

    // ---- terrain ----
    const geo = new THREE.PlaneGeometry(SIZE, SIZE, SEG, SEG);
    geo.rotateX(-Math.PI / 2);
    const pos = geo.attributes.position;
    cn = new DNNoise(91);
    for (let i = 0; i < pos.count; i++) {
      pos.setY(i, heightAt(pos.getX(i), pos.getZ(i)));
    }
    geo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(pos.count * 3), 3));
    geo.computeVertexNormals();
    const terrain = new THREE.Mesh(geo, DN.util.voxelMat({ flatShading: false, roughness: 0.97 }));
    terrain.receiveShadow = true;
    terrain.name = 'terrain';
    scene.add(terrain);
    W.terrain = terrain;
    W.biome = DN.biomes[0];
    W.recolorTerrain(W.biome.ground);

    // ---- infinite ground skirt: huge plane that extends to the horizon ----
    // Slightly below the terrain edge so the falloff blends seamlessly.
    // Vertex-colored with subtle low-frequency tonal variation so it doesn't
    // read as a sterile flat plane in the distance.
    const skirtGeo = new THREE.PlaneGeometry(SKIRT_SIZE, SKIRT_SIZE, 96, 96);
    skirtGeo.rotateX(-Math.PI / 2);
    const skirtPos = skirtGeo.attributes.position;
    const skirtColors = new Float32Array(skirtPos.count * 3);
    skirtGeo.setAttribute('color', new THREE.BufferAttribute(skirtColors, 3));
    // Subtle rolling undulation only well outside the terrain footprint so
    // the inner ring stays perfectly flat against the terrain falloff.
    const innerFlat = SIZE * 0.55;
    for (let i = 0; i < skirtPos.count; i++) {
      const x = skirtPos.getX(i), z = skirtPos.getZ(i);
      const r = Math.max(Math.abs(x), Math.abs(z));
      if (r > innerFlat) {
        const k = Math.min(1, (r - innerFlat) / (SKIRT_SIZE * 0.25));
        const undulation = noise.fbm2(x * 0.0025, z * 0.0025, 3, 2.0, 0.5);
        skirtPos.setY(i, undulation * 9 * k);
      }
    }
    skirtGeo.computeVertexNormals();
    const skirt = new THREE.Mesh(
      skirtGeo,
      DN.util.voxelMat({ flatShading: false, roughness: 0.98 })
    );
    skirt.position.y = SKIRT_Y;
    skirt.receiveShadow = true;
    skirt.name = 'skirt';
    // Render slightly before terrain so terrain sits on top where they overlap.
    skirt.renderOrder = -1;
    scene.add(skirt);
    W.skirt = skirt;
    W.recolorSkirt(W.biome.ground);

    // ---- water plane along the streambed / basin ----
    // Sized to inner terrain so water only shows where the streambed dips
    // below WATER_LEVEL — the skirt sits above water level out at the horizon.
    const waterGeo = new THREE.PlaneGeometry(SIZE, SIZE, 1, 1);
    waterGeo.rotateX(-Math.PI / 2);
    const waterMat = new THREE.MeshStandardMaterial({
      color: DN.palette.water, transparent: true, opacity: 0.78,
      roughness: 0.18, metalness: 0.0
    });
    const water = new THREE.Mesh(waterGeo, waterMat);
    water.position.y = W.WATER_LEVEL;
    water.receiveShadow = false;
    scene.add(water);

    // ---- atmospheric dust motes (sunbeam sparkle) ----
    const dn = 240;
    const dpos = new Float32Array(dn * 3), dph = new Float32Array(dn);
    for (let i = 0; i < dn; i++) {
      dpos[i * 3] = (Math.random() - 0.5) * SIZE;
      dpos[i * 3 + 1] = 9 + Math.random() * 48;
      dpos[i * 3 + 2] = (Math.random() - 0.5) * SIZE;
      dph[i] = Math.random() * 6.28;
    }
    const dgeo = new THREE.BufferGeometry();
    dgeo.setAttribute('position', new THREE.BufferAttribute(dpos, 3));
    dust = new THREE.Points(dgeo, new THREE.PointsMaterial({
      size: 0.45, map: DN.util.softSprite(), color: 0xFFFBEF,
      transparent: true, opacity: 0.22, depthWrite: false, sizeAttenuation: true
    }));
    dust.frustumCulled = false;
    scene.add(dust);
    W._dust = { pts: dust, base: dpos.slice(), ph: dph };

    // ---- fireflies (warm glowing motes near ground) ----
    const fn = 90;
    const fpos = new Float32Array(fn * 3), fph = new Float32Array(fn);
    for (let i = 0; i < fn; i++) {
      const a = Math.random() * 6.28, r = 30 + Math.random() * 120;
      const x = Math.cos(a) * r, z = Math.sin(a) * r;
      fpos[i * 3] = x; fpos[i * 3 + 1] = heightAt(x, z) + 2 + Math.random() * 6; fpos[i * 3 + 2] = z;
      fph[i] = Math.random() * 6.28;
    }
    const fgeo = new THREE.BufferGeometry();
    fgeo.setAttribute('position', new THREE.BufferAttribute(fpos, 3));
    fireflies = new THREE.Points(fgeo, new THREE.PointsMaterial({
      size: 1.5, map: DN.util.softSprite(), color: 0xFFE9A0,
      transparent: true, opacity: 0.0, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
    }));
    fireflies.frustumCulled = false;
    scene.add(fireflies);
    W._fire = { pts: fireflies, base: fpos.slice(), ph: fph };

    W.scene = scene; W.camera = camera; W.renderer = renderer;
    W.terrain = terrain; W.sun = sun; W.water = water; W.hemi = hemi; W.amb = amb;
    W.SIZE = SIZE;

    addEventListener('resize', function () {
      camera.aspect = innerWidth / innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(innerWidth, innerHeight);
    });
    return W;
  };

  W.update = function (dt, elapsed) {
    const d = W._dust;
    if (d) {
      const p = d.pts.geometry.attributes.position;
      for (let i = 0; i < d.ph.length; i++) {
        const ph = d.ph[i];
        p.array[i * 3] = d.base[i * 3] + Math.sin(elapsed * 0.1 + ph) * 5;
        p.array[i * 3 + 1] = d.base[i * 3 + 1] + Math.sin(elapsed * 0.16 + ph * 1.7) * 2.4;
        p.array[i * 3 + 2] = d.base[i * 3 + 2] + Math.cos(elapsed * 0.09 + ph) * 5;
      }
      p.needsUpdate = true;
    }
    const f = W._fire;
    if (f) {
      const p = f.pts.geometry.attributes.position;
      for (let i = 0; i < f.ph.length; i++) {
        const ph = f.ph[i];
        p.array[i * 3] = f.base[i * 3] + Math.sin(elapsed * 0.5 + ph) * 3;
        p.array[i * 3 + 1] = f.base[i * 3 + 1] + Math.sin(elapsed * 0.7 + ph * 2.1) * 1.6;
        p.array[i * 3 + 2] = f.base[i * 3 + 2] + Math.cos(elapsed * 0.45 + ph) * 3;
      }
      p.needsUpdate = true;
      // twinkle, stronger at dusk/night
      const night = W._night || 0;
      f.pts.material.opacity = (0.25 + Math.sin(elapsed * 2) * 0.1) * (0.2 + night * 0.9);
    }
    if (W.water) W.water.material.opacity = 0.74 + Math.sin(elapsed * 0.6) * 0.04;
  };

  // time-of-day 0..1 (0 dawn, .5 midday, 1 dusk->night)
  W.setDaylight = function (t) {
    const b = W.biome || DN.biomes[0];
    const day = Math.sin(t * Math.PI); // 0 ends, 1 midday
    const night = Math.max(0, 1 - day * 1.4);
    W._night = night;
    if (W.sun) {
      W.sun.intensity = (0.36 + day * 1.0) * (b.sunBias || 1);
      const warm = new THREE.Color(0xFFD9A0).lerp(new THREE.Color(b.sky.sun), day);
      W.sun.color.copy(warm);
      const ang = 0.15 + t * (Math.PI - 0.3);
      W.sun.position.set(Math.cos(ang) * 150, 30 + day * 150, 80);
      if (W.skyMat) W.skyMat.uniforms.sunDir.value.copy(W.sun.position).normalize();
    }
    if (W.hemi) W.hemi.intensity = 0.26 + day * 0.26;
    if (W.amb) W.amb.intensity = (b.amb || 0.16);
    if (W.skyMat) {
      const duskTop = new THREE.Color(b.sky.top).lerp(new THREE.Color(0x2A3458), night * 0.6);
      const duskBot = new THREE.Color(b.sky.bot).lerp(new THREE.Color(0xE8A368), Math.max(0, Math.sin((t - 0.5) * Math.PI)) * 0.45);
      W.skyMat.uniforms.top.value.copy(duskTop);
      W.skyMat.uniforms.mid.value.set(b.sky.mid);
      W.skyMat.uniforms.bot.value.copy(duskBot);
      W.skyMat.uniforms.sunCol.value.set(b.sky.sun);
    }
  };

  // recolor the infinite ground skirt vertices to match the biome
  W.recolorSkirt = function (ground) {
    if (!W.skirt) return;
    const geo = W.skirt.geometry, pos = geo.attributes.position, colAttr = geo.attributes.color;
    const cGrass = new THREE.Color(ground.grass);
    const cGrassD = new THREE.Color(ground.grassDark);
    const cGrassL = new THREE.Color(ground.grassLight);
    const tmp = new THREE.Color();
    const tintN = cn || new DNNoise(91);
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), z = pos.getZ(i);
      const tint = tintN.n2(x * 0.012, z * 0.012) * 0.5 + 0.5;
      const dark = tintN.n2(x * 0.004 + 7.1, z * 0.004 - 3.3) * 0.5 + 0.5;
      tmp.copy(cGrass).lerp(cGrassL, tint * 0.55);
      tmp.lerp(cGrassD, dark * 0.35);
      colAttr.setXYZ(i, tmp.r, tmp.g, tmp.b);
    }
    colAttr.needsUpdate = true;
  };

  // recolor terrain vertices to a biome ground palette
  W.recolorTerrain = function (ground) {
    const geo = W.terrain.geometry, pos = geo.attributes.position, colAttr = geo.attributes.color;
    const cGrass = new THREE.Color(ground.grass), cGrassD = new THREE.Color(ground.grassDark), cGrassL = new THREE.Color(ground.grassLight), cDirt = new THREE.Color(ground.dirt), cSand = new THREE.Color(ground.sand), tmp = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const x = pos.getX(i), z = pos.getZ(i), h = pos.getY(i);
      const hx = heightAt(x + 1.5, z) - heightAt(x - 1.5, z), hz = heightAt(x, z + 1.5) - heightAt(x, z - 1.5);
      const slope = Math.min(1, Math.hypot(hx, hz) / 5);
      const tint = cn.n2(x * 0.05, z * 0.05) * 0.5 + 0.5;
      tmp.copy(cGrass).lerp(cGrassL, tint * 0.6); tmp.lerp(cGrassD, slope * 0.5);
      if (h < W.WATER_LEVEL + 1.6) tmp.lerp(cSand, Math.min(1, (W.WATER_LEVEL + 1.6 - h) / 2.2));
      else if (slope > 0.55) tmp.lerp(cDirt, (slope - 0.55) * 1.5);
      colAttr.setXYZ(i, tmp.r, tmp.g, tmp.b);
    }
    colAttr.needsUpdate = true;
  };

  W.applyBiome = function (b) {
    W.biome = b;
    if (W.scene) {
      W.scene.background.set(b.bg);
      if (W.scene.fog) { W.scene.fog.color.set(b.bg); W.scene.fog.near = b.fog[0]; W.scene.fog.far = b.fog[1]; }
    }
    if (W.hemi) { W.hemi.color.set(b.hemiSky); W.hemi.groundColor.set(b.hemiGround); }
    if (W.water) W.water.material.color.set(b.water);
    if (W.skyMat) { W.skyMat.uniforms.top.value.set(b.sky.top); W.skyMat.uniforms.mid.value.set(b.sky.mid); W.skyMat.uniforms.bot.value.set(b.sky.bot); W.skyMat.uniforms.sunCol.value.set(b.sky.sun); }
    W.recolorTerrain(b.ground);
    W.recolorSkirt(b.ground);
  };

  return W;
})();
