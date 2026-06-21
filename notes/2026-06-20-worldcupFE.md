# 2026-06-20 — World Cup Predictions Frontend (branch: `worldcup`)

Planning doc for a frontend addition to WorldColony: a prominent entry button on the
main 3D scene that leads to a new static **World Cup Predictions** page surfacing our
real on-chain trades, simulated/counterfactual trades, and the strategy story
(arbitrage, UMA oracle, privileged ClickHouse data).

Stack reminder: the live frontend is a **vanilla Three.js static app** served by Vite
(`index.html` + classic scripts in `public/dinasty/*.js`, vendored three in
`public/vendor/`). No React/bundler. New pages are plain static HTML/CSS/JS under
`public/`. Dev server currently running on **localhost:3000** (`npm run dev -- --port 3000`).

---

## 1. Entry button on the main scene (top-left)

- Add a prominent button in the **top-left** HUD that reads:
  **"Ant Colony — World Cup Predictions"**.
- Placement: inside `#hud` near `#brand` (top-left), styled as a bold call-to-action
  (distinct from the existing subtle tool panels). Pixel/arcade aesthetic matches the
  existing fonts (Press Start 2P / Silkscreen already loaded in `index.html`).
- Behavior: navigates to `/worldcup` (full page nav, not an in-scene overlay — keeps
  the heavy WebGL scene out of the predictions page).
- Files touched:
  - `index.html` — add the button markup (e.g. `<a id="wc-cta" href="/worldcup">…</a>`).
  - `public/dinasty/styles.css` — `#wc-cta` styling (prominent, top-left, hover glow).

## 2. ~~New static page at `domain/worldcup`~~ → **IN-APP OVERLAY** (pivot 2026-06-20)

**ARCHITECTURE CHANGE (Adil):** Do NOT navigate to a separate page. Instead the entry
button opens a **full-screen overlay layer** inside `index.html` that covers the entire
app (3D scene + all HUD) with a top z-index. A **back button replaces the entry button in
the same top-left spot** to dismiss it (Esc also closes). All World Cup content lives in
`#wc-content` inside that overlay.
- ✅ DONE: overlay (`#wc-overlay`, dark-green gradient bg), `#wc-back` button, toggle via
  `body.wc-open`, all fenced in the WORLD CUP TEMP blocks (`index.html` + `styles.css`).
- Implication: no `public/worldcup/index.html`, no routing question. The soccer-ball SVG
  still lives at `public/worldcup/soccerball.svg`. Content (§3–§5) renders into `#wc-content`
  via a `worldcup.js` (to be added) — same fetch/render plan, just mounted in the overlay.

### (original separate-page plan, superseded — kept for reference)

- Implement as `public/worldcup/index.html` so Vite serves it at the clean URL
  **`/worldcup`** (works in `npm run dev`, `vite preview`, and the static `dist/` deploy).
- Self-contained: its own `styles.css` (or reuse a trimmed slice of the dinasty look) +
  one `worldcup.js` that fetches the data JSON and renders the tables/cards.
- A "← Back to the Colony" link returns to `/`.

### Data wiring
The source-of-truth JSON files live at repo root (`ethglobalnyc/predictions.json`,
`ethglobalnyc/simulatedtransactions.json`). The frontend can only fetch from `public/`.
- **Plan:** copy both into `frontend/public/data/` →
  `public/data/predictions.json`, `public/data/simulatedtransactions.json`,
  and `worldcup.js` fetches them at runtime. (Note: these are snapshots — re-copy if the
  root files change. Optional later: a tiny npm script to sync.)

## 3. World Cup Predictions page — content

### a.i — Wallet identity (ENS-first) + PolygonScan
- **Primary identity = ENS `worldcolony.eth`** on **Ethereum mainnet** — this is the
  canonical handle for the trading wallet (resolves to `0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`).
  Lead with the `.eth` name, not the raw hex.
  - Link → ENS app `https://app.ens.domains/worldcolony.eth`
  - Link → Etherscan `https://etherscan.io/name-lookup-search?id=worldcolony.eth`
    (or `https://etherscan.io/address/0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`).
