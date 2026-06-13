import { chromium } from 'playwright'

const url = process.argv[2] || 'http://localhost:5173/'
const btn = process.argv[3] || 'World'
const out = process.argv[4] || '/tmp/colony_click.png'

const browser = await chromium.launch({ args: ['--use-gl=angle', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const logs = []
page.on('console', (m) => logs.push(`[${m.type()}] ${m.text()}`))
page.on('pageerror', (e) => logs.push(`[pageerror] ${e.message}`))

await page.goto(url, { waitUntil: 'networkidle' }).catch((e) => logs.push(`[goto] ${e.message}`))
await page.waitForTimeout(3000)
try {
  await page.getByRole('button', { name: btn }).click({ timeout: 4000 })
} catch (e) {
  logs.push(`[click] could not click "${btn}": ${e.message}`)
}
await page.waitForTimeout(3500)
await page.screenshot({ path: out })

console.log('--- console (' + logs.length + ') ---')
console.log(logs.filter((l) => !l.includes('vite') && !l.includes('DevTools')).slice(0, 20).join('\n') || '(clean)')
console.log('--- saved ' + out + ' ---')
await browser.close()
