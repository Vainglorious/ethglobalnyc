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
  snapshot [--n N]       write the last N bot messages + buttons as JSON for
                         read-only Colony KG enrichment
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
import json
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


def _buttons(msg):
    markup = getattr(msg, "reply_markup", None)
    rows = getattr(markup, "rows", None) if markup else None
    out = []
    if rows:
        for r, row in enumerate(rows):
            for c, btn in enumerate(row.buttons):
                out.append(f"[{r},{c}]={btn.text!r}")
    return ", ".join(out) or "(no buttons)"


def _message_to_dict(m) -> dict:
    buttons = []
    markup = getattr(m, "reply_markup", None)
    rows = getattr(markup, "rows", None) if markup else None
    if rows:
        for r, row in enumerate(rows):
            for c, btn in enumerate(row.buttons):
                buttons.append(
                    {
                        "row": r,
                        "col": c,
                        "text": btn.text,
                        "url": getattr(btn, "url", None),
                        "callback": bool(getattr(btn, "data", None)),
                    }
                )
    return {
        "id": m.id,
        "out": bool(m.out),
        "text": m.text or "",
        "date": str(getattr(m, "date", "") or ""),
        "buttons": buttons,
    }


def _find_button(msg, keywords):
    """Return (row, col, label) of the first inline button whose text contains
    any keyword (case-insensitive)."""
    markup = getattr(msg, "reply_markup", None)
    rows = getattr(markup, "rows", None) if markup else None
    if not rows:
        return None
    for r, row in enumerate(rows):
        for c, btn in enumerate(row.buttons):
            text = (btn.text or "").lower()
            if any(k in text for k in keywords):
                return r, c, btn.text
    return None


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


async def cmd_snapshot(args) -> None:
    """Write recent bot messages and inline buttons as JSON for read-only scouts."""
    client, bot = make_client()
    await client.connect()
    msgs = await client.get_messages(bot, limit=args.n)
    payload = {
        "bot": bot,
        "messages": [_message_to_dict(m) for m in reversed(msgs)],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"wrote snapshot: {out}")
    else:
        print(text, end="")
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


async def cmd_buy(args) -> None:
    """Automated market buy: open market -> Buy Yes/No -> custom amount -> type
    amount -> confirm. Dry-run by default (stops at the confirm button); pass
    --confirm to actually fire the trade."""
    client, bot = make_client()
    await client.connect()
    refcode = args.refcode or os.environ.get("PG_REFCODE", "vaingloriouseth")

    async def latest():
        msgs = await client.get_messages(bot, limit=1)
        return msgs[0] if msgs else None

    async def click_kw(msg, kws, what):
        b = _find_button(msg, kws)
        if not b:
            raise SystemExit(f"button for '{what}' not found. buttons: {_buttons(msg)}")
        r, c, label = b
        await msg.click(r, c)
        print(f"  clicked {what}: [{r},{c}] {label!r}")
        await asyncio.sleep(args.wait)
        return await latest()

    print(f"Opening market m_{args.market} (refcode {refcode})...")
    await client.send_message(bot, f"/start ref_{refcode}__m_{args.market}")
    await asyncio.sleep(args.wait)
    panel = await latest()
    _print_message(panel)

    side_kw = "buy yes" if args.side.lower() == "yes" else "buy no"
    amt_panel = await click_kw(panel, (side_kw,), f"Buy {args.side}")
    _print_message(amt_panel)

    prompt = await click_kw(amt_panel, ("custom",), "Enter custom amount")
    _print_message(prompt)

    # IMPORTANT: PolyGun MARKET buys have NO confirm step — sending the amount
    # immediately executes the trade. So the dry-run must stop BEFORE this.
    if not args.confirm:
        print(f"\nDRY RUN — reached the amount prompt. Sending '{args.amount}' would "
              f"IMMEDIATELY execute a ${args.amount} {args.side.upper()} market buy "
              f"(no confirm step exists). Re-run with --confirm to fire.")
        await client.disconnect()
        return

    print(f"  sending amount: {args.amount}  (this fires the market buy)")
    await client.send_message(bot, str(args.amount))
    await asyncio.sleep(args.wait)
    result = await latest()
    _print_message(result)
    tx_line = next((ln for ln in (result.text or "").splitlines() if "0x" in ln), "")
    print(f"\nDone. {tx_line.strip() or 'See result above.'}")
    await client.disconnect()


def main() -> int:
    ap = argparse.ArgumentParser(description="PolyGun Telegram userbot controller.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("whoami")
    d = sub.add_parser("dump"); d.add_argument("--n", type=int, default=5)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--n", type=int, default=8)
    snap.add_argument("--out", default="polygun/snapshots/latest.json")
    s = sub.add_parser("send"); s.add_argument("text"); s.add_argument("--wait", type=float, default=3.0)
    c = sub.add_parser("click")
    c.add_argument("msg_id", type=int); c.add_argument("row", type=int); c.add_argument("col", type=int)
    c.add_argument("--wait", type=float, default=3.0)
    b = sub.add_parser("buy")
    b.add_argument("--market", required=True, help="PolyGun market id, e.g. 558936 (France-to-win)")
    b.add_argument("--side", default="yes", choices=["yes", "no"])
    b.add_argument("--amount", required=True, help="USD/pUSD to spend, e.g. 2")
    b.add_argument("--refcode", default=None, help="referral handle in deep links (default from PG_REFCODE)")
    b.add_argument("--confirm", action="store_true", help="actually fire the trade (else dry-run)")
    b.add_argument("--wait", type=float, default=3.5)
    args = ap.parse_args()

    handler = {"login": cmd_login, "whoami": cmd_whoami, "dump": cmd_dump, "snapshot": cmd_snapshot,
               "send": cmd_send, "click": cmd_click, "buy": cmd_buy}[args.cmd]
    asyncio.run(handler(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
