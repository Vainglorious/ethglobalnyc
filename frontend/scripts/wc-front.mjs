import { chromium } from 'playwright'
const b = await chromium.launch({ args:['--use-gl=angle','--ignore-gpu-blocklist','--enable-webgl'] })
const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
await p.goto('http://localhost:3000/', { waitUntil: 'networkidle' }).catch(()=>{})
await p.waitForTimeout(2500)   // intro still fading / onboarding up — DO NOT hide it
await p.screenshot({ path: '/tmp/wc-front-early.png', clip:{x:0,y:0,width:520,height:240} })
await p.waitForTimeout(3500)
await p.screenshot({ path: '/tmp/wc-front-late.png', clip:{x:0,y:0,width:520,height:240} })
const z = await p.evaluate(() => getComputedStyle(document.getElementById('wc-cta')).zIndex)
console.log('wc-cta z-index:', z)
await b.close()
