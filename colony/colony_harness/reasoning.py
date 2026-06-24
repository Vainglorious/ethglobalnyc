"""Natural ant judgment adapters.

The core harness still keeps numeric fields for benchmarking and settlement.
This module adds the qualitative layer on top: thesis, conviction, survival
risk, stake sizing, doubts, and social move. CAMEL is optional and isolated
here.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from .agent import AntAgent
from .models import Forecast, MatchContext
from .mind import mind_one_line

JudgmentStance = Literal["home", "draw", "away", "undecided", "pass"]
JudgmentConviction = Literal["very_low", "low", "medium", "high"]
JudgmentIntent = Literal["bet", "pass", "buy_info", "ask_debate", "watch"]
JudgmentAction = Literal[
    "commit_stake",
    "vote_only",
    "request_evidence",
    "challenge_source",
    "call_discussion",
    "minority_report",
    "fund_scout",
    "hold_position",
]
CommitmentLabel = Literal["none", "micro", "small", "medium", "high"]
RiskIntent = Literal["none", "micro", "small", "medium", "aggressive"]
RiskRead = Literal["too_risky", "acceptable", "attractive"]
StakeLevel = Literal["micro", "small", "medium", "high"]
SocialMove = Literal[
    "defend",
    "challenge_source",
    "challenge_consensus",
    "ask_for_data",
    "listen",
    "minority_report",
]

SIDES = {"home", "draw", "away"}
STANCES = SIDES | {"undecided", "pass"}
CONVICTIONS = {"very_low", "low", "medium", "high"}
INTENTS = {"bet", "pass", "buy_info", "ask_debate", "watch"}
ACTIONS = {
    "commit_stake",
    "vote_only",
    "request_evidence",
    "challenge_source",
    "call_discussion",
    "minority_report",
    "fund_scout",
    "hold_position",
}
COMMITMENT_LABELS = {"none", "micro", "small", "medium", "high"}
RISK_INTENTS = {"none", "micro", "small", "medium", "aggressive"}
RISK_READS = {"too_risky", "acceptable", "attractive"}
STAKE_LEVELS = {"micro", "small", "medium", "high"}
SOCIAL_MOVES = {"defend", "challenge_source", "challenge_consensus", "ask_for_data", "listen", "minority_report"}
INTENT_TO_ACTION = {
    "bet": "commit_stake",
    "pass": "vote_only",
    "buy_info": "request_evidence",
    "ask_debate": "call_discussion",
    "watch": "hold_position",
}
ACTION_TO_INTENT = {
    "commit_stake": "bet",
    "vote_only": "pass",
    "request_evidence": "buy_info",
    "challenge_source": "ask_debate",
    "call_discussion": "ask_debate",
    "minority_report": "ask_debate",
    "fund_scout": "buy_info",
    "hold_position": "watch",
}
RISK_TO_COMMITMENT = {
    "none": "none",
    "micro": "micro",
    "small": "small",
    "medium": "medium",
    "aggressive": "high",
}
COMMITMENT_TO_RISK = {
    "none": "none",
    "micro": "micro",
    "small": "small",
    "medium": "medium",
    "high": "aggressive",
}
STAKE_TO_RISK_INTENT = {
    "micro": "micro",
    "small": "small",
    "medium": "medium",
    "high": "aggressive",
}
MIN_CAMEL_TIMEOUT_SECONDS = 30
CONVICTION_ALIASES = {
    "minimal": "very_low",
    "none": "very_low",
    "uncertain": "low",
    "weak": "low",
    "cautious": "low",
    "moderate": "medium",
    "solid": "medium",
    "reasonable": "medium",
    "confident": "high",
    "strong": "high",
    "very_high": "high",
}
RISK_READ_ALIASES = {
    "bad": "too_risky",
    "high_risk": "too_risky",
    "risky": "too_risky",
    "too_high": "too_risky",
    "too_risky": "too_risky",
    "fair": "acceptable",
    "ok": "acceptable",
    "okay": "acceptable",
    "reasonable": "acceptable",
    "solid": "acceptable",
    "good": "attractive",
    "great": "attractive",
    "value": "attractive",
    "valuable": "attractive",
}
SOCIAL_MOVE_ALIASES = {
    "ask": "listen",
    "ask_question": "listen",
    "question": "listen",
    "debate": "defend",
    "support": "defend",
    "challenge": "challenge_consensus",
    "contrarian": "minority_report",
}


@dataclass(frozen=True)
class NaturalJudgment:
    agent_id: str
    persona_id: str
    input_style: str
    source: str
    stance: JudgmentStance
    conviction: JudgmentConviction
    intent: JudgmentIntent
    action: JudgmentAction
    civic_choice: Literal["home", "draw", "away"]
    commitment_label: CommitmentLabel
    risk_intent: RiskIntent
    thesis: str
    main_signal: str
    risk_read: RiskRead
    stake_level: StakeLevel
    survival_reason: str
    action_target: str
    evidence_used: list[str]
    evidence_distrusted: list[str]
    reasoning: list[str]
    doubts: list[str]
    debate_question: str
    social_move: SocialMove
    one_line: str
    diagnostics: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CamelReasonerConfig:
    timeout_seconds: int = 45
    input_style: str = "structured_evidence_cards"
    max_evidence_cards: int = 8
    max_claims_per_finding: int = 2


class CamelReasoner:
    """Optional CAMEL adapter that asks one ant for a qualitative judgment."""

    def __init__(self, config: CamelReasonerConfig | None = None) -> None:
        resolved = config or CamelReasonerConfig()
        if resolved.timeout_seconds < MIN_CAMEL_TIMEOUT_SECONDS:
            resolved = replace(resolved, timeout_seconds=MIN_CAMEL_TIMEOUT_SECONDS)
        self.config = resolved
        self._model: Any | None = None
        self._model_error = ""

    def available(self) -> bool:
        return self._model_backend() is not None

    def private_judgment(
        self,
        *,
        agent: AntAgent,
        match: MatchContext,
        debate_messages: list[str] | None = None,
    ) -> NaturalJudgment:
        model = self._model_backend()
        if model is None:
            return _fallback_judgment(
                agent=agent,
                input_style=self.config.input_style,
                source="camel_unavailable",
                reason=self._model_error or "CAMEL model backend is unavailable",
            )

        try:
            from camel.agents import ChatAgent
            from pydantic import BaseModel, Field
        except Exception as exc:
            return _fallback_judgment(
                agent=agent,
                input_style=self.config.input_style,
                source="camel_unavailable",
                reason=f"CAMEL imports failed: {type(exc).__name__}: {exc}",
            )

        class CamelJudgmentPayload(BaseModel):
            persona_id: str = ""
            input_style: str = ""
            stance: str
            conviction: str
            intent: str = "bet"
            action: str = "commit_stake"
            civic_choice: str
            commitment_label: str = "micro"
            risk_intent: str = "micro"
            thesis: str = ""
            main_signal: str = ""
            risk_read: str
            stake_level: str
            survival_reason: str = ""
            action_target: str = ""
            evidence_used: list[str] = Field(default_factory=list, max_length=6)
            evidence_distrusted: list[str] = Field(default_factory=list, max_length=6)
            reasoning: list[str] = Field(default_factory=list, max_length=5)
            doubts: list[str] = Field(default_factory=list, max_length=4)
            debate_question: str = ""
            social_move: str = "listen"
            one_line: str = ""

        system = _system_prompt(agent)
        prompt = _judgment_prompt(
            agent=agent,
            match=match,
            input_style=self.config.input_style,
            max_evidence_cards=self.config.max_evidence_cards,
            max_claims_per_finding=self.config.max_claims_per_finding,
            debate_messages=debate_messages or [],
        )
        started_at = time.monotonic()
        try:
            camel_agent = ChatAgent(
                system_message=system,
                model=model,
                tools=None,
                max_iteration=1,
                step_timeout=self.config.timeout_seconds,
            )
            response = camel_agent.step(prompt, response_format=CamelJudgmentPayload)
            message = response.msgs[0]
            payload = _payload_from_camel_message(message)
            payload["diagnostics"] = {
                **_clean_diagnostics(payload.get("diagnostics")),
                "elapsed_seconds": round(time.monotonic() - started_at, 3),
                "timeout_seconds": self.config.timeout_seconds,
                "model": _configured_camel_model_name(),
            }
        except Exception as exc:
            return _fallback_judgment(
                agent=agent,
                input_style=self.config.input_style,
                source="camel_error",
                reason=f"{type(exc).__name__}: {exc}",
                diagnostics={
                    "elapsed_seconds": round(time.monotonic() - started_at, 3),
                    "timeout_seconds": self.config.timeout_seconds,
                    "model": _configured_camel_model_name(),
                },
            )

        return normalize_judgment(
            payload,
            agent_id=agent.agent_id,
            persona_id=str((agent.mind or {}).get("archetype") or agent.genome.persona),
            input_style=self.config.input_style,
            source="camel",
        )

    def _model_backend(self) -> Any | None:
        if self._model is not None:
            return self._model
        if self._model_error:
            return None
        try:
            from .live_scouts import _camel_model_backend

            self._model = _camel_model_backend(timeout_seconds=self.config.timeout_seconds)
        except Exception as exc:
            self._model_error = f"{type(exc).__name__}: {exc}"
            return None
        if self._model is None:
            self._model_error = "No CAMEL API key/model backend resolved from environment"
        return self._model


def normalize_judgment(
    payload: dict,
    *,
    agent_id: str,
    persona_id: str,
    input_style: str,
    source: str,
) -> NaturalJudgment:
    stance = _choice(payload.get("stance"), STANCES, "undecided")
    conviction = _choice(payload.get("conviction"), CONVICTIONS, "low", aliases=CONVICTION_ALIASES)
    intent = _choice(payload.get("intent"), INTENTS, "pass")
    action = _choice(payload.get("action"), ACTIONS, "")
    civic_choice = _choice(payload.get("civic_choice"), SIDES, "")
    if not civic_choice and stance in SIDES:
        civic_choice = stance
    if not civic_choice:
        civic_choice = "draw"
    social_move = _choice(payload.get("social_move"), SOCIAL_MOVES, "listen", aliases=SOCIAL_MOVE_ALIASES)
    if action:
        intent = ACTION_TO_INTENT.get(action, intent)
    else:
        action = _action_from_intent_and_social_move(intent=intent, social_move=social_move)

    risk_read = _choice(payload.get("risk_read"), RISK_READS, "", aliases=RISK_READ_ALIASES)
    stake_level = _stake_level_from_payload(payload)
    if not risk_read:
        risk_read = _risk_read_from_stake_level(stake_level=stake_level, conviction=conviction)

    if source == "camel":
        if stance not in SIDES:
            stance = civic_choice
        action = "commit_stake"
        intent = "bet"
        commitment_label = stake_level
        risk_intent = STAKE_TO_RISK_INTENT[stake_level]
    elif _is_camel_fallback_source(source):
        if stance not in SIDES:
            stance = civic_choice
        action = "commit_stake"
        intent = "bet"
        stake_level = "micro"
        risk_read = "too_risky"
        commitment_label = "micro"
        risk_intent = "micro"
    else:
        risk_intent = _choice(payload.get("risk_intent"), RISK_INTENTS, "none")
        commitment_label = _choice(payload.get("commitment_label"), COMMITMENT_LABELS, "")
        if not commitment_label:
            commitment_label = RISK_TO_COMMITMENT.get(risk_intent, "none")
        if action != "commit_stake":
            commitment_label = "none"
            risk_intent = "none"
        elif risk_intent == "none":
            risk_intent = COMMITMENT_TO_RISK.get(commitment_label, "none")
        if action == "commit_stake" and commitment_label == "none":
            action = "vote_only"
            intent = "pass"

    thesis = _clean_text(payload.get("thesis")) or _clean_text(payload.get("one_line"))
    if not thesis:
        thesis = _clean_text(payload.get("debate_question")) or "I do not have a strong thesis yet."
    main_signal = _clean_signal(payload.get("main_signal"))
    survival_reason = _clean_text(payload.get("survival_reason")) or _survival_reason(
        risk_read=risk_read,
        stake_level=stake_level,
        conviction=conviction,
    )

    one_line = _clean_text(payload.get("one_line")) or survival_reason or thesis
    if not one_line:
        one_line = "I commit the minimum survival stake while keeping the thesis cautious."

    resolved_persona_id = (
        persona_id
        if _is_survival_judgment_source(source)
        else _clean_text(payload.get("persona_id")) or persona_id
    )

    return NaturalJudgment(
        agent_id=agent_id,
        persona_id=resolved_persona_id,
        input_style=_clean_text(payload.get("input_style")) or input_style,
        source=source,
        stance=stance,  # type: ignore[arg-type]
        conviction=conviction,  # type: ignore[arg-type]
        intent=intent,  # type: ignore[arg-type]
        action=action,  # type: ignore[arg-type]
        civic_choice=civic_choice,  # type: ignore[arg-type]
        commitment_label=commitment_label,  # type: ignore[arg-type]
        risk_intent=risk_intent,  # type: ignore[arg-type]
        thesis=thesis,
        main_signal=main_signal,
        risk_read=risk_read,  # type: ignore[arg-type]
        stake_level=stake_level,  # type: ignore[arg-type]
        survival_reason=survival_reason,
        action_target=_clean_text(payload.get("action_target")),
        evidence_used=_clean_list(payload.get("evidence_used"), limit=6),
        evidence_distrusted=_clean_list(payload.get("evidence_distrusted"), limit=6),
        reasoning=_clean_list(payload.get("reasoning"), limit=5),
        doubts=_clean_list(payload.get("doubts"), limit=4),
        debate_question=_clean_text(payload.get("debate_question")),
        social_move=social_move,  # type: ignore[arg-type]
        one_line=one_line,
        diagnostics={**_clean_diagnostics(payload.get("diagnostics")), "normalized": True},
    )


def apply_judgment_to_forecast(
    *,
    forecast: Forecast,
    match: MatchContext,
    judgment: NaturalJudgment,
) -> Forecast:
    if not _is_survival_judgment_source(judgment.source):
        return replace(
            forecast,
            stake=0.0,
            decision_reason=f"{forecast.decision_reason}; natural judgment skipped: {judgment.one_line}",
            judgment=judgment.to_dict(),
        )

    applied_judgment = judgment
    if _is_camel_fallback_source(judgment.source):
        fallback_thesis = (
            "CAMEL fallback: this ant uses its deterministic survival read "
            "and commits only the minimum stake."
        )
        applied_judgment = replace(
            judgment,
            stance=forecast.side,
            civic_choice=forecast.side,
            action="commit_stake",
            intent="bet",
            commitment_label="micro",
            risk_intent="micro",
            risk_read="too_risky",
            stake_level="micro",
            thesis=fallback_thesis,
            main_signal=judgment.main_signal or "baseline_survival_fallback",
            survival_reason="I keep the mandatory stake at micro because the natural judgment failed.",
            one_line="CAMEL failed, so I participate with a micro fallback stake.",
        )

    side = applied_judgment.civic_choice
    home_probability = _baseline_probability_bridge(
        original=forecast.home_probability,
        market_anchor=match.market_home_probability,
        stance=applied_judgment.civic_choice,
    )
    edge = _baseline_edge(home_probability=home_probability, market_anchor=match.market_home_probability, side=side)
    stake = _stake_from_level(
        base_stake=forecast.stake,
        bankroll=forecast.bankroll,
        stake_level=applied_judgment.stake_level,
    )

    reason = _decision_reason_from_judgment(forecast, applied_judgment)
    return replace(
        forecast,
        side=side,
        home_probability=round(home_probability, 4),
        market_edge=round(home_probability - match.market_home_probability, 4),
        edge=round(edge, 4),
        stake=round(stake, 4),
        decision_reason=reason,
        judgment=applied_judgment.to_dict(),
    )


def _system_prompt(agent: AntAgent) -> str:
    mind = agent.mind or {}
    lines = [
        "You are a WorldColony football forecasting ant.",
        f"Ant id: {agent.agent_id}.",
        f"Persona: {mind.get('label') or agent.genome.persona}.",
        f"Belief: {mind.get('belief') or 'Act carefully from evidence.'}",
        f"Voice: {mind.get('voice') or 'concise and grounded'}.",
        f"Risk style: {mind.get('risk_style') or 'balanced'}.",
        f"Data style: {mind.get('data_style') or 'mixed evidence'}.",
        f"Debate style: {mind.get('debate_style') or 'evidence-first'}.",
        f"Wealth behavior: {mind.get('wealth_behavior') or 'protects its bankroll'}.",
        f"Trust style: {mind.get('trust_style') or 'trusts traceable evidence'}.",
        "",
        "Make a practical judgment without numeric probabilities.",
        "Do not output percentages or decimal probabilities.",
        "You must cast a civic_choice: home, draw, or away.",
        "You must form a thesis, choose the main signal you prioritize, read the survival risk, and set a stake_level.",
        "Every valid ant participates financially: stake_level must be micro, small, medium, or high; never none.",
        "Use micro when survival matters more than conviction.",
        "Use high only for rare, strongly justified theses.",
        "The debate should focus on interpretation and whether the risk is worth the stake.",
        "Use action=commit_stake and intent=bet.",
        "Do not use old non-staking actions such as pass, watch, buy_info, request_evidence, or challenge_source.",
        "Do not make the market or statistics your only focus; use source quality, tactics, lineup, motivation, social context, and debate quality when relevant.",
        "Prediction markets are allowed as one signal, especially for market-oriented personas, but they are not the whole judgment.",
        "Return only valid structured data.",
    ]
    return "\n".join(lines)


def _judgment_prompt(
    *,
    agent: AntAgent,
    match: MatchContext,
    input_style: str,
    max_evidence_cards: int,
    max_claims_per_finding: int,
    debate_messages: list[str],
) -> str:
    evidence_cards = _evidence_cards(
        match,
        max_cards=max_evidence_cards,
        max_claims_per_finding=max_claims_per_finding,
    )
    market_read = _qualitative_market_read(match.market_home_probability, match.home_team, match.away_team)
    memory = mind_one_line(agent.mind) if agent.mind else ""
    debate_block = "\n".join(f"- {message}" for message in debate_messages[:6]) or "- No debate transcript yet."
    return f"""
