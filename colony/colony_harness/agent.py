"""Agent behavior for the Colony harness."""

from __future__ import annotations

import hashlib
import random
import secrets
from dataclasses import dataclass

from .genes import Genome
from .models import AccessTier, BetCommitment, DebateClaim, Forecast, MatchContext, Side
from .voice import TemplateVoiceModel, VoiceModel


def _clamp_probability(value: float) -> float:
    return min(max(value, 0.01), 0.99)


def _normalize_public_message(agent_name: str, message: str) -> str:
    cleaned = " ".join(message.strip().split())
    if not cleaned or cleaned.lower() == "none":
        raise ValueError("voice model returned an empty message")
    if not cleaned.startswith(f"{agent_name}:"):
        cleaned = f"{agent_name}: {cleaned}"
    return cleaned


def _short_voice_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if len(text) > 180:
        return f"{text[:177]}..."
    return text


def _top_weight_labels(genome: Genome, count: int = 2) -> str:
    weights = genome.source_weights.normalized().to_dict()
    top = sorted(weights.items(), key=lambda item: item[1], reverse=True)[:count]
    return ", ".join(f"{label}={value:.2f}" for label, value in top)


def _claim_type_from_genome(genome: Genome) -> str:
    weights = genome.source_weights.normalized().to_dict()
    top_source = max(weights, key=weights.get)
    if genome.herd_bias < -0.25:
        return "contrarian"
    if top_source == "odds":
        return "market-check"
    if top_source == "debate":
        return "debate-response"
    if top_source == "news":
        return "narrative"
    return "evidence"


@dataclass
class AntAgent:
    agent_id: str
    name: str
    generation: int
    genome: Genome
    bankroll: float
    accuracy: float

    @property
    def public_record(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "generation": self.generation,
            "bankroll": round(self.bankroll, 4),
            "accuracy": round(self.accuracy, 4),
            "status": "alive",
            "genome_hash": self.genome.public_hash(),
        }

    def private_baseline_probability(self, match: MatchContext) -> float:
        weights = self.genome.source_weights.normalized()
        probability = (
            weights.stats * match.stats_home_signal
            + weights.odds * match.odds_home_signal
            + weights.news * match.news_home_signal
            + weights.debate * match.market_home_probability
        )

        if self.genome.estimator == "llm":
            model_tilt = {
                "deepseek-v3.2": 0.018,
                "qwen-3": 0.01,
                "MiniMax-M3": 0.012,
                "MiniMax-M2.7": -0.002,
                "MiniMax-M2.7-highspeed": -0.006,
                "claude-haiku": 0.004,
                "parametric": 0.0,
            }.get(self.genome.model, 0.0)
            probability += model_tilt

        return _clamp_probability(probability)

    def listen(self, match: MatchContext, debate_home_probability: float | None) -> float:
        base = self.private_baseline_probability(match)
        if debate_home_probability is None:
            return base

        debate_weight = self.genome.source_weights.normalized().debate
        signed_herd = self.genome.herd_bias
        adjustment = debate_weight * signed_herd * (debate_home_probability - match.market_home_probability)
        return _clamp_probability(base + adjustment)

    def speak(
        self,
        match: MatchContext,
        rng: random.Random,
        voice_model: VoiceModel | None = None,
        selection_reason: str = "",
        access_tier: AccessTier = "public",
        visible_findings: int = 0,
    ) -> DebateClaim:
        probability = self.private_baseline_probability(match)
        edge = probability - match.market_home_probability
        confidence = min(abs(edge) * 3.0 + 0.25 + rng.random() * 0.1, 0.95)
        direction: Side = "home" if edge >= 0 else "away"
        voice = voice_model or TemplateVoiceModel()
        try:
            message = voice.render_claim(
                agent_name=self.name,
                genome=self.genome,
                match=match,
                probability=probability,
                direction=direction,
            )
            message = _normalize_public_message(self.name, message)
        except Exception as exc:
            fallback = TemplateVoiceModel()
            message = fallback.render_claim(
                agent_name=self.name,
                genome=self.genome,
                match=match,
                probability=probability,
                direction=direction,
            )
            message = f"{message} [voice fallback: {_short_voice_error(exc)}]"

        tags = []
        weights = self.genome.source_weights.normalized()
        for label, value in weights.to_dict().items():
            if value >= 0.28:
                tags.append(label)

        return DebateClaim(
            round_id=match.round_id,
            speaker_id=self.agent_id,
            speaker_name=self.name,
            model=self.genome.model,
            persona=self.genome.persona,
            access_tier=access_tier,
            visible_findings=visible_findings,
            claim_type=_claim_type_from_genome(self.genome),
            selection_reason=selection_reason,
            stated_home_probability=round(probability, 4),
            confidence=round(confidence, 4),
            direction=direction,
            message=message,
            evidence_tags=tags,
        )

    def forecast(
        self,
        match: MatchContext,
        debate_home_probability: float | None,
        access_tier: AccessTier = "public",
        visible_findings: int = 0,
    ) -> Forecast:
        baseline_probability = self.private_baseline_probability(match)
        probability = self.listen(match, debate_home_probability)
        home_edge = probability - match.market_home_probability
        away_edge = (1.0 - probability) - (1.0 - match.market_home_probability)
        debate_shift = probability - baseline_probability

        if home_edge >= self.genome.edge_threshold:
            side: Side = "home"
            edge = home_edge
            decision_reason = (
                f"home edge {home_edge:+.1%} clears threshold {self.genome.edge_threshold:.1%}; "
                f"debate shift {debate_shift:+.1%}; top weights {_top_weight_labels(self.genome)}"
            )
        elif away_edge >= self.genome.edge_threshold:
            side = "away"
            edge = away_edge
            decision_reason = (
                f"away edge {away_edge:+.1%} clears threshold {self.genome.edge_threshold:.1%}; "
                f"debate shift {debate_shift:+.1%}; top weights {_top_weight_labels(self.genome)}"
            )
        else:
            side = "pass"
            edge = 0.0
            decision_reason = (
                f"largest edge {max(home_edge, away_edge):+.1%} is below threshold "
                f"{self.genome.edge_threshold:.1%}; debate shift {debate_shift:+.1%}; "
                f"top weights {_top_weight_labels(self.genome)}"
            )

        stake = 0.0 if side == "pass" else round(self.bankroll * self.genome.risk_appetite, 4)
        return Forecast(
            agent_id=self.agent_id,
            access_tier=access_tier,
            visible_findings=visible_findings,
            home_probability=round(probability, 4),
            market_edge=round(home_edge, 4),
            edge_threshold=self.genome.edge_threshold,
            edge=round(edge, 4),
            side=side,
            stake=stake,
            bankroll=round(self.bankroll, 4),
            decision_reason=decision_reason,
        )

    def commit_bet(self, forecast: Forecast, round_id: str) -> BetCommitment:
        salt = secrets.token_hex(16)
        reveal = {
            "agent_id": self.agent_id,
            "round_id": round_id,
            "side": forecast.side,
            "stake": forecast.stake,
            "salt": salt,
        }
        payload = f"{self.agent_id}|{round_id}|{forecast.side}|{forecast.stake}|{salt}"
        commitment = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return BetCommitment(
            agent_id=self.agent_id,
            round_id=round_id,
            commitment=commitment,
            reveal=reveal,
        )