- The **same resolved address trades on Polygon** → PolygonScan button:
  `https://polygonscan.com/address/0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`
  (= `polygun_trading_address` in `predictions.json`). i.e. identity on mainnet (ENS),
  execution on Polygon — same address, two chains. Make that explicit on the page.
- Also surface the treasury: `0xcc16bEC342794f35a32d4Ba2c76BF9D759C131eB`.
- Settlement token shown as **pUSD** (Polymarket USD, Polygon `0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb`, 6 decimals).
- Optional: resolve `worldcolony.eth` live in-browser (ENS public resolver / viem) to
  display the address dynamically — but hardcoding the known address is fine for the demo.

### a.ii — Real trades to date (from `predictions.json`)
- Render the 11 real, on-chain-verified trades as a table/cards. Columns:
  - **Match / event** (`event`, e.g. "Brazil vs. Morocco (Jun 13)") + kickoff/timestamp (`ts_utc`).
  - **Pick** (`outcome` / `market_question`), **side**.
  - **Phase** (`bet_phase`: pregame / in-play), **placed_by** (adil/claude), **method** (manual/auto).
  - **Size**: `shares`, `avg_price`, `pusd_total`.
  - **Status** (`status`), **tx link** → `https://polygonscan.com/tx/<tx_hash>`, block.
  - **Notes** (the `note` field — includes the colony-consensus story, the accidental
    Scotland double-fill, the "submitted but filled on-chain" verifications).
- Highlight: trades 1–8 carry rich World-Cup metadata; trades 9–11 are bare market_ids
  (label them by polygun_market_id, note metadata TBD).

### a.iii — Simulated / counterfactual trades (from `simulatedtransactions.json`)
- Clearly badge this section **"SIMULATED — not executed on-chain"** (the file is
  explicitly `executed: false`, no real funds moved).
- Context card: Qatar vs. Switzerland (Group B, 2026-06-13, final 1-1 draw), thesis =
  "privileged info / speed edge — we had the read, lost it to score-latency + venue".
