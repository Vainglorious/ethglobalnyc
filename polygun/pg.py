"""PolyGun automation via a Telegram userbot (Telethon).

PolyGun has no API — it's only driveable through its Telegram bot. This logs in as
YOUR Telegram account and operates @PolyGunSniperBot programmatically: it reads the
bot's messages + inline buttons and can send text / tap buttons. That's how we
automate trades.

Subcommands:
  login                  one-time interactive auth (asks for your phone + the code
                         Telegram texts you; creates polygun/pg.session)
  whoami                 confirm the logged-in account
  dump [--n N]           print the last N messages from the bot + their buttons,
                         each labeled with [row,col] so you can click them
  send "TEXT"            send a text message to the bot, then show its reply
  click MSG_ID ROW COL   tap the inline button at [ROW,COL] of message MSG_ID,
                         then show the bot's reply

Typical flow to learn the buy path:
  pg.py login
  pg.py send "/start"          # see the menu
  pg.py dump                   # read buttons
  pg.py click <id> 0 0         # tap into Buy / paste a market, etc.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_env() -> None:
    p = HERE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_client():
    from telethon import TelegramClient

    load_env()
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit("Set TG_API_ID and TG_API_HASH in polygun/.env "
                         "(get them at https://my.telegram.org).")
    bot = os.environ.get("PG_BOT", "PolyGunSniperBot").strip().lstrip("@")
    client = TelegramClient(str(HERE / "pg"), int(api_id), api_hash)
    return client, bot


def _print_message(m) -> None:
    who = "me" if m.out else "bot"
    print(f"\n--- msg {m.id} ({who}) ---")
    if m.text:
        print(m.text)
    markup = getattr(m, "reply_markup", None)
    rows = getattr(markup, "rows", None) if markup else None
    if rows:
        for r, row in enumerate(rows):
            for c, btn in enumerate(row.buttons):
                url = getattr(btn, "url", None)
                kind = f" url={url}" if url else (" [callback]" if getattr(btn, "data", None) else "")
                print(f"   button [{r},{c}]: {btn.text!r}{kind}")


async def _dump(client, bot, n: int) -> None:
    msgs = await client.get_messages(bot, limit=n)
    for m in reversed(msgs):
        _print_message(m)


async def cmd_login(args) -> None:
    client, _ = make_client()
    phone = os.environ.get("TG_PHONE", "").strip() or None
    await client.start(phone=(lambda: phone) if phone else (lambda: input("Phone (+country code): ")))
    me = await client.get_me()
    print(f"Logged in as @{me.username or me.first_name} (id {me.id}). Session saved.")
    await client.disconnect()


async def cmd_whoami(args) -> None:
    client, bot = make_client()
    await client.connect()
    if not await client.is_user_authorized():
        print("Not logged in. Run: pg.py login")
    else:
        me = await client.get_me()
        print(f"Logged in as @{me.username or me.first_name} (id {me.id}); target bot: @{bot}")
    await client.disconnect()


async def cmd_dump(args) -> None:
    client, bot = make_client()
    await client.connect()
    await _dump(client, bot, args.n)
    await client.disconnect()


async def cmd_send(args) -> None:
    client, bot = make_client()
    await client.connect()
    m = await client.send_message(bot, args.text)
    print(f"sent msg {m.id}: {args.text!r}")
    await asyncio.sleep(args.wait)
    print("\n=== bot reply ===")
    await _dump(client, bot, 3)
    await client.disconnect()


async def cmd_click(args) -> None:
    client, bot = make_client()
    await client.connect()
    msg = await client.get_messages(bot, ids=args.msg_id)
    if msg is None:
        print(f"message {args.msg_id} not found")
        await client.disconnect()
        return
    try:
        res = await msg.click(args.row, args.col)
        print(f"clicked [{args.row},{args.col}] -> {getattr(res, 'message', res)}")
    except Exception as exc:  # noqa: BLE001
        print(f"click failed: {exc}")
    await asyncio.sleep(args.wait)
    print("\n=== bot state after click ===")
    await _dump(client, bot, 3)
    await client.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyGun Telegram userbot controller.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("whoami")
    d = sub.add_parser("dump"); d.add_argument("--n", type=int, default=5)
    s = sub.add_parser("send"); s.add_argument("text"); s.add_argument("--wait", type=float, default=3.0)
    c = sub.add_parser("click")
    c.add_argument("msg_id", type=int); c.add_argument("row", type=int); c.add_argument("col", type=int)
    c.add_argument("--wait", type=float, default=3.0)
    args = ap.parse_args()

    handler = {"login": cmd_login, "whoami": cmd_whoami, "dump": cmd_dump,
               "send": cmd_send, "click": cmd_click}[args.cmd]
    asyncio.run(handler(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
