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
    cleaned = " ".join(rationale.strip().split())
    if cleaned.startswith(f"{agent_name}:"):
        cleaned = cleaned.split(":", 1)[1].strip()
    if not cleaned or cleaned.lower() == "none":
        raise RuntimeError("LLM returned empty rationale")

    market = match.market_home_probability
    if direction == "home":
        stance = f"I price {match.home_team} above market ({probability:.1%} vs {market:.1%})."
    else:
        stance = f"I price {match.home_team} below market ({probability:.1%} vs {market:.1%})."
    return f"{agent_name}: {stance} {cleaned}"


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
) -> str:
    return (
        "Write only a short rationale for a forecasting predictor in an agent debate.\n"
        "You may mention injuries, players, lineups, tactics, or source disagreement only if present in the allowed evidence below.\n"
        "Do not invent facts. Do not add new sources. Do not include the agent name.\n"
        "Do not repeat the match name. Do not include percentages or probabilities.\n"
        "Make it sound like a real debate move: cite one concrete fact, and if useful, respond to the previous claim.\n"
        "Keep it under 45 words. Write in English. Return one or two sentences.\n\n"
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
        f"{_compact_prior_claims(prior_claims)}\n"
    )


def _template_evidence_sentence(evidence_claims: list[dict], *, direction: Side) -> str:
    if not evidence_claims:
        return "I do not have a clean player-level claim, so I am leaning on my weighted signal mix."
    primary = evidence_claims[0]
    subject = str(primary.get("subject") or primary.get("team") or "the key subject")
    claim = str(primary.get("claim") or "").strip().rstrip(".")
    impact = str(primary.get("impact") or "")
    if claim:
        lead = f"The evidence I care about is {subject}: {claim}."
    else:
        lead = f"The evidence I care about is the {subject} availability signal."

    if len(evidence_claims) < 2:
        return lead

    counter = evidence_claims[1]
    counter_subject = str(counter.get("subject") or counter.get("team") or "the other side")
    counter_impact = str(counter.get("impact") or "")
    if direction == "away" and counter_impact == "negative_away":
        return f"{lead} I am not ignoring {counter_subject} risk, but the home-side concern prices larger for me."
    if direction == "home" and counter_impact == "negative_home":
        return f"{lead} I am not ignoring {counter_subject} risk, but the away-side concern prices larger for me."
    if impact.startswith("negative"):
        return f"{lead} That is a concrete availability drag, not just a narrative lean."
    return lead


def _short_source_name(source: str) -> str:
    cleaned = " ".join(source.split())
    if " - " in cleaned:
        tail = cleaned.rsplit(" - ", 1)[1].strip()
        if 2 <= len(tail) <= 32:
            return tail
    if " | " in cleaned:
        tail = cleaned.rsplit(" | ", 1)[1].strip()
        if 2 <= len(tail) <= 32:
            return tail
    return cleaned[:44].rstrip()


def _template_prior_sentence(
    prior_claims: list[DebateClaim],
    probability: float,
    evidence_claims: list[dict],
) -> str:
    if not prior_claims:
        return ""
    previous = prior_claims[-1]
    gap = probability - previous.stated_home_probability
    if abs(gap) < 0.006:
        if evidence_claims:
            source = str(evidence_claims[0].get("source_title") or evidence_claims[0].get("scout_name") or "another source")
            short_source = _short_source_name(source)
            return f"I mostly agree with {previous.speaker_name}; my added value is a separate {short_source} read."
        return f"I mostly agree with {previous.speaker_name}; I am not moving the price without a sharper source."
    if gap > 0:
        return f"I am pushing above {previous.speaker_name}'s number because my visible evidence is less damaging to the home side."
    return f"I am below {previous.speaker_name}'s number because the availability risk matters more in my weighting."


def _template_role_sentence(debate_role: str, *, direction: Side, match: MatchContext) -> str:
    if debate_role == "advocate":
        side = match.home_team if direction == "home" else match.away_team
        return f"I am carrying the room's strongest {side} case."
    if debate_role == "challenger":
        return "My job is to pressure-test the previous claim, not just echo it."
    if debate_role == "source_auditor":
        return "I am weighting source quality and source disagreement first."
    if debate_role == "skeptic":
        return "I would widen uncertainty rather than treat the edge as clean."
    if debate_role == "room_representative":
        return "I am bringing my room's strongest unresolved point into the final chamber."
    return ""


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
    ) -> str:
        evidence_sentence = _template_evidence_sentence(evidence_claims or [], direction=direction)
        prior_sentence = _template_prior_sentence(prior_claims or [], probability, evidence_claims or [])
        role_sentence = _template_role_sentence(debate_role, direction=direction, match=match)
        if direction == "home":
            return (
                f"{agent_name}: I price {match.home_team} above the market. "
                f"My {genome.persona} read is {probability:.1%} home win probability. "
                f"{role_sentence} {evidence_sentence} {prior_sentence}".strip()
            )

        away_probability = 1.0 - probability
        return (
            f"{agent_name}: I am fading {match.home_team}. "
            f"My {genome.persona} read gives {match.away_team} about {away_probability:.1%}. "
            f"{role_sentence} {evidence_sentence} {prior_sentence}".strip()
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
