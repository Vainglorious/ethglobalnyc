import { chromium } from 'playwright'
const b = await chromium.launch({ args:['--use-gl=angle','--ignore-gpu-blocklist','--enable-webgl'] })
const p = await b.newPage({ viewport: { width: 1280, height: 1050 }, deviceScaleFactor: 1.35 })
const errs=[]; p.on('pageerror',e=>errs.push(e.message)); p.on('console',m=>{ if(m.type()==='error') errs.push('[c] '+m.text()) })
await p.goto('http://localhost:3000/', { waitUntil: 'networkidle' }).catch(()=>{})
await p.waitForTimeout(4000)
await p.click('#wc-cta'); await p.waitForTimeout(1500)
for (const [id,name] of [['wc-outright','outright'],['wc-trades','trades'],['wc-sim','sim']]) {
  await p.evaluate((i)=>{ const e=document.getElementById(i); if(e) e.scrollIntoView(); }, id)
  await p.waitForTimeout(700)
  await p.screenshot({ path: '/tmp/wc-c3-'+name+'.png' })
}
console.log('errors:', errs.slice(0,6).join(' | ')||'none')
await b.close()
