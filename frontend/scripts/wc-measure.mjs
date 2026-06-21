import { chromium } from 'playwright'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://localhost:3000/', { waitUntil: 'networkidle' }).catch(()=>{})
await p.waitForTimeout(4000)
await p.evaluate(() => { const i=document.getElementById('intro'); if(i) i.style.display='none' })
for (const sel of ['#brand', '.brand-txt', '#wc-cta', '#stats']) {
  const el = await p.$(sel); console.log(sel, el ? JSON.stringify(await el.boundingBox()) : 'none')
}
await b.close()
