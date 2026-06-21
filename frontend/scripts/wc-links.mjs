import { chromium } from 'playwright'
const b = await chromium.launch(); const p = await b.newPage()
await p.goto('http://localhost:3000/',{waitUntil:'networkidle'}).catch(()=>{})
await p.waitForTimeout(3500); await p.click('#wc-cta'); await p.waitForTimeout(1200)
const links = await p.evaluate(()=>[...document.querySelectorAll('#wc-content a')].map(a=>a.textContent.trim()+' -> '+a.href))
console.log(links.filter(l=>/uma|oracle|polygon|polymarket|ens|etherscan|clickhouse/i.test(l)).join('\n'))
await b.close()
