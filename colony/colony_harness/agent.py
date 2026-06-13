"""Agent behavior for the Colony harness."""

from __future__ import annotations

import hashlib
import random
import re
import secrets
from dataclasses import dataclass, field

from .genes import Genome
from .models import AccessTier, BetCommitment, DebateClaim, Forecast, MatchContext, Side
from .voice import TemplateVoiceModel, VoiceModel


def _clamp_probability(value: float) -> float:
    return min(max(value, 0.01), 0.99)


def _normalize_public_message(agent_name: str, message: str) -> str:
    cleaned = " ".join(message.strip().split())
    if not cleaned or cleaned.lower() == "none":
        raise ValueError("voice model returned an empty message")
    prefix = f"{agent_name}:"
    if cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :].strip()
    return _sanitize_public_numbers(cleaned)


def _sanitize_public_numbers(text: str) -> str:
    def confidence_percent(match: re.Match[str]) -> str:
        value = float(match.group(1))
        if value >= 70:
            return "high confidence"
        if value >= 45:
            return "medium confidence"
        return "low confidence"

    def confidence_decimal(match: re.Match[str]) -> str:
        value = float(match.group(1))
        if value >= 0.7:
            return "high confidence"
        if value >= 0.45:
            return "medium confidence"
        return "low confidence"

    cleaned = re.sub(r"\b(\d+(?:\.\d+)?)%\s+confiden(?:ce|t)\b", confidence_percent, text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bconfidence\s+(?:is\s+)?(?:only\s+)?(\d?\.\d+)\b", confidence_decimal, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d?\.\d+)\s+confiden(?:ce|t)\b", confidence_decimal, cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d+(?:\.\d+)?)%\b", "a numeric signal", cleaned)
    return cleaned


