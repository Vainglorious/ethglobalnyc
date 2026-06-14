// WorldColony — dual camera: cinematic orbit/tour + WASD free-explore (pointer-lock look)
window.DN = window.DN || {};

DN.camera = (function () {
  const C = { mode: 'cinematic', followFn: null };
  let cam, controls, dom;
  const keys = {};
  let yaw = 0, pitch = -0.15;
  const vel = new THREE.Vector3();
  const EYE = 4.2;
  const tween = { active: false, t: 0, dur: 1.6, fromP: new THREE.Vector3(), toP: new THREE.Vector3(), fromT: new THREE.Vector3(), toT: new THREE.Vector3() };
  function ease(x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
  function ground(x, z) { return DN.world.heightAt(x, z); }

  C.init = function () {
    cam = DN.world.camera;
    dom = DN.world.renderer.domElement;
    controls = new THREE.OrbitControls(cam, dom);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.rotateSpeed = 0.5;
    controls.zoomSpeed = 0.8;
    controls.panSpeed = 0.6;
    controls.minDistance = 6;
    controls.maxDistance = 760;
    controls.maxPolarAngle = Math.PI * 0.49;
    controls.target.set(0, 2, 0);
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.3;
    C.controls = controls;

    addEventListener('keydown', e => {
      keys[e.code] = true;
      if (e.code === 'Space' && C.mode === 'explore') e.preventDefault();
    });
    addEventListener('keyup', e => { keys[e.code] = false; });

    // pointer-lock mouse look in explore mode
    dom.addEventListener('click', () => {
      if (C.mode === 'explore' && document.pointerLockElement !== dom) dom.requestPointerLock();
    });
    document.addEventListener('mousemove', e => {
      if (C.mode === 'explore' && document.pointerLockElement === dom) {
        yaw -= e.movementX * 0.0024;
        pitch -= e.movementY * 0.0024;
        pitch = Math.max(-1.3, Math.min(1.2, pitch));
      }
    });
    document.addEventListener('pointerlockchange', () => {
      const locked = document.pointerLockElement === dom;
      document.body.classList.toggle('pl', locked);
      if (DN.hud) DN.hud.setExploreLocked(locked);
    });
    return C;
  };

  C.setMode = function (mode) {
    if (mode === C.mode) return;
    C.mode = mode;
    C.followFn = null;
    if (mode === 'explore') {
      controls.enabled = false;
      controls.autoRotate = false;
      // derive yaw/pitch from current view, drop to ground level near target
      const dir = new THREE.Vector3().subVectors(controls.target, cam.position);
      yaw = Math.atan2(-dir.x, -dir.z);
      pitch = -0.12;
      const gx = cam.position.x, gz = cam.position.z;
      cam.position.set(gx, ground(gx, gz) + EYE, gz);
      tween.active = false;
    } else {
      controls.enabled = true;
      if (document.pointerLockElement === dom) document.exitPointerLock();
      // set orbit target a little ahead of camera
      const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
      controls.target.copy(cam.position).addScaledVector(fwd, 24).setY(4);
    }
    document.body.classList.toggle('explore-mode', mode === 'explore');
    if (DN.hud) DN.hud.setCameraMode(mode);
  };

  C.flyTo = function (target, dist, height, dur) {
    if (C.mode !== 'cinematic') C.setMode('cinematic');
    controls.autoRotate = false;
    const dir = new THREE.Vector3().subVectors(cam.position, controls.target).setY(0);
    if (dir.lengthSq() < 0.01) dir.set(0.6, 0, 1);
    dir.normalize();
    tween.fromP.copy(cam.position); tween.fromT.copy(controls.target);
    tween.toT.copy(target);
    tween.toP.copy(target).addScaledVector(dir, dist).setY(target.y + height);
    tween.t = 0; tween.dur = dur || 1.6; tween.active = true;
  };

  // fn returns the THREE.Vector3 target; offset (optional) sets the camera
  // position relative to the target. Default is a close inspection view
  // (+6 up, +14 back). Wider lifecycle shots should pass something like
  // (0, 50, 80) to pull the camera out.
  C.follow = function (fn, offset) { C.setMode('cinematic'); C.followFn = fn; C.followOffset = offset || null; controls.autoRotate = false; };
  C.stopFollow = function () { C.followFn = null; C.followOffset = null; };
  C.autoRotate = function (on) { if (C.mode === 'cinematic') controls.autoRotate = on; };

  C.update = function (dt) {
    if (C.mode === 'explore') {
      const fwd = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
      const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));
      const accel = new THREE.Vector3();
      const sp = (keys['ShiftLeft'] || keys['ShiftRight']) ? 46 : 24;
      if (keys['KeyW'] || keys['ArrowUp']) accel.add(fwd);
      if (keys['KeyS'] || keys['ArrowDown']) accel.sub(fwd);
      if (keys['KeyD'] || keys['ArrowRight']) accel.add(right);
      if (keys['KeyA'] || keys['ArrowLeft']) accel.sub(right);
      if (accel.lengthSq() > 0) accel.normalize().multiplyScalar(sp);
      vel.lerp(accel, Math.min(1, dt * 8));
      cam.position.addScaledVector(vel, dt);
      // clamp inside world
      const lim = DN.world.SIZE * 0.5 - 6;
      cam.position.x = Math.max(-lim, Math.min(lim, cam.position.x));
      cam.position.z = Math.max(-lim, Math.min(lim, cam.position.z));
      // terrain follow (with vertical bob)
      let gy = ground(cam.position.x, cam.position.z) + EYE;
      if (keys['Space']) gy += 6;
      cam.position.y += (gy - cam.position.y) * Math.min(1, dt * 10);
      const dir = new THREE.Vector3(
        -Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch)
      );
      cam.lookAt(cam.position.clone().add(dir));
      return;
    }
    // cinematic
    if (tween.active) {
      tween.t += dt / tween.dur;
      const k = ease(Math.min(1, tween.t));
      cam.position.lerpVectors(tween.fromP, tween.toP, k);
      controls.target.lerpVectors(tween.fromT, tween.toT, k);
      if (tween.t >= 1) tween.active = false;
    } else if (C.followFn) {
      const p = C.followFn();
      if (p) {
        controls.target.lerp(p, Math.min(1, dt * 3));
        const off = C.followOffset || new THREE.Vector3(0, 6, 14);
        const desired = p.clone().add(off);
        cam.position.lerp(desired, Math.min(1, dt * 1.6));
      }
    }
    controls.update();
  };

  return C;
})();
