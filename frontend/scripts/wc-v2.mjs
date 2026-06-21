import { chromium } from 'playwright'
const b = await chromium.launch(); const p = await b.newPage()
await p.goto('http://localhost:3000/',{waitUntil:'networkidle'}).catch(()=>{})
await p.waitForTimeout(3500); await p.click('#wc-cta'); await p.waitForTimeout(1200)
const t = await p.evaluate(()=>document.getElementById('wc-trades').innerText)
console.log('has Adil:', /\bAdil\b/.test(t), '| has Human-Executed:', /Human-Executed/.test(t), '| has claude:', /claude/i.test(t))
await b.close()
