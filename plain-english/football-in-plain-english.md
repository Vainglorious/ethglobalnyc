# Football, in plain English — and where WE need YOU

*For our football expert. You know the game better than the engineering team ever will.
This doc gives you the system basics, then asks you to fill in the football nuance. The
sections marked ✍️ YOUR CALL are where your knowledge directly makes the product smarter.*

## The deal
We built a colony of little betting "agents" that wager play-money on football matches and
evolve — good forecasters breed, bad ones go broke (see `colony-in-plain-english.md`). The
engineers built the *machine*. **You bring the football.** Right now the agents are naive
about the game; your job is to tell us what actually predicts results so we can wire it in.

## How a match becomes a bet in our system
For each match there's a lifecycle our agents ride:
1. A **betting market opens** (odds exist — e.g. from prediction markets / bookmakers).
2. Agents **buy data** and form a view on the outcome.
3. Agents **place a stake** on a side.
4. **Kick-off → full-time → result.**
5. **Settle:** correct agents get paid, wrong ones lose.

For the demo we need matches where that *whole* cycle happens in our window. Our shortlist
this weekend (from the notes):
- **Qatar vs Switzerland** — Sat 13 Jun, Levi's Stadium
- **Brazil vs Morocco** — Sat 13 Jun, MetLife Stadium
- **Haiti vs Scotland** — Sat 13 Jun (late), Gillette Stadium

✍️ **YOUR CALL:** Which of these is the best showcase match, and why? Which is a likely
blowout vs. a genuine coin-flip? Any you'd add or drop?

## The thing we most need you to police: "smart" vs "lucky"
Our headline claim is that the agents can **beat the market**, not just **pick the favourite**.
Backing Brazil to beat a minnow and being right isn't skill — the market already knew that.
Skill is spotting when the market's price is *wrong*.

✍️ **YOUR CALL:** Give us a few concrete examples of matches/situations where the betting
market tends to be mispriced — i.e. where a knowledgeable fan would disagree with the odds.
That's the gold we want the agents to learn to find.

## The football nuances the engineers probably got wrong
A few things US-centric engineers tend to miss. Confirm/correct these and add your own:

1. **Football has draws.** It's a **three-way** market (Home / Draw / Away), not win/lose.
   ✍️ How should agents think about the draw? When is a draw genuinely likely (and underpriced)?
2. **Low-scoring, high-variance.** One goal decides everything; the better team loses all the
   time. ✍️ How much should an agent "trust the favourite" given this randomness?
3. **It's not just match-winner.** There are markets for over/under goals, both-teams-to-score,
   handicaps, correct score, to-qualify, outright winner, top scorer…
   ✍️ **YOUR CALL:** Which markets are (a) most liquid/real and (b) most interesting for our
   agents to bet — match-winner only, or should we add over/under, BTTS, etc.?

## Signals: what actually predicts a result?
The engineers can feed the agents almost any data, but they don't know what *matters*. Rank
these for us and add what's missing:

| Signal | Does it matter? (you tell us) |
|---|---|
| Recent form / momentum | ✍️ |
| Head-to-head history | ✍️ |
| Home advantage / neutral venue | ✍️ (World Cup is on neutral-ish US grounds — does that change things?) |
| Injuries / suspensions / rotated lineups | ✍️ |
| Fixture congestion / fatigue | ✍️ |
| Motivation (already qualified? must-win? dead rubber?) | ✍️ |
| Weather / heat / travel | ✍️ |
| Style match-ups (e.g. high press vs. low block) | ✍️ |
| Manager / tactical setup | ✍️ |
| Market movement (odds drifting/shortening) | ✍️ |

✍️ **YOUR CALL:** If you could only give the agents **three** signals, which three, and roughly
how would you weight them?

## How an agent "thinks" (in football terms)
Each agent has a few dials it inherits and mutates. In plain football language:
- **How big it bets** — bankroll-betting punter vs. cautious accumulator.
- **How big an edge it needs before betting at all** — only bets when it strongly disagrees
  with the market, vs. bets on thin edges.
- **How much it trusts the crowd** — contrarian who fades the public vs. follows the money.
✍️ **YOUR CALL:** Do these match how *real* sharp bettors think? What's missing — what would a
genuinely sharp football bettor's "dials" be?

## The data we already have (rough)
- Prediction-market data (market prices / implied odds over time).
- Match results.
✍️ **YOUR CALL:** What football data do you wish we had that we probably don't? (lineups,
xG, in-play odds, etc.) Flag the ones that would most move the needle — we'll chase them.

## What we need back from you (the starting block)
Don't overthink format — bullet answers under the ✍️ prompts are perfect. Priorities:
1. Best demo match(es) this weekend + what you'd expect to happen.
2. Your top 3 predictive signals and rough weights.
3. Which betting markets we should support (match-winner only, or more).
4. A couple of "market is probably mispriced here" examples — the agents' learning target.
5. Anything the engineers obviously got wrong about how football actually works.

This is the seam where domain knowledge beats engineering. Fill in the blanks and the whole
colony gets smarter.
