import { chromium } from 'playwright'
const browser = await chromium.launch({ args: ['--use-gl=angle','--ignore-gpu-blocklist','--enable-webgl'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 })
const logs = []
page.on('console', m => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', e => logs.push(`[pageerror] ${e.message}`))
await page.goto('http://localhost:3000/', { waitUntil: 'networkidle' }).catch(e=>logs.push('[goto] '+e.message))
await page.waitForTimeout(5000)
// hide intro if still up
await page.evaluate(() => { const i=document.getElementById('intro'); if(i) i.style.display='none'; })
await page.waitForTimeout(300)
const cta = await page.$('#wc-cta')
console.log('wc-cta present:', !!cta)
if (cta) console.log('box:', JSON.stringify(await cta.boundingBox()))
await page.screenshot({ path: '/tmp/wc-full.png' })
await page.screenshot({ path: '/tmp/wc-closeup.png', clip: { x: 0, y: 0, width: 460, height: 220 } })
// hover state
if (cta) { await cta.hover(); await page.waitForTimeout(500); await page.screenshot({ path: '/tmp/wc-hover.png', clip: { x: 0, y: 0, width: 460, height: 220 } }) }
console.log('--- console ---'); console.log(logs.slice(0,15).join('\n')||'(clean)')
await browser.close()
