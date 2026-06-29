import { chromium } from 'playwright';

const url = process.env.COLONY_URL || 'http://127.0.0.1:5173/';
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', err => errors.push(err.message));
page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
await page.waitForTimeout(3500);

const checks = await page.evaluate(() => {
  const W = window.DN && window.DN.world;
  const A = window.DN && window.DN.ants;
  const F = window.DN && window.DN.flora;
  const C = window.DN && window.DN.colony;
  const scene = W && W.scene;
  let grassInstances = 0;
  if (F && F.grass && typeof F.grass.count === 'number') grassInstances = F.grass.count;
  let moundDetail = false;
  if (C && C.list && C.list[0]) {
    moundDetail = !!(C.list[0]._detailGroup && C.list[0]._detailGroup.children.length >= 3);
  }
  let antSheen = false;
  if (A && A.material) antSheen = !!A.material.userData.sceneRevampSheen;
  let hasClouds = false;
  let hasTerrainOverlay = false;
  let hasLivingCritters = false;
  if (scene) {
    scene.traverse(obj => {
      if (obj.name === 'atmospheric-clouds') hasClouds = true;
      if (obj.name === 'terrain-detail-overlay') hasTerrainOverlay = true;
      if (obj.name === 'living-critters') hasLivingCritters = true;
    });
  }
  return {
    worldRevampFlag: !!(W && W._sceneRevampV2),
    waterIsShader: !!(W && W.water && W.water.material && W.water.material.isShaderMaterial),
    hasClouds,
    hasTerrainOverlay,
    hasLivingCritters,
    antSheen,
    moundDetail,
    grassInstances: grassInstances >= 450,
  };
});

const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([name]) => name);
await browser.close();
if (errors.length || failed.length) {
  console.error(JSON.stringify({ failed, errors, checks }, null, 2));
  process.exit(1);
}
console.log(JSON.stringify({ ok: true, checks }, null, 2));