Input style: {input_style}
Match: {match.home_team} vs {match.away_team}
Stage: {match.stage_name or match.group_name or 'unknown'}
Venue: {match.venue_name or 'unknown'}
Market read: {market_read}
Wallet: {agent.bankroll:.1f} internal credits. Protect reserves when conviction is weak.
Mind memory: {memory or 'No extra memory summary.'}

Evidence cards:
{evidence_cards}

Debate / society review context:
{debate_block}

Task:
Give your private final judgment for this round as this ant. If the context includes post-resolution reviews, you may revise your earlier choice.
    Use stance, civic_choice, thesis, main_signal, conviction, risk_read, stake_level, survival_reason, doubts, evidence IDs, debate question, and social move.
    civic_choice is mandatory and must be home, draw, or away.
    stake_level is mandatory and must be micro, small, medium, or high; do not use none.
If the pick is weak or the risk is too large, use risk_read=too_risky and stake_level=micro.
If risk is acceptable, usually use small or medium.
If the upside is unusually attractive and conviction is high, you may use high.
    Set action=commit_stake, intent=bet, commitment_label equal to stake_level, and risk_intent consistent with stake_level.
    Do not use pass, watch, buy_info, request_evidence, challenge_source, vote_only, or hold_position.
    Do not reduce the match to a market/statistics read. Markets can inform you, but should not be the only reason.
    Never give numeric probabilities. Never invent source links.
