# How the ants actually place bets, in plain English

*For the product/football side. This is about the "money goes down on a real match" part.*

## What we're trying to do
When an ant decides "Switzerland will win," we want that decision to turn into a **real bet on a
real prediction market** (Polymarket) — not a pretend one. That's what makes the whole economy
honest: a wrong bet really loses money.

## The wall we hit
Polymarket **won't let people in the US trade directly.** We wrote the code, it built a real $2
bet on "France to win the World Cup," and Polymarket bounced it with a "trading is restricted in
your region" error. We're in New York, so the front door is closed to us.

## The way in: a bot called PolyGun
**PolyGun** is a third-party service that places Polymarket bets *on your behalf* from a location
that isn't blocked. So for us it's not a shortcut — it's the **only door that opens**.

The trade-off: PolyGun **holds the money for you** (like a betting account you top up), instead of
you holding it in your own wallet. You can put money in and take it out, but only through
PolyGun's own "withdraw" button — you can't grab it back yourself. So we keep the amounts small
and treat it like a custodial account.

## The big win: it's fully automated, and the bets are real
We proved that **our code can place a real bet with no human clicking anything** — it drove
PolyGun start-to-finish and bought $2 of "France" shares. We checked the blockchain afterwards:
the position is a genuine Polymarket holding that will pay out if France wins. So:

> **Colony decides → our code places the bet on PolyGun → a real Polymarket position exists.**

## The live demo moment (Saturday's 3pm match)
For **Qatar vs. Switzerland** we plan to bet at three moments to show the colony reacting in real
time:
- **Before kickoff** — bet if the colony disagrees with the market's price.
- **During the game** — prices swing wildly on goals; the colony re-thinks and bets the gap. This
  is where the biggest edge is.
- **Right after the final whistle** — a brief window before the market officially settles.

## Two honest caveats
- **Real money, no test mode.** Polymarket is live-only — every "test" bet is a tiny *real* bet.
  We have strict safety guards and keep stakes at a couple of dollars.
- **The assistant won't move money on its own.** It only places a bet when a person explicitly
  says "do the $X bet on this side now." No surprise spending.

## One-line summary
**US users can't bet on Polymarket directly, so we use PolyGun to do it for us — and we've already
proven our code can place a real, automated bet that the colony's brain decided on.**
