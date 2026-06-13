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


def _evidence_score(evidence: dict, *, direction: Side, source_weight: float, debate_focus: str = "") -> float:
    impact = str(evidence.get("impact") or "")
    claim_type = str(evidence.get("claim_type") or "")
    player = str(evidence.get("player") or "")
    subject = str(evidence.get("subject") or evidence.get("team") or "").lower()
    confidence = float(evidence.get("confidence") or 0.35)
    score = confidence + source_weight
    if claim_type == "injury_availability":
        score += 0.35
    if claim_type in {"recent_form", "player_form"}:
        score += 0.24
    if player:
        score += 0.16
    if claim_type in {"lineup", "market_preview"} and not player:
        score -= 0.32
    if direction == "home" and impact == "negative_away":
        score += 0.5
    elif direction == "away" and impact == "negative_home":
        score += 0.5
    elif impact in {"context_home", "context_away"}:
        score += 0.12
    if debate_focus == "neymar_availability" and "neymar" in subject:
        score += 1.0
    elif debate_focus == "morocco_availability" and (
        "morocco" in subject or "aguerd" in subject or "abde" in subject or impact == "negative_away"
    ):
        score += 1.0
    elif debate_focus == "market_pricing" and claim_type == "market_preview":
        score += 0.9
    elif debate_focus == "team_form" and claim_type == "recent_form":
        score += 0.95
    elif debate_focus == "player_form" and claim_type == "player_form":
        score += 0.95
    elif debate_focus == "source_audit" and evidence.get("source_title"):
        score += 0.55
    elif debate_focus == "stats_form" and claim_type in {"lineup", "tactical", "recent_form", "player_form"}:
        score += 0.35
    elif debate_focus == "uncertainty" and claim_type == "injury_availability":
        score += 0.25
    return score


def _prior_evidence_keys(prior_claims: list[DebateClaim]) -> tuple[set[str], set[str]]:
    subjects: set[str] = set()
    claim_texts: set[str] = set()
    for claim in prior_claims:
        message = claim.message.lower()
        for evidence in claim.referenced_evidence:
            subject = str(evidence.get("subject") or evidence.get("team") or "").lower()
            text = str(evidence.get("claim") or "").lower()[:120]
            if subject and subject in message:
                subjects.add(subject)
            if text and text[:70] in message:
                claim_texts.add(text)
    return subjects, claim_texts


def _is_counterpoint(evidence: dict, *, direction: Side) -> bool:
    impact = str(evidence.get("impact") or "")
    return (direction == "away" and impact == "negative_away") or (direction == "home" and impact == "negative_home")


def _is_supporting_evidence(evidence: dict, *, direction: Side) -> bool:
    impact = str(evidence.get("impact") or "")
    return (direction == "away" and impact == "negative_home") or (direction == "home" and impact == "negative_away")


def _matches_debate_focus(evidence: dict, debate_focus: str) -> bool:
    subject = str(evidence.get("subject") or evidence.get("team") or "").lower()
    claim_type = str(evidence.get("claim_type") or "")
    impact = str(evidence.get("impact") or "")
    if debate_focus == "neymar_availability":
        return "neymar" in subject
    if debate_focus == "morocco_availability":
        return "morocco" in subject or "aguerd" in subject or "abde" in subject or impact == "negative_away"
    if debate_focus == "market_pricing":
        return claim_type == "market_preview"
    if debate_focus == "team_form":
        return claim_type == "recent_form"
    if debate_focus == "player_form":
        return claim_type == "player_form"
    if debate_focus == "source_audit":
        return bool(evidence.get("source_title") or evidence.get("source_url"))
    if debate_focus == "stats_form":
        return claim_type in {"lineup", "tactical", "market_preview", "recent_form", "player_form"}
    if debate_focus == "uncertainty":
        return claim_type == "injury_availability"
    return False


def _select_debate_evidence(
    match: MatchContext,
    genome: Genome,
    direction: Side,
    prior_claims: list[DebateClaim],
    debate_focus: str = "",
    limit: int = 3,
) -> list[dict]:
    weights = genome.source_weights.normalized().to_dict()
    prior_subjects, prior_claim_texts = _prior_evidence_keys(prior_claims)
    scored: list[tuple[float, dict]] = []
    for finding in match.findings:
        source_weight = weights.get(finding.source_type, weights.get("news", 0.0))
        for evidence in finding.evidence_claims:
            enriched = {
                **evidence,
                "finding_id": finding.finding_id,
                "finding_name": finding.finding_name,
                "scout_name": finding.scout_name,
                "access_level": finding.access_level,
                "source_type": finding.source_type,
            }
            score = _evidence_score(
                enriched,
                direction=direction,
                source_weight=source_weight,
                debate_focus=debate_focus,
            )
            subject = str(enriched.get("subject") or enriched.get("team") or "").lower()
            claim_text = str(enriched.get("claim") or "").lower()[:120]
            if claim_text in prior_claim_texts:
                score -= 2.0
            elif subject in prior_subjects:
                score -= 0.8
            scored.append((score, enriched))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict] = []
    if debate_focus:
        for _score, evidence in scored:
            if _matches_debate_focus(evidence, debate_focus):
                selected.append(evidence)
                break
        if not selected and scored:
            selected.append(scored[0][1])
    else:
        for _score, evidence in scored:
            if _is_supporting_evidence(evidence, direction=direction):
                selected.append(evidence)
                break
    if not selected and scored:
        selected.append(scored[0][1])
    if selected:
        selected_subjects = {str(item.get("subject") or item.get("team") or "").lower() for item in selected}
        for _score, evidence in scored:
            subject = str(evidence.get("subject") or evidence.get("team") or "").lower()
            if subject in selected_subjects:
                continue
            if _is_counterpoint(evidence, direction=direction):
                selected.append(evidence)
                selected_subjects.add(subject)
                break
    for _score, evidence in scored:
        if len(selected) >= limit:
            break
        claim_text = str(evidence.get("claim") or "")
        if any(str(item.get("claim") or "") == claim_text for item in selected):
            continue
        selected.append(evidence)
    return selected


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
        prior_claims: list[DebateClaim] | None = None,
        debate_phase: str = "final",
        room_id: str = "",
        debate_role: str = "",
        debate_focus: str = "",
    ) -> DebateClaim:
        probability = self.private_baseline_probability(match)
        edge = probability - match.market_home_probability
        confidence = min(abs(edge) * 3.0 + 0.25 + rng.random() * 0.1, 0.95)
        direction: Side = "home" if edge >= 0 else "away"
        voice = voice_model or TemplateVoiceModel()
        referenced_evidence = _select_debate_evidence(
            match,
            self.genome,
            direction,
            prior_claims or [],
            debate_focus=debate_focus,
        )
        voice_prior_claims = [claim for claim in (prior_claims or []) if claim.speaker_id != self.agent_id]
        try:
            message = voice.render_claim(
                agent_name=self.name,
                genome=self.genome,
                match=match,
                probability=probability,
                direction=direction,
                evidence_claims=referenced_evidence,
                prior_claims=voice_prior_claims,
                debate_role=debate_role,
                debate_phase=debate_phase,
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
                evidence_claims=referenced_evidence,
                prior_claims=voice_prior_claims,
                debate_role=debate_role,
                debate_phase=debate_phase,
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
            debate_phase=debate_phase,
            room_id=room_id,
            debate_role=debate_role,
            evidence_tags=tags,
            referenced_evidence=referenced_evidence,
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