def _short_voice_error(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if len(text) > 180:
        return f"{text[:177]}..."
    return text


def _short_text(text: str, limit: int = 150) -> str:
    cleaned = " ".join(str(text).strip().split())
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[: limit - 3].rstrip(" .")
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip(" .")
    return f"{clipped}..."


def _claim_ref(claim: DebateClaim) -> str:
    phase = claim.debate_phase or "final"
    room = claim.room_id or "global"
    return f"debate_claim:{claim.round_id}:{phase}:{room}:{claim.speaker_id}"


def _evidence_subject(evidence: dict) -> str:
    return str(evidence.get("subject") or evidence.get("team") or evidence.get("player") or "").strip()


def _source_quality(evidence: dict) -> str:
    explicit_quality = str(evidence.get("source_quality") or "").lower()
    if explicit_quality in {"strong", "medium", "weak"}:
        return explicit_quality
    source = str(evidence.get("source_title") or evidence.get("source_url") or evidence.get("scout_name") or "").lower()
    claim = str(evidence.get("claim") or "").lower()
    if any(marker in source for marker in ("prediction", "betting", "tips", "boostmatch", "wc26lineups", "lineup & players")):
        return "weak"
    if any(marker in source for marker in ("bbc", "espn", "rotowire", "reuters", "fifa.com", "sports illustrated")):
        return "strong"
    if any(marker in claim for marker in ("promising", "will be relied upon", "ability to compete", "high expectations")):
        return "weak"
    return "medium"


def _critique_type(
    *,
    probability: float,
    target_claim: DebateClaim,
    current_evidence: dict,
    target_evidence: dict,
) -> str:
    current_subject = _evidence_subject(current_evidence).lower()
    target_subject = _evidence_subject(target_evidence).lower()
    if target_evidence and _source_quality(target_evidence) == "weak":
        return "source_quality"
    if current_subject and target_subject and current_subject != target_subject:
        return "counter_evidence"
    if abs(probability - target_claim.stated_home_probability) < 0.006:
        return "impact_size"
    if probability > target_claim.stated_home_probability:
        return "underpriced_home"
    return "overpriced_home"


def _build_dispute_metadata(
    *,
    agent_id: str,
    debate_role: str,
    probability: float,
    prior_claims: list[DebateClaim],
    referenced_evidence: list[dict],
) -> dict:
    if debate_role not in {"challenger", "source_auditor", "skeptic"}:
        return {}
    target_claim = next((claim for claim in reversed(prior_claims) if claim.speaker_id != agent_id), None)
    if target_claim is None:
        return {}
    target_evidence = target_claim.referenced_evidence[0] if target_claim.referenced_evidence else {}
    current_evidence = referenced_evidence[0] if referenced_evidence else {}
    target_message = target_claim.message
    prefix = f"{target_claim.speaker_name}:"
    if target_message.startswith(prefix):
        target_message = target_message[len(prefix):].strip()
    return {
        "target_claim_id": _claim_ref(target_claim),
        "target_speaker_id": target_claim.speaker_id,
        "target_speaker_name": target_claim.speaker_name,
        "target_genome_id": target_claim.genome_id,
        "target_excerpt": _short_text(target_message),
        "critique_type": _critique_type(
            probability=probability,
            target_claim=target_claim,
            current_evidence=current_evidence,
            target_evidence=target_evidence,
        ),
        "probability_gap": round(probability - target_claim.stated_home_probability, 4),
        "target_subject": _evidence_subject(target_evidence),
        "counter_subject": _evidence_subject(current_evidence),
        "target_source_quality": _source_quality(target_evidence) if target_evidence else "not_evidenced",
    }


def _top_weight_labels(genome: Genome, count: int = 2) -> str:
    weights = genome.source_weights.normalized().to_dict()
    top = sorted(weights.items(), key=lambda item: item[1], reverse=True)[:count]
    return ", ".join(f"{label}={value:.2f}" for label, value in top)


def _draw_band(genome: Genome) -> float:
    profile = _risk_profile(genome)
    if profile == "secure":
        return 0.011 + max(genome.edge_threshold, 0.0) * 0.035
    if profile == "risky":
        return 0.002 + max(genome.edge_threshold, 0.0) * 0.004
    return 0.0055 + max(genome.edge_threshold, 0.0) * 0.014


def _risk_profile(genome: Genome) -> str:
    if genome.risk_appetite >= 0.135 or genome.edge_threshold <= 0.035:
        return "risky"
    if genome.risk_appetite <= 0.06 or genome.edge_threshold >= 0.105:
        return "secure"
    return "balanced"


def _forced_three_way_side(probability: float, genome: Genome) -> Side:
    if abs(probability - 0.5) <= _draw_band(genome):
        return "draw"
    return "home" if probability > 0.5 else "away"


def _side_label(side: Side, match: MatchContext) -> str:
    if side == "home":
        return match.home_team
    if side == "away":
        return match.away_team
    if side == "draw":
        return "draw"
    return "pass"


def _qualitative_shift(value: float) -> str:
    if value >= 0.015:
        return "toward home"
    if value <= -0.015:
        return "toward away"
    return "only slightly"


def _stake_fraction(genome: Genome) -> float:
    profile = _risk_profile(genome)
    if profile == "secure":
        return max(0.006, genome.risk_appetite * 0.55)
    if profile == "risky":
        return min(0.33, genome.risk_appetite * 1.35)
    return genome.risk_appetite


def _social_stance(side: Side) -> str:
    if side == "home":
        return "supportive_home"
    if side == "away":
        return "opposing_home"
    if side == "draw":
        return "neutral_draw"
    return "observer"


def _activity_level(genome: Genome) -> str:
    score = genome.query_budget + genome.risk_appetite * 5.0 + max(0.0, -genome.edge_threshold) * 2.0
    if score >= 2.35:
        return "very_active"
    if score >= 1.45:
        return "active"
    if score >= 0.75:
        return "regular"
    return "quiet"


def _influence_weight(genome: Genome, access_tier: AccessTier) -> str:
    access_bonus = {"public": 0.0, "shared": 0.25, "private": 0.45}.get(access_tier, 0.0)
    score = genome.query_budget * 0.45 + genome.risk_appetite * 2.2 + access_bonus
    if score >= 1.25:
        return "high"
    if score >= 0.65:
        return "medium"
    return "low"


def _response_delay(genome: Genome) -> str:
    if _risk_profile(genome) == "risky" or genome.query_budget >= 1.7:
        return "fast"
    if _risk_profile(genome) == "secure" and genome.query_budget <= 0.8:
        return "slow"
    return "normal"


def _active_windows(genome: Genome) -> str:
    weights = genome.source_weights.normalized()
    windows = ["pre_match"]
    if weights.news >= 0.28:
        windows.append("lineup_window")
    if weights.odds >= 0.28:
        windows.append("market_move_window")
    if weights.debate >= 0.28:
        windows.append("late_room_replies")
    if _risk_profile(genome) == "risky":
        windows.append("last_call")
    return ",".join(dict.fromkeys(windows))


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
    if claim_type == "match_history":
        score += 0.2
    if claim_type == "tactical":
        score += 0.18
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
    if debate_focus == "neymar_availability" and claim_type == "injury_availability" and "neymar" in subject:
        score += 1.0
    elif debate_focus == "morocco_availability" and claim_type == "injury_availability" and (
        "morocco" in subject or "aguerd" in subject or "abde" in subject or impact == "negative_away"
    ):
        score += 1.0
    elif debate_focus == "market_pricing" and claim_type == "market_preview":
        score += 0.9
    elif debate_focus == "team_form" and claim_type == "recent_form":
        score += 0.95
    elif debate_focus == "match_history" and claim_type == "match_history":
        score += 0.95
    elif debate_focus == "tactical_matchup" and claim_type == "tactical":
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
        return claim_type == "injury_availability" and "neymar" in subject
    if debate_focus == "morocco_availability":
        return claim_type == "injury_availability" and (
            "morocco" in subject or "aguerd" in subject or "abde" in subject or impact == "negative_away"
        )
    if debate_focus == "market_pricing":
        return claim_type == "market_preview"
    if debate_focus == "team_form":
        return claim_type == "recent_form"
    if debate_focus == "match_history":
        return claim_type == "match_history"
    if debate_focus == "tactical_matchup":
        return claim_type == "tactical"
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
    wallet_address: str = ""
    ens_name: str = ""
    parent_agent_id: str = ""
    lineage_id: str = ""
    lineage_root_agent_id: str = ""
    verified_lineage: bool = False
    world_verified: bool = False
    world_human_id: str = ""
    evolution_role: str = ""
    parent_genome_id: str = ""
    previous_genome_id: str = ""
    last_settlement: dict = field(default_factory=dict)

    @property
    def genome_id(self) -> str:
        return self.genome.stable_id()

    @property
    def world_status(self) -> str:
        return "world_verified" if self.world_verified else "unverified"

    @property
    def world_access_tier(self) -> str:
        return "premium_world" if self.world_verified else "standard"

    @property
    def public_record(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "genome_id": self.genome_id,
            "wallet_address": self.wallet_address,
            "ens_name": self.ens_name,
            "parent_agent_id": self.parent_agent_id,
            "lineage_id": self.lineage_id,
            "lineage_root_agent_id": self.lineage_root_agent_id,
            "verified_lineage": self.verified_lineage,
            "world_verified": self.world_verified,
            "world_human_id": self.world_human_id,
            "world_status": self.world_status,
            "world_access_tier": self.world_access_tier,
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
        dispute = _build_dispute_metadata(
            agent_id=self.agent_id,
            debate_role=debate_role,
            probability=probability,
            prior_claims=prior_claims or [],
            referenced_evidence=referenced_evidence,
        )
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
                dispute=dispute,
            )
            message = _normalize_public_message(self.name, message)
        except Exception as exc:
            recovery_voice = TemplateVoiceModel()
            message = recovery_voice.render_claim(
                agent_name=self.name,
                genome=self.genome,
                match=match,
                probability=probability,
                direction=direction,
                evidence_claims=referenced_evidence,
                prior_claims=voice_prior_claims,
                debate_role=debate_role,
                debate_phase=debate_phase,
                dispute=dispute,
            )
            message = f"{message} [voice recovery: {_short_voice_error(exc)}]"

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
            dispute=dispute,
            genome_id=self.genome_id,
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

        side = _forced_three_way_side(probability, self.genome)
        if side == "home":
            edge = home_edge
        elif side == "away":
            edge = away_edge
        else:
            edge = max(0.0025, _draw_band(self.genome) - abs(probability - 0.5))
        risk_profile = _risk_profile(self.genome)
        decision_reason = (
            f"{risk_profile} group-stage pick: {_side_label(side, match)}; "
            f"debate moved the read {_qualitative_shift(debate_shift)}; "
            f"top inputs {_top_weight_labels(self.genome)}"
        )

        stake = round(max(0.0001, self.bankroll * _stake_fraction(self.genome)), 4)
        return Forecast(
            agent_id=self.agent_id,
            wallet_address=self.wallet_address,
            ens_name=self.ens_name,
            access_tier=access_tier,
            visible_findings=visible_findings,
            persona=self.genome.persona,
            risk_profile=risk_profile,
            social_stance=_social_stance(side),
            activity_level=_activity_level(self.genome),
            influence_weight=_influence_weight(self.genome, access_tier),
            response_delay=_response_delay(self.genome),
            active_windows=_active_windows(self.genome),
            home_probability=round(probability, 4),
            market_edge=round(home_edge, 4),
            edge_threshold=self.genome.edge_threshold,
            edge=round(edge, 4),
            side=side,
            stake=stake,
            bankroll=round(self.bankroll, 4),
            decision_reason=decision_reason,
            genome_id=self.genome_id,
        )

    def commit_bet(self, forecast: Forecast, round_id: str) -> BetCommitment:
        salt = secrets.token_hex(16)
        reveal = {
            "agent_id": self.agent_id,
            "genome_id": self.genome_id,
            "wallet_address": self.wallet_address,
            "ens_name": self.ens_name,
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
