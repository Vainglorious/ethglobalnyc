"""Voice models for debate speakers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .genes import Genome
from .models import DebateClaim, MatchContext, Side


def _text_from_openai_message(data: dict) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected LLM response shape: {data}") from exc

    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content.strip()
        if text:
            return text
    if isinstance(content, list):
        text_parts = [
            str(part.get("text", "")).strip()
            for part in content
            if isinstance(part, dict) and part.get("type") in {None, "text"}
        ]
        joined = " ".join(part for part in text_parts if part)
        if joined:
            return joined

    refusal = message.get("refusal") if isinstance(message, dict) else None
    if refusal:
        raise RuntimeError(f"LLM refused to render claim: {refusal}")
    raise RuntimeError(f"LLM returned empty message content: {data}")


def _format_llm_claim(
    *,
    agent_name: str,
    match: MatchContext,
    probability: float,
    direction: Side,
    rationale: str,
) -> str:
    cleaned = _clean_voice_output(rationale, agent_name=agent_name)
    if not cleaned or cleaned.lower() == "none":
        raise RuntimeError("LLM returned empty rationale")
    return cleaned


def _clean_voice_output(text: str, *, agent_name: str) -> str:
    cleaned = " ".join(text.strip().strip('"').strip("'").split())
    prefixes = (
        f"{agent_name}:",
        f"{agent_name} -",
        "Agent:",
        "Predictor:",
        "Debater:",
        "Reply:",
    )
    for prefix in prefixes:
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix) :].strip()
            break
    return cleaned


def _format_evidence_line(evidence: dict) -> str:
    claim_type = str(evidence.get("claim_type") or "claim").replace("_", " ")
    subject = str(evidence.get("subject") or evidence.get("team") or "unknown")
    claim = str(evidence.get("claim") or "").strip()
    source = str(evidence.get("source_title") or evidence.get("scout_name") or "source")
    confidence = evidence.get("confidence")
    confidence_text = f", confidence {float(confidence):.2f}" if isinstance(confidence, int | float) else ""
    return f"- {claim_type}: {subject}: {claim} ({source}{confidence_text})"


def _compact_evidence(evidence_claims: list[dict], limit: int = 3) -> str:
    if not evidence_claims:
        return "- no structured evidence claims visible"
    return "\n".join(_format_evidence_line(evidence) for evidence in evidence_claims[:limit])


def _compact_prior_claims(prior_claims: list[DebateClaim], limit: int = 2) -> str:
    if not prior_claims:
        return "- no previous public claims"
    compact = []
    for claim in prior_claims[-limit:]:
        compact.append(f"- {claim.speaker_name}: {claim.stated_home_probability:.1%} home; {claim.message}")
    return "\n".join(compact)


def _compact_dispute(dispute: dict) -> str:
    if not dispute:
        return "- no structured dispute target"
    fields = [
        ("target speaker", dispute.get("target_speaker_name") or dispute.get("target_speaker_id")),
        ("critique type", str(dispute.get("critique_type") or "").replace("_", " ")),
        ("target subject", dispute.get("target_subject")),
        ("counter subject", dispute.get("counter_subject")),
        ("target excerpt", dispute.get("target_excerpt")),
    ]
    lines = [f"- {label}: {value}" for label, value in fields if value]
    return "\n".join(lines) if lines else "- no structured dispute target"


def _build_rationale_prompt(
    *,
    agent_name: str,
    genome: Genome,
    match: MatchContext,
    probability: float,
    direction: Side,
    evidence_claims: list[dict],
    prior_claims: list[DebateClaim],
    debate_role: str,
    debate_phase: str,
    dispute: dict | None = None,
) -> str:
    dispute_text = _compact_dispute(dispute or {})
    return (
        "Write only a short conversational reply for a forecasting predictor in an agent debate.\n"
        "You may mention injuries, players, lineups, tactics, or source disagreement only if present in the allowed evidence below.\n"
        "Do not invent facts. Do not add new sources. Do not include the agent name.\n"
        "Do not mention other agents by ID or name; say 'that claim' or 'the previous claim' instead.\n"
        "Do not repeat the match name. Do not include percentages or probabilities.\n"
        "Do not use template phrases like 'the evidence I care about', 'my added value', 'I am fading', or 'my read gives'.\n"
        "Make it sound like a real person in a trading room: cite one concrete fact, and if useful, push back on the previous claim.\n"
        "Avoid stiff openings such as 'I would', 'I am', or 'my model' unless they sound natural in context.\n"
        "Prefer direct replies like 'Hold on', 'That part matters', 'I buy that, but', or 'The cleaner anchor is'.\n"
        "If the debate role is challenger, explicitly challenge source quality, evidence relevance, or impact size.\n"
        "If a structured dispute target is present, reply to that target rather than making a standalone claim.\n"
        "Keep it under 35 words. Write in English. Return one or two sentences.\n\n"
        f"Agent name: {agent_name}\n"
        f"Persona: {genome.persona}\n"
        f"Model species: {genome.model}\n"
        f"Match: {match.home_team} vs {match.away_team}\n"
        f"Market home probability: {match.market_home_probability:.3f}\n"
        f"Agent home probability: {probability:.3f}\n"
        f"Direction: {direction}\n\n"
        f"Debate phase: {debate_phase or 'final'}\n"
        f"Debate role: {debate_role or 'speaker'}\n\n"
        "Allowed evidence claims:\n"
        f"{_compact_evidence(evidence_claims)}\n\n"
        "Previous public claims:\n"
        f"{_compact_prior_claims(prior_claims)}\n\n"
        "Structured dispute target:\n"
        f"{dispute_text}\n"
    )


def _market_stance(*, match: MatchContext, probability: float, persona: str = "", seed: str = "") -> str:
    edge = probability - match.market_home_probability
    if abs(edge) < 0.006:
        return _choose(
            seed + ":stance-close",
            [
                f"I would mostly leave {match.home_team} where it is.",
                f"Not much to move on {match.home_team}.",
                "Small adjustment only.",
            ],
        )
    if edge > 0:
        if probability >= 0.5:
            return _choose(
                seed + ":stance-home-up",
                [
                    f"Slightly higher on {match.home_team} for me.",
                    f"The home price still looks light to me.",
                    f"I would nudge {match.home_team} up.",
                ],
            )
        return _choose(
            seed + ":stance-away-soft",
            [
                f"I still lean {match.away_team}, just less than the market mood.",
                f"I am not fully on {match.home_team}; I just think the market is too harsh.",
                f"The away side is still my lean, but not by that much.",
            ],
        )
    if probability >= 0.5:
        if "contrarian" in persona or "value" in persona:
            return _choose(
                seed + ":stance-home-overpriced-contrarian",
                [
                    f"{match.home_team} can be the favorite and still be overpriced.",
                    f"I still have {match.home_team} ahead, just not at this price.",
                    f"The favorite label is fine; the price is the issue.",
                ],
            )
        return _choose(
            seed + ":stance-home-overpriced",
            [
                f"{match.home_team} is still favored for me, but the price is too high.",
                f"I keep {match.home_team} in front, but I would trim the price.",
                f"I am not flipping sides; I am just cutting the favorite.",
            ],
        )
    return _choose(
        seed + ":stance-away",
        [
            f"I actually lean {match.away_team} here.",
            f"My lean is on {match.away_team}.",
            f"I would rather hold the {match.away_team} side here.",
        ],
    )


def _variant_index(seed: str, count: int) -> int:
    if count <= 1:
        return 0
    return sum(ord(char) for char in seed) % count


def _choose(seed: str, options: list[str]) -> str:
    return options[_variant_index(seed, len(options))]


def _clean_claim_text(text: str, limit: int = 58) -> str:
    cleaned = " ".join(text.strip().strip(".").split())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip(" .") + "..."


def _sentence_start(text: str) -> str:
    cleaned = str(text).strip()
    if not cleaned:
        return cleaned
    return cleaned[0].upper() + cleaned[1:]


def _has_concrete_evidence(evidence_claims: list[dict]) -> bool:
    if not evidence_claims:
        return False
    claim = str(evidence_claims[0].get("claim") or "").lower()
    if not claim:
        return False
    vague_markers = (
        "signal is there",
        "placeholder",
        "future",
        "no web",
        "no x/social",
    )
    return not any(marker in claim for marker in vague_markers)


def _punctuate(text: str) -> str:
    if text.endswith((".", "!", "?", "...")):
        return text
    return f"{text}."


def _limit_sentences(text: str, *, limit: int = 2) -> str:
    parts = []
    current = []
    for token in text.split():
        current.append(token)
        if token.endswith((".", "!", "?")):
            parts.append(" ".join(current).strip())
            current = []
            if len(parts) >= limit:
                break
    if current and len(parts) < limit:
        parts.append(" ".join(current).strip())
    return " ".join(part for part in parts if part)


def _source_label(evidence: dict) -> str:
    title = str(evidence.get("source_title") or "")
    url = str(evidence.get("source_url") or "")
    scout = str(evidence.get("scout_name") or "")
    source = title or scout or url
    if not source:
        source = "that source"
    return _short_source_name(source) or "that source"


def _source_quality_label(evidence: dict) -> str:
    source = str(evidence.get("source_title") or evidence.get("source_url") or evidence.get("scout_name") or "").lower()
    claim = str(evidence.get("claim") or "").lower()
    strong_markers = (
        "bbc",
        "espn",
        "rotowire",
        "reuters",
        "associated press",
        " ap ",
        "fifa",
        "the athletic",
        "sports illustrated",
    )
    weak_markers = (
        "prediction",
        "predictor",
        "pick",
        "betting",
        "odds",
        "tips",
        "worldcuppass",
        "wc26lineups",
        "wc26 lineups",
        "world cup squad",
        "squad – lineup",
        "squad - lineup",
        "lineup & players",
        "full 26-player roster",
    )
    generic_claim_markers = (
        "promising",
        "high expectations",
        "will be relied upon",
        "ability to compete",
        "key against",
    )
    if any(marker in source for marker in strong_markers):
        return "strong"
    if any(marker in source for marker in weak_markers):
        return "weak"
    if any(marker in claim for marker in generic_claim_markers):
        return "weak"
    return "medium"


def _evidence_brief(evidence: dict) -> str:
    subject = _subject_label(evidence)
    raw_subject = str(evidence.get("subject") or evidence.get("team") or subject)
    source = _source_label(evidence)
    claim_type = str(evidence.get("claim_type") or "")
    claim = str(evidence.get("claim") or "").lower()
    if claim_type == "injury_availability":
        if "ruled out" in claim:
            return f"{source} has {subject} ruled out"
        if "miss" in claim or "missing" in claim:
            return f"{source} has {subject} missing"
        if "not in the predicted starting xi" in claim or "not in predicted starting xi" in claim:
            return f"{source} has {subject} out of the expected XI"
        if "injury blow" in claim or "injury-hit" in claim:
            return f"{source} flags {subject}"
        return f"{source} flags {subject}"
    if claim_type == "recent_form":
        if "above the market anchor" in claim:
            return f"{source} has {raw_subject} above the market anchor"
        if "below the market anchor" in claim:
            return f"{source} has {raw_subject} below the market anchor"
        return f"{source} gives the {raw_subject} form line"
    if claim_type == "player_form":
        return f"{source} flags {subject}"
    if claim_type == "lineup":
        if "cleaner" in claim:
            return f"{source} says {raw_subject} is the cleaner lineup read"
        if "less stable" in claim:
            return f"{source} says {raw_subject} is less stable"
        if "small" in claim and "adjustment" in claim:
            return f"{source} gives {raw_subject} a small lineup adjustment"
        return f"{source} gives a lineup note on {raw_subject}"
    if claim_type == "market_preview":
        if "above the consensus home price" in claim:
            return f"{source} has {subject} above the consensus home price"
        if "below the consensus home price" in claim:
            return f"{source} has {subject} below the consensus home price"
        return f"{source} is mostly market context"
    return f"{source} points to {subject}"


def _subject_label(evidence: dict) -> str:
    subject = str(evidence.get("subject") or evidence.get("team") or "that point")
    claim_type = str(evidence.get("claim_type") or "")
    player = str(evidence.get("player") or "")
    if claim_type == "injury_availability" and not player and subject:
        return f"{subject} injury list"
    if claim_type == "recent_form" and subject:
        if "form" in subject.lower():
            return subject
        return f"{subject} form"
    if claim_type == "player_form" and subject:
        if "form" in subject.lower():
            return subject
        return f"{subject} form"
    return subject


def _is_evidence_aligned(evidence: dict, *, direction: Side) -> bool:
    impact = str(evidence.get("impact") or "")
    return (direction == "away" and impact == "negative_home") or (direction == "home" and impact == "negative_away")


def _template_evidence_sentence(evidence_claims: list[dict], *, direction: Side, seed: str = "") -> str:
    if not evidence_claims:
        return _choose(
            seed + ":no-evidence",
            [
                "I do not see a fresh fact strong enough to force the move.",
                "Without a cleaner input, I would keep the adjustment small.",
                "That is still thin; I need one concrete football reason before moving it.",
            ],
        )
    primary = evidence_claims[0]
    subject = _subject_label(primary)
    claim = str(primary.get("claim") or "").strip().rstrip(".")
    impact = str(primary.get("impact") or "")
    claim_type = str(primary.get("claim_type") or "").replace("_", " ")
    source = _source_label(primary)
    aligned = _is_evidence_aligned(primary, direction=direction)

    if claim:
        detail = _evidence_brief(primary)
        if claim_type == "injury availability":
            if aligned:
                if direction == "away":
                    lead = _choose(
                        seed + ":injury-away",
                        [
                            f"{subject} is where I start the haircut; {detail}.",
                            f"{detail}, so I cannot leave that risk flat.",
                            f"{subject} is the live drag for me; {detail}.",
                        ],
                    )
                else:
                    lead = _choose(
                        seed + ":injury-home",
                        [
                            f"{detail}, and that helps the home case.",
                            f"The cleaner home-side point is {subject}; {detail}.",
                            f"{subject} is the concrete availability edge; {detail}.",
                        ],
                    )
            else:
                lead = _choose(
                    seed + ":injury-counter",
                    [
                        f"{subject} is the hesitation; {detail}.",
                        f"I cannot ignore {subject}; {detail}.",
                        f"{detail}, so I keep the move smaller.",
                    ],
                )
        elif claim_type == "recent form":
            lead = _choose(
                seed + ":recent-form",
                [
                    f"Okay, this is the form point I care about: {detail}.",
                    f"Form is doing work here: {detail}. Still not enough to go blind.",
                    f"This is the useful bit on form: {detail}.",
                ],
            )
        elif claim_type == "player form":
            lead = _choose(
                seed + ":player-form",
                [
                    f"{subject} matters, but I am not letting one player note run the whole pick.",
                    f"I keep {subject} in the mix. Not the whole bet, but real.",
                    f"{subject} is a real input. I still want the team context next to it.",
                ],
            )
        elif claim_type == "market preview":
            lead = _choose(
                seed + ":market-preview",
                [
                    f"Market note is useful, but do not chase it: {detail}.",
                    f"I see the market point. It is context, not a free lunch: {detail}.",
                    f"Fine, but that may already be in the price: {detail}.",
                ],
            )
        else:
            lead = _choose(
                seed + ":generic-evidence",
                [
                    f"The useful detail is {subject}: {detail}.",
                    f"I keep circling {subject}: {detail}.",
                    f"Put {subject} on the board: {detail}.",
                ],
            )
    else:
        lead = _choose(
            seed + ":thin-evidence",
            [
                f"{subject} is relevant, but the claim is thin.",
                f"The {subject} angle needs a better source.",
                f"{subject} is on the board, just not strongly enough for a big move.",
            ],
        )

    if len(evidence_claims) < 2:
        return lead

    counter = evidence_claims[1]
    counter_subject = _subject_label(counter)
    counter_impact = str(counter.get("impact") or "")
    if direction == "away" and counter_impact == "negative_away":
        counter_line = _choose(
                seed + ":counter-away",
                [
                f"{counter_subject} pulls the other way, just not enough for me.",
                f"{counter_subject} is real. I just make it the smaller problem.",
                f"{counter_subject} offsets it, but does not take over.",
            ],
        )
        return f"{lead} {counter_line}"
    if direction == "home" and counter_impact == "negative_home":
        counter_line = _choose(
                seed + ":counter-home",
                [
                f"{counter_subject} is real. I still see more risk on the other side.",
                f"{counter_subject} trims the move. It does not kill it.",
                f"{counter_subject} keeps me cautious rather than bearish.",
            ],
        )
        return f"{lead} {counter_line}"
    if impact.startswith("negative"):
        counter_line = _choose(
            seed + ":negative-context",
            [
                "That is better than a generic preview.",
                "That beats another broad pre-match take.",
                "At least we have a real thing to argue about.",
            ],
        )
        return f"{lead} {counter_line}"
    return lead


def _short_source_name(source: str) -> str:
    cleaned = " ".join(source.split())
    lower = cleaned.lower()
    known_sources = (
        ("wc26lineups", "WC26 Lineups"),
        ("wc26 lineups", "WC26 Lineups"),
        ("bbc", "BBC"),
        ("espn", "ESPN"),
        ("rotowire", "RotoWire"),
        ("sports mole", "Sports Mole"),
        ("sports illustrated", "Sports Illustrated"),
        ("reuters", "Reuters"),
        ("associated press", "Associated Press"),
        ("fifa", "FIFA"),
        ("the athletic", "The Athletic"),
        ("boostmatch", "Boostmatch"),
    )
    for marker, label in known_sources:
        if marker in lower:
            return label
    if " - " in cleaned:
        tail = cleaned.rsplit(" - ", 1)[1].strip()
        if 2 <= len(tail) <= 32:
            return tail
    if " | " in cleaned:
        tail = cleaned.rsplit(" | ", 1)[1].strip()
        if 2 <= len(tail) <= 32:
            return tail
    if len(cleaned) <= 44:
        return cleaned
    return cleaned[:41].rstrip(" .") + "..."


def _template_prior_sentence(
    prior_claims: list[DebateClaim],
    probability: float,
    evidence_claims: list[dict],
    seed: str = "",
) -> str:
    if not prior_claims:
        return ""
    previous = prior_claims[-1]
    gap = probability - previous.stated_home_probability
    previous_evidence = previous.referenced_evidence[0] if previous.referenced_evidence else {}
    previous_subject = str(previous_evidence.get("subject") or previous_evidence.get("team") or "that point")
    if abs(gap) < 0.006:
        if evidence_claims:
            source = str(evidence_claims[0].get("source_title") or evidence_claims[0].get("scout_name") or "another source")
            short_source = _short_source_name(source)
            return _choose(
                seed + ":prior-close-source",
                [
                    f"Same neighborhood, but {short_source} is the part I would actually trade off.",
                    f"That is close to my number; I just trust the {short_source} input more.",
                    f"Not much separation there; {short_source} keeps me from pushing harder.",
                ],
            )
        return _choose(
            seed + ":prior-close",
            [
                "We are basically in the same area; I just do not see a sharper source.",
                "That is close enough for me, unless someone brings a cleaner fact.",
                "I cannot split that much from the previous point without better evidence.",
            ],
        )
    if gap > 0:
        return _choose(
            seed + ":prior-higher",
            [
                f"That leans too hard on {previous_subject}.",
                f"I buy the {previous_subject} concern, just not at that size.",
                f"The topic is right; the move is too aggressive.",
            ],
        )
    return _choose(
        seed + ":prior-lower",
        [
            f"I cut more than that; {previous_subject} still matters too much.",
            f"I am lower because {previous_subject} is doing real work here.",
            f"That is not bearish enough on the {previous_subject} angle.",
        ],
    )


def _template_challenge_sentence(
    prior_claims: list[DebateClaim],
    probability: float,
    evidence_claims: list[dict],
    dispute: dict | None = None,
    seed: str = "",
) -> str:
    structured = _template_structured_dispute_sentence(dispute or {}, seed=seed)
    if structured:
        return structured
    if not prior_claims:
        return _choose(
                seed + ":challenge-open",
                [
                "Show me the football reason before we move.",
                "I need one stronger fact before I follow that.",
                "Source first, pick second.",
            ],
        )

    previous = prior_claims[-1]
    previous_evidence = previous.referenced_evidence[0] if previous.referenced_evidence else {}
    current_evidence = evidence_claims[0] if evidence_claims else {}
    previous_subject = _subject_label(previous_evidence) if previous_evidence else "that point"
    current_subject = _subject_label(current_evidence) if current_evidence else ""
    previous_quality = _source_quality_label(previous_evidence) if previous_evidence else "medium"
    current_quality = _source_quality_label(current_evidence) if current_evidence else "medium"
    gap = probability - previous.stated_home_probability

    if previous_quality == "weak":
        return _choose(
            seed + ":challenge-weak-prior",
            [
                f"Hold on, {previous_subject} is coming from a broad preview, not hard team news.",
                f"That leans on {previous_subject}, but the source is too generic for a big move.",
                f"{previous_subject} should not drive the room if the anchor is just a squad page.",
            ],
        )
    if current_evidence and current_quality == "strong" and current_subject and current_subject != previous_subject:
        source = _source_label(current_evidence)
        return _choose(
            seed + ":challenge-strong-counter",
            [
                f"I would rather anchor on {current_subject}; {source} is cleaner than the previous source.",
                f"The previous topic is fair, but {current_subject} comes from the cleaner source.",
                f"Do not let {previous_subject} dominate before pricing {current_subject} from {source}.",
            ],
        )
    if current_subject and previous_subject and current_subject != previous_subject:
        return _choose(
                seed + ":challenge-counter-topic",
                [
                f"You are missing {current_subject}; {previous_subject} is not the whole match.",
                f"I buy part of {previous_subject}, but {current_subject} still has to count.",
                f"{previous_subject} matters. So does {current_subject}.",
            ],
        )
    if abs(gap) < 0.006:
        return _choose(
                seed + ":challenge-size-close",
                [
                f"Direction is fine, but {previous_subject} cannot carry the whole pick.",
                "Close, but the impact still feels too big.",
                f"Keep {previous_subject} on the board. Do not make it everything.",
            ],
        )
    if gap > 0:
        return _choose(
                seed + ":challenge-too-bearish",
                [
                f"Too much of a cut. {previous_subject} does not erase the other side.",
                "Right topic, too much damage.",
                "I like the angle. I do not like the size.",
            ],
        )
    return _choose(
                seed + ":challenge-not-bearish-enough",
                [
                f"I cut harder than that. {previous_subject} still feels underpriced.",
                "That names the risk, but barely moves for it.",
                f"The room is still too light on {previous_subject}.",
            ],
        )


def _template_structured_dispute_sentence(dispute: dict, *, seed: str = "") -> str:
    if not dispute:
        return ""
    target_subject = str(dispute.get("target_subject") or "").strip()
    counter_subject = str(dispute.get("counter_subject") or "").strip()
    critique_type = str(dispute.get("critique_type") or "")
    if critique_type == "source_quality":
        if counter_subject and target_subject and counter_subject != target_subject:
            return _choose(
                seed + ":structured-source-quality-shift",
                [
                    f"I would not anchor on {target_subject}; {counter_subject} is the cleaner source fight.",
                    f"That {target_subject} point needs a better source before it beats {counter_subject}.",
                    f"Source quality is the issue: {counter_subject} is cleaner than {target_subject}.",
                ],
            )
        subject = target_subject or counter_subject or "that point"
        return _choose(
            seed + ":structured-source-quality",
            [
                f"Hold on, {subject} needs a cleaner source before it drives the room.",
                "The topic may be right, but the source quality is not enough.",
                f"I want a better source for {subject} before moving price.",
            ],
        )
    if critique_type == "counter_evidence":
        if target_subject and counter_subject and target_subject != counter_subject:
            target_start = _sentence_start(target_subject)
            return _choose(
                seed + ":structured-counter-evidence",
                [
                    f"I buy part of {target_subject}, but {counter_subject} is the live counterweight.",
                    f"{target_start} is not the whole trade; {counter_subject} still has to be priced.",
                    f"The room cannot price {target_subject} without netting it against {counter_subject}.",
                ],
            )
        subject = counter_subject or target_subject or "that point"
        return _choose(
            seed + ":structured-counter-same",
            [
                f"I agree {subject} matters; I just do not buy the size of the move.",
                f"{subject} stays on the board, but it should not carry everything.",
                f"The disagreement is not {subject}; it is how much to move for it.",
            ],
        )
    if critique_type == "impact_size":
        subject = target_subject or counter_subject or "that point"
        return _choose(
            seed + ":structured-impact-size",
            [
                f"{subject} matters, just not enough to own the whole number.",
                f"The topic is fine; the impact size is where I push back.",
                f"Keep {subject} in the mix, just with a smaller move.",
            ],
        )
    if critique_type == "underpriced_home":
        subject = target_subject or counter_subject or "that risk"
        return _choose(
            seed + ":structured-underpriced-home",
            [
                f"That cut is too large; {subject} does not erase the other side.",
                f"I push back on how much we cut for {subject}, not on the topic itself.",
                f"{subject} matters, but I still think the home side is light.",
            ],
        )
    if critique_type == "overpriced_home":
        subject = target_subject or counter_subject or "that risk"
        return _choose(
            seed + ":structured-overpriced-home",
            [
                f"I cut harder than that; {subject} is still underpriced.",
                "The previous claim names the risk, but does not move enough for it.",
                f"The room is still light on {subject}.",
            ],
        )
    return ""


def _template_role_sentence(debate_role: str, *, direction: Side, match: MatchContext, seed: str = "") -> str:
    if debate_role == "advocate":
        return ""
    if debate_role == "challenger":
        return _choose(
            seed + ":role-challenger",
            [
                "I do not buy the leap yet.",
                "That feels one step too far for me.",
                "Slow down before moving the price that much.",
            ],
        )
    if debate_role == "source_auditor":
        return _choose(
            seed + ":role-auditor",
            [
                "Separate the story from the source quality first.",
                "The source matters as much as the headline here.",
                "Before moving price, I want the cleaner source.",
            ],
        )
    if debate_role == "skeptic":
        return _choose(
            seed + ":role-skeptic",
            [
                "This feels more like wider uncertainty than a clean side.",
                "I would widen the band before I pick a side.",
                "The signal is real, but the confidence is not.",
            ],
        )
    if debate_role == "room_representative":
        return ""
    return ""


def _compose_template_claim(
    *,
    agent_name: str,
    genome: Genome,
    match: MatchContext,
    probability: float,
    direction: Side,
    evidence_claims: list[dict],
    prior_claims: list[DebateClaim],
    debate_role: str,
    debate_phase: str,
    dispute: dict | None = None,
) -> str:
    seed = f"{agent_name}:{genome.persona}:{debate_role}:{debate_phase}:{len(prior_claims)}"
    stance = _market_stance(match=match, probability=probability, persona=genome.persona, seed=seed)
    evidence = _template_evidence_sentence(evidence_claims, direction=direction, seed=seed)
    prior = _template_prior_sentence(prior_claims, probability, evidence_claims, seed=seed)
    role = _template_role_sentence(debate_role, direction=direction, match=match, seed=seed)
    challenge = _template_challenge_sentence(prior_claims, probability, evidence_claims, dispute, seed=seed)
    concrete_evidence = _has_concrete_evidence(evidence_claims)

    layouts = {
        "advocate": [
            [stance, evidence],
            [evidence],
            [evidence],
            [evidence, prior],
        ],
        "challenger": [
            [challenge, evidence if concrete_evidence else ""],
            [challenge, prior or evidence],
            [evidence if concrete_evidence else "", challenge],
        ],
        "source_auditor": [
            [challenge or role, evidence if concrete_evidence else ""],
            [evidence if concrete_evidence else "", challenge or prior or role],
            [challenge or prior or role, evidence],
        ],
        "skeptic": [
            [role, evidence],
            [prior or evidence, role],
            [evidence, role],
        ],
        "room_representative": [
            [evidence, prior],
            [prior, evidence],
            [evidence],
        ],
    }
    options = layouts.get(debate_role) or [[stance, evidence], [evidence, prior], [prior, evidence]]
    selected = options[_variant_index(seed + ":layout", len(options))]
    parts = [part for part in selected if part]
    if not parts:
        parts = [stance]
    message = " ".join(parts)
    return _limit_sentences(_clean_voice_output(message, agent_name=agent_name), limit=2)


class VoiceModel(Protocol):
    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
        evidence_claims: list[dict] | None = None,
        prior_claims: list[DebateClaim] | None = None,
        debate_role: str = "",
        debate_phase: str = "final",
        dispute: dict | None = None,
    ) -> str:
        """Render the public debate message for a speaker."""


@dataclass
class TemplateVoiceModel:
    """Deterministic local voice model used by default."""

    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
        evidence_claims: list[dict] | None = None,
        prior_claims: list[DebateClaim] | None = None,
        debate_role: str = "",
        debate_phase: str = "final",
        dispute: dict | None = None,
    ) -> str:
        return _compose_template_claim(
            agent_name=agent_name,
            genome=genome,
            match=match,
            probability=probability,
            direction=direction,
            evidence_claims=evidence_claims or [],
            prior_claims=prior_claims or [],
            debate_role=debate_role,
            debate_phase=debate_phase,
            dispute=dispute,
        )


@dataclass
class OpenAICompatibleVoiceModel:
    """LLM-backed speaker voice using an OpenAI-compatible chat API."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 30
    referer: str = ""
    title: str = ""
    disable_reasoning: bool = False

    @classmethod
    def from_env(cls) -> "OpenAICompatibleVoiceModel":
        api_key = os.environ.get("COLONY_LLM_API_KEY", "").strip()
        base_url = os.environ.get("COLONY_LLM_BASE_URL", "").strip()
        model = os.environ.get("COLONY_LLM_MODEL", "MiniMax-M3").strip()
        timeout = int(os.environ.get("COLONY_LLM_TIMEOUT_SECONDS", "30"))

        if not api_key:
            raise ValueError("COLONY_LLM_API_KEY is missing")
        if not base_url:
            raise ValueError("COLONY_LLM_BASE_URL is missing")
        if not model:
            raise ValueError("COLONY_LLM_MODEL is missing")

        return cls(api_key=api_key, base_url=base_url.rstrip("/"), model=model, timeout_seconds=timeout)

    @classmethod
    def from_openrouter_env(cls) -> "OpenAICompatibleVoiceModel":
        api_key = (
            os.environ.get("OPENROUTER_API_KEY", "").strip()
            or os.environ.get("COLONY_LLM_API_KEY", "").strip()
        )
        base_url = os.environ.get("COLONY_LLM_BASE_URL", "https://openrouter.ai/api/v1").strip()
        model = os.environ.get("COLONY_LLM_MODEL", "deepseek/deepseek-v4-flash").strip()
        timeout = int(os.environ.get("COLONY_LLM_TIMEOUT_SECONDS", "30"))
        referer = os.environ.get("OPENROUTER_HTTP_REFERER", "").strip()
        title = os.environ.get("OPENROUTER_APP_TITLE", "Colony Harness").strip()

        if not api_key:
            raise ValueError("OPENROUTER_API_KEY or COLONY_LLM_API_KEY is missing")
        if not base_url:
            raise ValueError("COLONY_LLM_BASE_URL is missing")
        if not model:
            raise ValueError("COLONY_LLM_MODEL is missing")

        return cls(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            timeout_seconds=timeout,
            referer=referer,
            title=title,
            disable_reasoning=True,
        )

    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
        evidence_claims: list[dict] | None = None,
        prior_claims: list[DebateClaim] | None = None,
        debate_role: str = "",
        debate_phase: str = "final",
        dispute: dict | None = None,
    ) -> str:
        prompt = _build_rationale_prompt(
            agent_name=agent_name,
            genome=genome,
            match=match,
            probability=probability,
            direction=direction,
            evidence_claims=evidence_claims or [],
            prior_claims=prior_claims or [],
            debate_role=debate_role,
            debate_phase=debate_phase,
            dispute=dispute,
        )

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the voice layer for a bounded prediction-colony debate feed. "
                        "Always return a non-empty plain-text sentence."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.5,
            "max_tokens": 180,
        }
        if self.disable_reasoning:
            payload["reasoning"] = {"effort": "none", "exclude": True}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.referer:
            headers["HTTP-Referer"] = self.referer
        if self.title:
            headers["X-OpenRouter-Title"] = self.title

        request = urllib.request.Request(
            url=f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"LLM voice call failed: HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"LLM voice call failed: {exc}") from exc

        return _format_llm_claim(
            agent_name=agent_name,
            match=match,
            probability=probability,
            direction=direction,
            rationale=_text_from_openai_message(data),
        )


@dataclass
class MiniMaxVoiceModel:
    """MiniMax native text chat API used by the official mmx CLI."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 30

    @property
    def messages_url(self) -> str:
        if self.base_url.endswith("/anthropic"):
            return f"{self.base_url}/v1/messages"
        return f"{self.base_url}/anthropic/v1/messages"

    @classmethod
    def from_env(cls) -> "MiniMaxVoiceModel":
        api_key = os.environ.get("COLONY_LLM_API_KEY", "").strip()
        base_url = os.environ.get("COLONY_LLM_BASE_URL", "https://api.minimax.io").strip()
        model = os.environ.get("COLONY_LLM_MODEL", "MiniMax-M3").strip()
        timeout = int(os.environ.get("COLONY_LLM_TIMEOUT_SECONDS", "30"))

        if not api_key:
            raise ValueError("COLONY_LLM_API_KEY is missing")
        if not base_url:
            raise ValueError("COLONY_LLM_BASE_URL is missing")
        if not model:
            raise ValueError("COLONY_LLM_MODEL is missing")

        return cls(api_key=api_key, base_url=base_url.rstrip("/"), model=model, timeout_seconds=timeout)

    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
        evidence_claims: list[dict] | None = None,
        prior_claims: list[DebateClaim] | None = None,
        debate_role: str = "",
        debate_phase: str = "final",
        dispute: dict | None = None,
    ) -> str:
        prompt = _build_rationale_prompt(
            agent_name=agent_name,
            genome=genome,
            match=match,
            probability=probability,
            direction=direction,
            evidence_claims=evidence_claims or [],
            prior_claims=prior_claims or [],
            debate_role=debate_role,
            debate_phase=debate_phase,
            dispute=dispute,
        )

        payload = {
            "model": self.model,
            "system": (
                "You are the voice layer for a bounded prediction-colony debate feed. "
                "Always return a non-empty plain-text sentence."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
            "max_tokens": 180,
            "stream": False,
            "temperature": 0.5,
        }

        request = urllib.request.Request(
            url=self.messages_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MiniMax voice call failed: HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"MiniMax voice call failed: {exc}") from exc

        content = data.get("content")
        if isinstance(content, str):
            return _format_llm_claim(
                agent_name=agent_name,
                match=match,
                probability=probability,
                direction=direction,
                rationale=content,
            )
        if isinstance(content, list):
            text_parts = [
                str(part.get("text", "")).strip()
                for part in content
                if isinstance(part, dict) and part.get("type") in {None, "text"}
            ]
            joined = " ".join(part for part in text_parts if part)
            if joined:
                return _format_llm_claim(
                    agent_name=agent_name,
                    match=match,
                    probability=probability,
                    direction=direction,
                    rationale=joined,
                )

        # Some gateways expose OpenAI-compatible response shapes even on custom hosts.
        try:
            return _format_llm_claim(
                agent_name=agent_name,
                match=match,
                probability=probability,
                direction=direction,
                rationale=_text_from_openai_message(data),
            )
        except RuntimeError as exc:
            raise RuntimeError(f"Unexpected MiniMax response shape: {data}") from exc


def llm_voice_model_from_env() -> VoiceModel:
    provider = os.environ.get("COLONY_LLM_PROVIDER", "minimax").strip().lower()
    if provider == "minimax":
        return MiniMaxVoiceModel.from_env()
    if provider == "openrouter":
        return OpenAICompatibleVoiceModel.from_openrouter_env()
    if provider == "openai":
        return OpenAICompatibleVoiceModel.from_env()
    raise ValueError("COLONY_LLM_PROVIDER must be 'minimax', 'openrouter', or 'openai'")