- Three simulated trades:
  1. **Draw @ 0.035** (would've netted ~$55) — repriced to 100c before we could act.
  2. **Under 2.5 @ 0.335** (1-1 = under, +$3.97) — no executable venue (O/U not on PolyGun,
     CLOB US-geoblocked).
  3. **Australia win @ 0.52–0.57** — ATTEMPTED but UNFILLABLE: winning side had 0 asks
     ("the liquidity wall").
- Surface the `lessons` array verbatim as takeaways.

#### a.iii.A — Link to UMA oracle
- Button/link → UMA Optimistic Oracle (`https://oracle.uma.xyz/`). UMA is the resolution
  source for these markets (our ClickHouse corpus includes `uma_oo_v2_events_decoded`).

#### a.iii.B — Link to Polymarket trading profile  ✅ CONFIRMED
- Link → our Polymarket profile (activity tab):
  **`https://polymarket.com/@xi31ydqg4cnd?tab=activity`**
- This is the public-facing activity feed for the colony's trading account — pairs
  nicely with the on-chain tx links (Polymarket UI view ↔ PolygonScan receipts).

#### a.iii.C — PolymarketAnalytics  ❌ DROPPED
- Decision (2026-06-20): **do NOT show a PolymarketAnalytics link.** The data there isn't
  good enough to display. (It's our own site for O/U lines, but we won't surface it on
  this page.) The Over/Under story still lives in the simulated-trade blurb text, just
  without an outbound link.

#### a.iii.D — Blurb: arbitrage strategies
- Short copy: cross-source arbitrage between the colony's read and the live market —
  bet the gap (draw cheap while market still implies a leader; O/U mispricing vs. the
  in-play score). The edge was real on both Qatar/Switzerland legs; we lost it to
  **speed and venue**, not a wrong call. Needs a live-score feed faster than the
  market reprice + an executable venue for O/U.

#### a.iii.E — Blurb: UMA oracle strategies
- Short copy: UMA's Optimistic Oracle is the ground-truth settlement layer. Our edge
  is reading **UMA resolution / dispute events** (decoded in ClickHouse) before the
  broader market fully reprices around settlement — and avoiding the structural trap of
  trying to scalp a ~99c near-certain winner at the close (0 asks = unbuyable).

#### a.iii.F — Blurb: privileged information via our proprietary ClickHouse API
- Short copy + link to the metered **ClickHouse knowledge plane**
  (`https://ethglobalnyc-production-5ce3.up.railway.app`, `/health` + `/config` are
  read-only and judge-runnable). Three rules:
  1. **Timestamp gate (cardinal rule):** every gated query enforces `ts <= as_of_ts` in
     SQL *and* re-checks every row in Python → no lookahead leakage (makes replay honest).
  2. **x402 metering:** gated queries are `402 → pay → 200`, so thinking costs USDC.
  3. **Worldcoin-verified premium tier:** verified lineages (a `humanId`) get a discount
     + higher caps.
  - Datasets: `odds` (Polymarket `market_snapshots` time-series), `uma_events`
    (`uma_oo_v2_events_decoded`), `markets` (catalog search). This is the "privileged
    data" the ants pay to query and that powered the simulated draw/under reads.

---

## 4. Team logos + upcoming game + "have the ants predicted?" status

Goal: at the top of the `/worldcup` page (and optionally a compact strip on the main
scene), show **the upcoming World Cup game** with **team logos**, and clearly indicate
**whether the colony/ants have made a prediction on it yet**.

### 4a. Team logos / flags — PLAN ✅
World Cup teams are national sides → use **country flags** as the "logo" (free, unambiguous;
federation crests are copyrighted — avoid). Decided approach:

- **Source: `flagcdn.com`** — tiny, crisp, keyed by ISO-3166 alpha-2, supports the UK
  subdivisions we need. Use raster at the size we render: `https://flagcdn.com/w40/<code>.png`
  (or `w80` for retina / `h20`). `<img loading="lazy">` so it's light.
  - *(Optional later: vendor the ~48 used flags into `public/worldcup/flags/` for full
    offline determinism. Not needed for first build.)*
- **`TEAM_ISO` map in `worldcup.js`** — country name (as it appears in the KG) → flag code.
  The KG uses these exact spellings (note quirks): `Turkey` (not Türkiye), `Ivory Coast`
  (not Côte d'Ivoire), `South Korea`, `USA`, `Czech Republic`, `Bosnia & Herzegovina`,
  `Cape Verde`, `Curaçao`, `DR Congo`.
  - Sample mappings: Brazil→`br`, Morocco→`ma`, Switzerland→`ch`, Qatar→`qa`, France→`fr`,
    Senegal→`sn`, Panama→`pa`, Croatia→`hr`, Australia→`au`, Ecuador→`ec`, Ivory Coast→`ci`,
    Haiti→`ht`, USA→`us`, South Korea→`kr`, Czech Republic→`cz`, South Africa→`za`,
    Turkey→`tr`, Paraguay→`py`, Bosnia & Herzegovina→`ba`, Curaçao→`cw`, DR Congo→`cd`,
    Cape Verde→`cv`, Saudi Arabia→`sa`, Uzbekistan→`uz`, New Zealand→`nz`.
  - **UK subdivisions:** England→`gb-eng`, Scotland→`gb-sct`, Wales→`gb-wls`
    (flagcdn supports these).
- **Placeholder slots:** the KG also contains non-country tokens for undecided knockout
  fixtures — group ranks (`1A`, `2B`), best-thirds (`3A/B/C/D/F`), and bracket refs
  (`W73`, `L101`). These have **no flag** → render a neutral pixel **⚽ / group-badge**
  placeholder + the raw token (e.g. "Winner Group A"). The flag lookup must fail gracefully
  to this, never a broken image.
- Build step: generate the full `TEAM_ISO` map from the 48 real countries in
  `worldcup-games.json` (the team list is already extracted), hand-verify the quirky ones.

### 4b. Upcoming game (the fixture) — REUSE the colony's own source/method
**Use the same World Cup data the backend uses — do not invent a new source.**

- **Canonical source = `colony/data/world_cup_kg.json`** (the committed tournament
  knowledge graph: 847 entities incl. **104 `match` entities** + 12 `group`). Built from
  **OpenFootball 2026** (`colony_harness/tournament_graph.py` →
  `https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json`),
  then committed so it's offline/deterministic.
- Served live by `colony_api`:
  - `GET /kg/world-cup` → full graph
  - `GET /kg/world-cup/summary` → markdown summary
  - (both already on the Railway deploy at `window.DN_CONFIG.API_URL`)
- **Match entity shape** (`entity_type:"match"`, `attributes`):
  `date` ("2026-06-13"), `time` ("18:00 UTC-4"), `team1`, `team2`, `group` ("Group C"),
  `ground` (venue), `round` ("Matchday 3"), and `score` (`{ft:[..],ht:[..]}` once played,
  else null/absent). `entity_id` like `match:world_cup_2026:NNN:YYYY_MM_DD_team1_team2`.
- **Reuse the backend's exact "upcoming games" logic** — `colony_api.main._forecast_games_from_kg()`:
  iterate `match` entities, take `team1`/`team2`, **skip any with a non-empty `score`**
  (already played), set `market_type = three_way` if it has a `group` else `binary`,
  then **sort by `(date, time, name)`**. Port this verbatim into `worldcup.js`.
  → "the upcoming game" = first game with no score (or first with kickoff `>= now`).
  Games that already have a `score` become "**played**" rows where we can show the result
  next to the colony's call (did the ants get it right?).
- **Data wiring (mirror, like the backend does):** copy `colony/data/world_cup_kg.json`
  → `frontend/public/data/world_cup_kg.json` and fetch it locally (keyless, deterministic).
  Prefer the live `GET /kg/world-cup` when `API_URL` is reachable, fall back to the local
  mirror — same Live/Replay pattern the rest of the app already uses.
- Render a **Next Match card**: `[flag] Team1  vs  Team2 [flag]` · Group · Venue · Kickoff
  (local + countdown), plus a horizontal rail of the next N upcoming `match` entities.

### 4b-bis. TWO kinds of colony bet (critical for the listing)
The trades in `predictions.json` are not all per-match. Split them:

1. **Per-match markets** — "Will `<team>` win on `<date>`?" → render a **prediction badge
   on that fixture's row** in the matches list. NOTE: bets are often placed *days early*
   (e.g. a Panama bet placed 6/18–6/19 for **Panama vs Croatia on 2026-06-23**), so match
   by **market identity, not by the trade's timestamp.**
2. **Outright / tournament futures** — "Will `<team>` win the **2026 World Cup**?" → these
   are NOT tied to a single fixture. Render them in a **separate "Colony outright bets"
   panel** (e.g. **France to win the World Cup**, trades #1 & #2, currently OPEN).

### Resolving the bare-market trades (#9–#11) — UNCONFIRMED, do not guess on-page
`predictions.json` trades 9–11 carry only `polygun_market_id` (no `event`/`market_question`),
so we cannot reliably say which match they belong to from the repo alone.
- **Source of truth = the live Polymarket activity feed** (`@xi31ydqg4cnd`) + Adil's
  confirmation — NOT internal notes (an old note guessed `1897108` = a South Africa 6/18
  game, but that's unverified and Adil does not see it on the profile → treat as wrong
  until confirmed).
- Plan: a small **manual override map** in `worldcup.js`
  (`polygun_market_id → { teams, date, market_question, kind }`) that we fill in ONLY with
  values Adil confirms from the live profile. Anything unmapped renders in a neutral
  **"Unmapped colony trades"** list (raw market id + tx link), never pinned onto a guessed
  fixture.
- Confirmed so far (from Adil): **France = tournament-winner futures** (outright panel),
  **Panama = a group match ~2026-06-23** (Panama vs Croatia, Group L — the per-match bet).
  - **TODO:** map `1897246` / `1897121` → {Panama, ...} and identify the third.

### 4c. "Have the ants predicted?" status
- For each fixture, cross-reference it against `predictions.json` (real) and
  `simulatedtransactions.json` (simulated) to derive a status badge:
  - **✅ Colony predicted** — show the pick (`outcome`), `side`, `avg_price`, phase
    (pregame/in-play), and a tx link if real. (e.g. Brazil vs. Morocco → "Brazil @ 0.59",
    Qatar vs. Switzerland → "Switzerland @ 0.85 + simulated Draw/Under reads".)
  - **🟡 Simulated only** — colony had a read but it wasn't executed (the Qatar/Switz
    draw + under, the Australia liquidity-wall attempt).
  - **⏳ No prediction yet** — upcoming match the ants haven't weighed in on → CTA to
    "Run the colony" (links back to the main scene's LLM-agents run, or just a label).
- **Matching logic** (`worldcup.js`): match a fixture → trade by **team names + date**
  (normalize "Türkiye/Turkiye", "Côte d'Ivoire/Cote d'Ivoire"), with `polygun_market_id`
  / `event` string as a secondary key. Build once into a `Map<fixtureKey, predictionState>`.
- Each fixture card therefore renders: both flags, teams, kickoff, group/venue, **and** the
  prediction badge — making "what's next + did the ants call it" readable at a glance.

### Open data note
- The 11 real trades cover specific Jun 13–19 group matches; most *upcoming* fixtures will
  legitimately show **⏳ No prediction yet** — that's expected and is itself the story
  (the colony predicts selectively where it sees edge).

## 5. Page copy / blurbs (DRAFT — for review)

### Hero / page intro
> **WorldColony — World Cup Predictions**
> A colony of autonomous AI "ants" forecasts World Cup matches, debates to consensus,
> and places real on-chain bets. Forecasting is the labor; the USDC market is the judge.
> Every trade below is verifiable on-chain — identity on Ethereum (`worldcolony.eth`),
> execution on Polygon.

### Real trades section intro
> **On-chain ledger.** These are real, executed trades — settled in pUSD on Polygon and
> verifiable by transaction hash. Picks come from the colony's consensus (the "ants"),
> placed either with a human pressing the final button or fully autonomously by code —
> both through our Polymarket execution rail (PolyGun).

### Simulated trades section intro
> **Counterfactual ledger — not executed.** No funds moved here. These are bets the colony
> *identified* but didn't place in time. We keep them separate from the real ledger to
> study one question honestly: what would our edge have produced if our execution speed
> matched our information?

### a.iii.D — Arbitrage strategies (blurb)
> **Arbitrage: bet the gap.**
> Our edge is the spread between the colony's read and the live market price. When the
> colony saw Qatar–Switzerland heading for a 1–1 draw, the draw was still trading at ~3.5c
> and the Under 2.5 at ~33c — both mispriced against the outcome we already expected. The
> calls were right; we lost the edge to **speed and venue, not to a wrong prediction.**
> Capturing it needs a live-score feed faster than the market reprice and an executable
> venue for the line — which is exactly what the rest of this stack is built to close.

### a.iii.E — UMA oracle strategies (blurb)
> **The oracle is the ground truth.**
> Polymarket's World Cup markets settle on **UMA's Optimistic Oracle** — the same
> resolution and dispute events we decode in our ClickHouse corpus. Reading the oracle
> layer tells us how a market *will* resolve before the crowd fully reprices around it.
> It also tells us where **not** to trade: you can't scalp a ~99c near-certain winner at
> the close — the winning side has zero asks (no one sells a sure thing), so a late market
> buy has nothing to fill against. We verified this live: 0 asks for five straight minutes.
> The edge is entering on the colony's read while two-sided liquidity still exists — not
> chasing the resolved winner.
> _(Links to UMA Optimistic Oracle.)_

### a.iii.F — Privileged information via our proprietary ClickHouse API (blurb)
> **A metered knowledge plane — thinking costs money.**
> The colony's ants query a private ClickHouse API holding the Polymarket odds time-series
> and decoded UMA resolution events. Three rules make it honest and scarce:
> **(1) Timestamp gate** — every query enforces `ts ≤ as_of_ts` in SQL *and* re-checks
> every row, so a replay can never peek at the future (no lookahead leakage).
> **(2) x402 metering** — gated queries are pay-to-read (`402 → pay → 200`) in USDC, so an
> ant spends real money to think. **(3) Worldcoin-verified tier** — lineages that prove a
> human (a `humanId`) get a discount and higher caps. This is the "privileged data" edge
> behind the reads above — priced, gated, and provably free of hindsight.
> _(Links to the live read-only API: `/health` + `/config`.)_

## 6. Visual design — base palette (extracted from the live FE)

Source: `frontend/public/dinasty/styles.css` (`:root`, lines 1–20). The aesthetic is a
**pixel-art / sunlit-parchment "world ink"** theme — earthy parchment panels, deep
sun-gold accents, on a dark-green world. Pixel display fonts. The `/worldcup` page should
**inherit this exact system** so it feels native (just dialed slightly more "World Cup").

### Core tokens (use these verbatim)
| Role | Token / value | Notes |
|---|---|---|
| **World background** (behind canvas) | `#0d1a14` | very dark green (`body` bg) |
| **Intro/hero background** | `radial-gradient(circle at 50% 40%, #1f3326, #0d1a14)` | dark green vignette |
| **Panel (parchment)** | `--panel: rgba(243,235,211,0.92)` ≈ `#F3EBD3` | primary card surface |
| **Panel strong** | `--panel-strong: rgba(249,243,226,0.96)` ≈ `#F9F3E2` | raised surface |
| **Slot (inset)** | `--slot: rgba(228,218,193,0.62)` | secondary button / inset |
| **Text — ink** | `--ink: #2C2820` | primary body text (on parchment) |
| **Text — soft** | `--ink-soft: #5E5440` | secondary text |
| **Text — faint** | `--ink-faint: #8C7E60` | labels, uppercase microcopy |
| **Text on dark** | `#FFE7A8` / `#FFD988` | warm cream/gold (tooltips, on-dark links) |
| **Accent — gold** | `--gold: #B07E1C` | primary accent / button fill |
| **Accent — gold deep** | `--gold-deep: #876012` | borders, hyperlinks on parchment |
| **Accent — gold bright** | `#FFD988`, `#FFE39A`, `#FFE8A6` | highlights, glints |
| **Accent — green** | `--green: #4E7E2A` | grass accent |
| **Border** | `--border: rgba(74,58,30,0.18)` / strong `0.36` | hairline → strong |
| **Pixel drop shadow** | `--shadow: 4px 4px 0 rgba(74,58,30,.3), 0 8px 18px -12px rgba(54,40,18,.35)` | hard pixel shadow |

### Semantic colors (already used for run sides — reuse for match outcomes)
| Role | Value |
|---|---|
| Home / Yes / positive | `#1f5ea8` (blue) |
| Draw / neutral | `#706f78` (gray) |
| Away / loss | `#a82d2d` (red) |
| Error | `#8f301f` |
| Dead / alert | `#D96E54` |

### Buttons (existing pattern)
- **Primary:** `background: var(--gold); color: #2a1d08; border: 1px solid var(--gold-deep)`
  (see `.backend-btn`). Gradient variant: `linear-gradient(180deg,#E0A828,#B07E1C)`.
- **Secondary:** `background: var(--slot); color: var(--ink); border-color: var(--border-strong)`.

### Hyperlinks (page convention to set, since the base app has no global `a{}`)
- On **parchment**: `color: var(--gold-deep) #876012`, underline on hover, `--ink` text for body.
- On **dark**: `color: #FFD988` (matches `.kg-links`).

### Fonts (already loaded in `index.html`)
- `--display: "Press Start 2P"` — headlines (use sparingly; it's chunky).
- `--font: "Pixelify Sans", Inter` — body.
- `--mono: "Silkscreen"` — numerals / stats / addresses.

> **Page direction:** parchment cards on the dark-green world bg, gold accents, pixel
> fonts — same as home, but the World Cup page may add a subtle pitch-green band / soccer
> motif in the hero. Keep it light (see §7 ethos): this is a temporary tournament skin.

## 7. The entry button — **BUILD THIS FIRST** (show before the page)

This is the single most important element. It's the only new thing on the main 3D scene,
it's **temporary** (removed after the World Cup), so it must be **eye-catching but light**.

### Intent (Adil)
- A **prominent overlay** button, top-left-ish on the main scene.
- **World-Cup themed** — a soccer ball, or a soccer-ball stripe/seam motif.
- **Temporary** — easy to rip out after the tournament (self-contained, one block of
  markup + scoped CSS, no rewiring of the HUD).
- **Lightweight** — no heavy assets, no new deps, pure CSS (ideally a CSS soccer-ball or a
  small inline SVG). No big PNGs, no animation that taxes the WebGL frame.

### Spec (proposed)
- **Label:** "Ant Colony — World Cup Predictions" (with a small ⚽ / pixel-ball glyph).
- **Markup:** a single `<a id="wc-cta" href="/worldcup">…</a>` placed in `index.html`
  just inside `#hud`, near `#brand` (top-left). Marked with an HTML comment
  `<!-- WORLD CUP TEMP — remove after tournament -->` for clean teardown.
- **Style (scoped `#wc-cta` block in styles.css, also fenced with a teardown comment):**
  - Parchment-strong pill (`--panel-strong`) with `--gold-deep` border + `--shadow`
    (consistent with the app), BUT with a **soccer-ball accent**: a small CSS/SVG
    black-and-white pentagon-seam ball glyph on the left, or a thin black/white
    "stitch" stripe along the top edge to read instantly as football.
  - Gold hover glow (reuse `#FFD988`), subtle scale on hover. One cheap CSS transition
    only — no continuous animation.
  - Pixel display font for the title line, mono for a tiny "LIVE" / sub-label.
- **Behavior:** full-page nav to `/worldcup` (keeps WebGL out of the predictions page).
- **Teardown:** delete the `#wc-cta` markup block + the fenced `#wc-cta` CSS block. Nothing
  else references it. (Document this in the comment.)

### Build & review loop
1. Build `#wc-cta` only. 2. Show it on `localhost:3000` (screenshot). 3. Iterate on the
look with Adil until it's right. **Only then** start the `/worldcup` page.

### STATUS — ✅ DONE (2026-06-20)
- Button built: parchment pill, real **public-domain soccer ball** (`/worldcup/soccerball.svg`,
  Wikimedia Commons), stitch stripe, "ANT COLONY · LIVE" kicker + "World Cup Predictions".
- Position: raised ~5% (`top: 44px`), **moved to body-level** + `z-index: 2147483000` so it
  sits in front of EVERYTHING (intro, onboarding modal, HUD). (Note: at this height it
  overlaps the `#brand` logo — accepted per "in front of everything".)
- Fenced with `WORLD CUP TEMP — remove after the tournament` comments in both
  `index.html` (body level, after `#wallet`) and `styles.css`.
- **Favicon added** (was missing): `frontend/public/favicon.ico` (16/32/48/64, from the
  soccer ball via inkscape→magick) + SVG fallback `<link>`s in `<head>`.

## File change summary

| File | Change |
|---|---|
| `frontend/index.html` | Add `#wc-cta` button (fenced w/ "WORLD CUP TEMP — remove after tournament" comment) linking to `/worldcup` — **BUILD FIRST (§7)** |
| `frontend/public/dinasty/styles.css` | Scoped `#wc-cta` block (fenced for clean teardown) — soccer-ball motif, parchment+gold |
| `frontend/public/worldcup/index.html` | **New** — World Cup Predictions static page |
| `frontend/public/worldcup/worldcup.css` | **New** — page styles (or reuse dinasty look) |
| `frontend/public/worldcup/worldcup.js` | **New** — fetch + render trades & blurbs |
| `frontend/public/data/predictions.json` | **New** — copy of root `predictions.json` |
| `frontend/public/data/simulatedtransactions.json` | **New** — copy of root file |
| `frontend/public/data/worldcup-games.json` | **Done** — 104 games extracted from `colony/data/world_cup_kg.json` via the backend's `_forecast_games_from_kg` logic (teams/date/time/group/venue/score/played) |
| flags | **CDN** — `flagcdn.com` (no vendored files for first build); `TEAM_ISO` map lives in `worldcup.js` |

## Open questions / confirm before/while building
1. ✅ RESOLVED — Polymarket profile: `https://polymarket.com/@xi31ydqg4cnd?tab=activity`.
2. ✅ RESOLVED — PolymarketAnalytics is our own site (`polymarketanalytics.com`,
   per-match `/sports/soccer/<slug>`); human-facing link, not a programmatic source.
3. **Trades 9–11** lack event/match metadata in `predictions.json` — leave as raw
   market_ids, or backfill the match names (could map `polygun_market_id` → match via KG)?
4. Routing: confirm `public/worldcup/index.html` → `/worldcup` is acceptable for the
   final deploy target (Vercel/static). It works under Vite dev + `dist/`.
5. Keep JSON as copied snapshots, or add a sync step so the page never drifts from root?
6. Flags: vendor local SVGs (offline-safe, recommended) vs. `flagcdn.com` CDN?