"""


def _evidence_cards(match: MatchContext, *, max_cards: int, max_claims_per_finding: int) -> str:
    cards: list[str] = []
    index = 1
    for finding in match.findings:
        claims = finding.evidence_claims[:max_claims_per_finding] if finding.evidence_claims else []
        if claims:
            for claim in claims:
                text = _clean_text(claim.get("claim") or claim.get("summary") or finding.summary)
                if not text:
                    continue
                quality = _clean_text(claim.get("source_quality") or claim.get("claim_quality") or "")
                claim_type = _clean_text(claim.get("claim_type") or finding.source_type)
                team = _clean_text(claim.get("team") or claim.get("subject") or "")
                cards.append(
                    f"E{index} [{finding.source_type}, {quality or 'unknown quality'}, {claim_type}] "
                    f"{team + ': ' if team else ''}{text}"
                )
                index += 1
                if len(cards) >= max_cards:
                    return "\n".join(cards)
        else:
            text = _clean_text(finding.summary)
            if not text:
                continue
            cards.append(f"E{index} [{finding.source_type}, confidence={finding.confidence:.1f}] {text}")
            index += 1
            if len(cards) >= max_cards:
                return "\n".join(cards)
    if cards:
        return "\n".join(cards)
    return "- No source-grounded evidence cards are available; be cautious."


def _fallback_judgment(
    *,
    agent: AntAgent,
    input_style: str,
    source: str,
    reason: str,
    diagnostics: dict | None = None,
) -> NaturalJudgment:
    persona_id = str((agent.mind or {}).get("archetype") or agent.genome.persona)
    return NaturalJudgment(
        agent_id=agent.agent_id,
        persona_id=persona_id,
        input_style=input_style,
        source=source,
        stance="undecided",
        conviction="very_low",
        intent="bet",
        action="commit_stake",
        civic_choice="draw",
        commitment_label="micro",
        risk_intent="micro",
        thesis="CAMEL judgment was unavailable, so the ant falls back to a survival-sized deterministic read.",
        main_signal="unavailable_judgment",
        risk_read="too_risky",
        stake_level="micro",
        survival_reason="I keep the mandatory stake at micro because the natural judgment failed.",
        action_target="",
        evidence_used=[],
        evidence_distrusted=[],
        reasoning=["CAMEL judgment unavailable; falling back to a micro survival stake."],
        doubts=[reason],
        debate_question="How much should the colony trust fallback survival stakes?",
        social_move="listen",
        one_line="CAMEL unavailable, so I participate with a micro fallback stake.",
        diagnostics={"error": reason, **(diagnostics or {})},
    )


def _decision_reason_from_judgment(forecast: Forecast, judgment: NaturalJudgment) -> str:
    parts = [
        "natural judgment",
        f"stance={judgment.stance}",
        f"choice={judgment.civic_choice}",
        f"conviction={judgment.conviction}",
        f"action={judgment.action}",
        f"intent={judgment.intent}",
        f"commitment={judgment.commitment_label}",
        f"risk={judgment.risk_intent}",
        f"stake_level={judgment.stake_level}",
        f"risk_read={judgment.risk_read}",
        f"main_signal={judgment.main_signal}",
        f"social={judgment.social_move}",
        f"thesis={judgment.thesis}",
        f"survival={judgment.survival_reason}",
        judgment.one_line,
    ]
    if judgment.action_target:
        parts.append(f"action target: {judgment.action_target}")
    if judgment.debate_question:
        parts.append(f"debate question: {judgment.debate_question}")
    if judgment.reasoning:
        parts.append("reasoning: " + " / ".join(judgment.reasoning[:3]))
    parts.append(f"baseline read: {forecast.decision_reason}")
    return "; ".join(part for part in parts if part)


def _baseline_probability_bridge(*, original: float, market_anchor: float, stance: str) -> float:
    if stance == "home":
        return _clamp_probability(max(original, market_anchor + 0.035))
    if stance == "away":
        return _clamp_probability(min(original, market_anchor - 0.035))
    if stance == "draw":
        return _clamp_probability((original + 0.5) / 2.0)
    return _clamp_probability(original)


def _baseline_edge(*, home_probability: float, market_anchor: float, side: str) -> float:
    if side == "home":
        return home_probability - market_anchor
    if side == "away":
        return market_anchor - home_probability
    return max(0.0025, 0.08 - abs(home_probability - 0.5))


def _stake_from_risk_intent(stake: float, risk_intent: str) -> float:
    multipliers = {
        "none": 0.0,
        "micro": 0.12,
        "small": 0.45,
        "medium": 0.9,
        "aggressive": 1.35,
    }
    return max(0.0, stake * multipliers.get(risk_intent, 0.0))


def _stake_from_level(*, base_stake: float, bankroll: float, stake_level: str) -> float:
    multipliers = {
        "micro": 0.12,
        "small": 0.45,
        "medium": 0.9,
        "high": 1.35,
    }
    multiplier = multipliers.get(stake_level, multipliers["micro"])
    minimum = max(0.0001, min(max(float(bankroll), 0.0) * 0.001, 0.05))
    stake = max(float(base_stake), minimum) * multiplier
    if stake_level == "micro":
        stake = max(stake, minimum)
    return max(0.0001, stake)


def _is_survival_judgment_source(source: str) -> bool:
    return source == "camel" or _is_camel_fallback_source(source)


def _is_camel_fallback_source(source: str) -> bool:
    return source in {"camel_error", "camel_unavailable"}


def _stake_level_from_payload(payload: dict) -> str:
    explicit = _clean_text(payload.get("stake_level"))
    if not explicit:
        action = _clean_text(payload.get("action")).lower().replace("-", "_").replace(" ", "_")
        intent = _clean_text(payload.get("intent")).lower().replace("-", "_").replace(" ", "_")
        if action and action != "commit_stake":
            return "micro"
        if intent and intent != "bet":
            return "micro"
    raw = _clean_text(explicit or payload.get("commitment_label") or payload.get("risk_intent")).lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    aliases = {
        "none": "micro",
        "no_stake": "micro",
        "pass": "micro",
        "very_low": "micro",
        "low": "micro",
        "minimal": "micro",
        "minimum": "micro",
        "1": "micro",
        "2": "small",
        "moderate": "medium",
        "solid": "medium",
        "3": "medium",
        "4": "high",
        "5": "high",
        "aggressive": "high",
        "large": "high",
        "big": "high",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in STAKE_LEVELS else "micro"


def _risk_read_from_stake_level(*, stake_level: str, conviction: str) -> str:
    if stake_level == "micro" or conviction in {"very_low", "low"}:
        return "too_risky"
    if stake_level == "high":
        return "attractive"
    return "acceptable"


def _survival_reason(*, risk_read: str, stake_level: str, conviction: str) -> str:
    if stake_level == "micro":
        return "I still participate, but the survival move is to keep the stake minimal."
    if risk_read == "too_risky":
        return "The pick is live, but the capital risk is large, so I keep the stake controlled."
    if risk_read == "attractive":
        return "The thesis has enough upside to justify a larger stake without going all-in."
    if conviction == "high":
        return "The thesis is strong enough for a meaningful but capped stake."
    return "The risk looks acceptable, so I take a measured position."


def _action_from_intent_and_social_move(*, intent: str, social_move: str) -> str:
    if intent == "bet":
        return "commit_stake"
    if social_move == "challenge_source":
        return "challenge_source"
    if social_move == "minority_report":
        return "minority_report"
    if social_move == "ask_for_data":
        return "request_evidence"
    return INTENT_TO_ACTION.get(intent, "vote_only")


def _qualitative_market_read(home_probability: float, home_team: str, away_team: str) -> str:
    if home_probability >= 0.58:
        return f"Market strongly favors {home_team}."
    if home_probability >= 0.53:
        return f"Market leans toward {home_team}."
    if home_probability <= 0.42:
        return f"Market strongly leans away from {home_team}, toward {away_team}."
    if home_probability <= 0.47:
        return f"Market leans toward {away_team}."
    return "Market reads close to balanced."


def _choice(value: object, allowed: set[str], fallback: str, *, aliases: dict[str, str] | None = None) -> str:
    text = _clean_text(value).lower().replace("-", "_").replace(" ", "_")
    if aliases:
        text = aliases.get(text, text)
    return text if text in allowed else fallback


def _payload_from_camel_message(message: Any) -> dict[str, Any]:
    parsed = getattr(message, "parsed", None)
    if parsed is not None:
        payload = parsed.model_dump() if hasattr(parsed, "model_dump") else parsed.dict()
        return dict(payload)
    payload = _json_object_from_text(getattr(message, "content", ""))
    if not isinstance(payload, dict):
        raise ValueError("CAMEL response did not contain a JSON object")
    return payload


def _json_object_from_text(text: object) -> dict[str, Any]:
    raw = _clean_text(text)
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON payload is not an object")
    return value


def _clean_diagnostics(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        name = _clean_text(key)
        if not name:
            continue
        if isinstance(item, str | int | float | bool) or item is None:
            cleaned[name] = item
        else:
            cleaned[name] = _clean_text(item)
    return cleaned


def _configured_camel_model_name() -> str:
    return (
        os.environ.get("COLONY_CAMEL_MODEL", "").strip()
        or os.environ.get("COLONY_LLM_MODEL", "").strip()
        or ""
    )


def _clean_list(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = [_clean_text(item) for item in value]
    return [item for item in cleaned if item][:limit]


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).strip()


def _clean_signal(value: object) -> str:
    text = _clean_text(value).lower().replace("-", "_").replace(" ", "_")
    return text or "mixed"


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, float(value)))
