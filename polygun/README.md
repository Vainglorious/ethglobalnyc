# PolyGun Automation (Telegram userbot)

PolyGun has **no API** — it's only driveable through its Telegram bot
(`@PolyGunSniperBot`). And direct Polymarket CLOB is **geoblocked in the US**
(see `notes/2026-06-13-polymarketexecution.txt`), so PolyGun is our execution path.

This drives the bot as **your own Telegram account** (Telethon / MTProto): it reads
the bot's messages + inline buttons and can send text and tap buttons. That's how
we automate placing trades.

## Setup (one-time)

1. Get Telegram API credentials: go to https://my.telegram.org → **API
   development tools**, log in with your phone, create an app (any name). Copy the
   **api_id** and **api_hash** into `polygun/.env` (`TG_API_ID`, `TG_API_HASH`,
   and your `TG_PHONE`).

2. Log in (interactive — Telegram will text you a code):
   ```
   polygun/.venv/bin/python polygun/pg.py login
   ```
   This creates `polygun/pg.session` (gitignored). If you have 2FA, it'll ask for
   your password too.

3. Confirm:
   ```
   polygun/.venv/bin/python polygun/pg.py whoami
   ```

## Mapping the buy flow

We reverse-engineer the bot's button flow, then script it:

```
polygun/.venv/bin/python polygun/pg.py send "/start"     # open the menu
polygun/.venv/bin/python polygun/pg.py dump              # list messages + [row,col] buttons
polygun/.venv/bin/python polygun/pg.py click <msg_id> <row> <col>   # tap a button
```

Each `dump`/`send`/`click` prints the bot's latest messages with every inline
button labeled `[row,col]`, so we can follow: Buy → paste/choose market → amount →
confirm. Once we know the exact sequence, we add a `buy` subcommand that replays it.

For Colony KG enrichment, export a read-only snapshot instead of driving the bot
during a simulation:

```
polygun/.venv/bin/python polygun/pg.py snapshot --out polygun/snapshots/latest.json
python3 colony/run_match.py --data-mode public --include-polygun
```

`snapshot` only reads recent bot messages and inline buttons. It does not send
text, click buttons, or place trades. The Colony scout consumes that JSON only
when it contains match-specific market panel text for the teams being scouted;
balance/account state is ignored.

## Safety

- This logs in as YOU. Keep `.env` and `pg.session` secret (both gitignored).
- PolyGun is custodial; trades spend your pUSD balance. Test with tiny amounts.
- A confirm step is usually the last button — we keep that explicit so nothing
  fires by accident while exploring.

## Status

- [done] Telethon controller (`pg.py`: login / whoami / dump / send / click).
- [done] Read-only `snapshot` export for Colony KG enrichment.
- [you]  Create the my.telegram.org app + fill `.env` + run `pg.py login`.
- [next] Map the buy flow together, then add an automated `buy` subcommand.
