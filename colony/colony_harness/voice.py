"""Voice models for debate speakers."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .genes import Genome
from .models import MatchContext, Side


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


class VoiceModel(Protocol):
    def render_claim(
        self,
        *,
        agent_name: str,
        genome: Genome,
        match: MatchContext,
        probability: float,
        direction: Side,
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
    ) -> str:
        if direction == "home":
            return (
                f"{agent_name}: I price {match.home_team} above the market. "
                f"My {genome.persona} read is {probability:.1%} home win probability."
            )

        away_probability = 1.0 - probability
        return (
            f"{agent_name}: I am fading {match.home_team}. "
            f"My {genome.persona} read gives {match.away_team} about {away_probability:.1%}."
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
    ) -> str:
        prompt = (
            "Write only a short rationale clause for a forecasting predictor.\n"
            "Do not include the ant name, match name, team names, numbers, probabilities, or percentages.\n"
            "Do not invent external facts. Do not mention team quality, injuries, tactics, recent form, players, or defensive gaps.\n"
            "Only refer to the persona or internal weighted findings.\n"
            "Keep it under 18 words. Write in English. Return one sentence fragment or sentence.\n\n"
            f"Ant name: {agent_name}\n"
            f"Persona: {genome.persona}\n"
            f"Model species: {genome.model}\n"
            f"Match: {match.home_team} vs {match.away_team}\n"
            f"Market home probability: {match.market_home_probability:.3f}\n"
            f"Ant home probability: {probability:.3f}\n"
            f"Direction: {direction}\n"
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
    ) -> str:
        prompt = (
            "Write only a short rationale clause for a forecasting predictor.\n"
            "Do not include the ant name, match name, team names, numbers, probabilities, or percentages.\n"
            "Do not invent external facts. Do not mention team quality, injuries, tactics, recent form, players, or defensive gaps.\n"
            "Only refer to the persona or internal weighted findings.\n"
            "Keep it under 18 words. Write in English. Return one sentence fragment or sentence.\n\n"
            f"Ant name: {agent_name}\n"
            f"Persona: {genome.persona}\n"
            f"Model species: {genome.model}\n"
            f"Match: {match.home_team} vs {match.away_team}\n"
            f"Market home probability: {match.market_home_probability:.3f}\n"
            f"Ant home probability: {probability:.3f}\n"
            f"Direction: {direction}\n"
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
