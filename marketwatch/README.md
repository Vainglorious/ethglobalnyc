# marketwatch

Tiny live match dashboard — **score + a streaming countdown + market prices** in one
browser view. Built for timing last-minute bets (e.g. "how much real time is left?").

## Run
```bash
# needs a python with certifi — the polymarket venv has it:
polymarket/.venv/bin/python3 marketwatch/marketwatch.py
# then open the URL it prints (http://localhost:3000, or :3001 if 3000 is taken
# by your frontend — it auto-falls-back). Force a port with --port 3000.
```

## What it shows (auto-refreshing; clock ticks every 0.25s, data every 4s)
- **Score** — live from ESPN's public scoreboard API (`site.api.espn.com`).
- **Time-left countdown** — streams down to 90:00 and **goes negative (red `+MM:SS`)
  in stoppage**; holds at "HT" during the break, "FT" at full time, and shows a
  kickoff countdown pre-match. Falls back to a kickoff-based estimate (with a ~15-min
  halftime hold) if the ESPN clock lags.
- **Live prices** — Belgium / IR Iran / Draw Buy-Yes (ask) from Polymarket CLOB
  (`clob.polymarket.com/book` — reads are public, never geoblocked).

## Point it at another game
Edit the `CONFIG` block at the top of `marketwatch.py`: `KICKOFF_UTC`, `TEAM_A`/`TEAM_B`
(substrings matched against ESPN), and `TOKENS` (the 3 outcome CLOB token ids).

Stdlib only (+certifi). No build step. Serves a `/state` JSON endpoint the page polls.
