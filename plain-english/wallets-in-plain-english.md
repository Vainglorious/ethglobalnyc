# How the ants get wallets and money, in plain English

*For the product side. This is about where each ant's money lives.*

## The setup
Every ant needs its own "bank account" (a crypto wallet) to hold its USDC, place stakes, and pass
money to its children. We need to be able to create **lots** of these, fast, and move money
between them.

## One treasury, no faucet-chasing
We have a single **treasury wallet** with 20 test-USDC in it. That's our whole bankroll for the
hackathon — we decided **not** to keep topping up from faucets. Everything downstream (ant
wallets, private transfers) gets funded *from the treasury*. One source of truth for the money.

## Two kinds of wallet, and why
We tested a service called **Dynamic** that can create wallets in bulk:
- We spun up **10 wallets in about 3.5 seconds** — so making "tens of ants" is no problem.
- These are **managed** wallets: there's no password file that can leak, and a **real human can
  later "claim"** one by logging in. That's a neat fit for our Worldcoin idea — a verified human
  can own a verified family line of ants.

The trade-off: with managed wallets, signing a transaction has to go *through* Dynamic's service
(not instant/local). So we'll likely use a **hybrid**:
- **Managed wallets** for the important, human-backed "founder" ants.
- **Simple local wallets** (fast, we hold the key) for cheap throwaway ants.

## It all connects
We proved money can flow across the whole stack in one go: **treasury → a managed ant wallet →
into the private-transfer layer → on to another ant** — all in a single automated run. The pieces
fit together.

## One lesson we learned the hard way
If we create a managed wallet and want to use it again later, we have to **save its "handle"** at
creation time — otherwise we can't get back into it and any money inside is stuck. (We left about
$2 parked in a couple of test wallets this way; not worth recovering, but a clear note for how we
build the real thing.)

## One-line summary
**One treasury funds everything; we can mint ant wallets in bulk, mix human-claimable managed
wallets with cheap local ones, and we've shown money flowing cleanly across the whole system.**
