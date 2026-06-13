import { chromium } from 'playwright'

const url = process.argv[2] || 'http://localhost:5173/'
const out = process.argv[3] || '/tmp/colony_closeup.png'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const logs = []
page.on('console', (m) => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`))

await page.goto(url, { waitUntil: 'networkidle' }).catch((e) => logs.push(`[goto] ${e.message}`))
await page.waitForTimeout(3000)

// zoom the OrbitControls in toward the colony centroid via wheel events
const cx = 720
const cy = 450
await page.mouse.move(cx, cy)
for (let i = 0; i < 22; i++) {
  await page.mouse.wheel(0, -120)
  await page.waitForTimeout(60)
}
await page.waitForTimeout(2500)
await page.screenshot({ path: out })

console.log('--- console (' + logs.length + ') ---')
console.log(logs.filter((l) => !l.includes('vite') && !l.includes('DevTools')).slice(0, 20).join('\n') || '(clean)')
console.log('--- saved ' + out + ' ---')
await browser.close()
