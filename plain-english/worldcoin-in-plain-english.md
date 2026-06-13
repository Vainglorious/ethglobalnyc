# Worldcoin / "proving a real human is behind an agent," in plain English

*For the product side. This covers what we built and tested on 2026-06-12/13.*

## The problem we're solving
Anyone can spin up a thousand bots. For our experiment to mean anything, we need to prove
that a **real, unique human** stands behind a family line of ants. Worldcoin's **World ID**
does exactly that: it's the "prove you're a real person, once" system (you verify in the
World App on your phone).

## The two things people confuse (and the simple truth)
There are two separate identities, and mixing them up is the main source of confusion:

1. **The agent's wallet** — just a digital account we create for an ant. We make these
   ourselves; they have nothing to do with Worldcoin. An ant can have its own.
2. **The human's World ID** — *you*, the real person. This is **never stored in a file or a
   password.** You prove it live by approving on your phone in the World App.

So "connecting an agent to a human" is not pasting a credential anywhere — it's **you tapping
"approve" in the World App** for that agent. That tap is the whole binding.

## What we actually tested (and it worked)
1. We created a throwaway agent account.
2. Adil ran one command and approved it in the World App.
3. The system then confirmed: this account is **registered = backed by a real human**, and it
   handed us an anonymous tag for that human (a "humanId").

Then we did the important test: we made a **second** agent account and Adil approved it too.
Result — **it came back with the exact same human tag as the first one.**

## The single most important takeaway
> **One real person = one human tag, forever — no matter how many agent accounts they make.**

This is by design (the entire point of "proof of personhood"). It means:
- You **cannot** fake being many people. Ten accounts you verify are still just *you*.
- So we should **not** make a human approve every single ant (that's hundreds of pointless
  phone taps, and they'd all collapse to the same person anyway).
- Instead, **one human approval = one verified family line.** The founder is human-backed,
  and we mark all its descendants as "verified" in our own records. Kids don't need their own
  phone approval.

## Why this is good news for the product
- **The headline experiment is real.** "Verified family lines vs. anonymous ones" is a true
  apples-to-oranges comparison, because we genuinely can't manufacture fake humans.
- **It's low-friction.** A human taps approve a handful of times (once per real person we
  recruit), not hundreds. Easy to demo.
- **It's privacy-safe.** We never learn who the person is — just an anonymous "same human"
  tag. Good story for judges and users.

## Honest caveats (so we don't oversell)
- The number of *truly* verified family lines is limited by how many **real humans** we can
  get to tap approve at the event. If we want more lines for a fuller chart, we add simulated
  ones and **clearly label them as simulated.**
- A couple of plumbing details are still open (which network things settle on, and one
  efficiency trick for signing), but none of them threaten the core idea — the part that
  could have sunk the design is already proven to work.

## One-line summary
**We can prove a real human stands behind a family line with a single phone tap — and we've
confirmed you can't fake being more than one person, which is exactly what makes our headline
experiment honest.**
