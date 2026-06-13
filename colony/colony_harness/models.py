"""Shared data models for the Colony harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

Side = Literal["home", "draw", "away", "pass"]
AccessLevel = Literal["public", "shared", "private"]
AccessTier = Literal["public", "shared", "private"]
SourceType = Literal["market", "stats", "odds", "news", "lineup", "social", "weather", "retrieval", "other"]
EntityType = Literal[
    "tournament",
    "group",
    "stage",
    "venue",
    "team",
    "match",
    "match_result",
    "availability_event",
    "scouting_topic",
    "team_scouting_topic",
    "team_match_profile",
    "scouting_gap",
    "finding",
    "evidence_claim",
    "scout_match_profile",
    "source",
    "source_domain",
    "source_domain_profile",
    "source_kind",
    "source_quality",
    "source_recency",
    "availability_status",
    "body_part",
    "scout",
    "claim_type",
    "claim_impact",
    "claim_quality",
    "metric",
    "player_stat_line",
    "player",
    "player_match_profile",
    "club",
    "position",
    "formation",
    "genome",
    "predictor",
    "debate_claim",
    "prediction",
]


@dataclass(frozen=True)
class Finding:
    finding_id: str
    scout_name: str
    access_level: AccessLevel
    source_type: SourceType
    finding_name: str
    home_probability: float | None
    home_delta: float | None
    confidence: float
    cost: float
    citations: list[str] = field(default_factory=list)
    summary: str = ""
    evidence_claims: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorldEntity:
    entity_id: str
    entity_type: EntityType
    name: str
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorldRelationship:
    source_id: str
    relation_type: str
    target_id: str
    weight: float = 1.0
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class WorldGraph:
    graph_id: str
    round_id: str
    entities: list[WorldEntity]
    relationships: list[WorldRelationship]

    def to_dict(self) -> dict:
        return {
            "graph_id": self.graph_id,
            "round_id": self.round_id,
            "entities": [entity.to_dict() for entity in self.entities],
            "relationships": [relationship.to_dict() for relationship in self.relationships],
        }


@dataclass(frozen=True)
class MatchContext:
    round_id: str
    home_team: str
    away_team: str
    market_home_probability: float
    stats_home_signal: float
    odds_home_signal: float
    news_home_signal: float
    match_date: str = ""
    match_time: str = ""
    group_name: str = ""
    stage_name: str = ""
    venue_name: str = ""
    score: str = ""
    findings: list[Finding] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "MatchContext":
        from .scouts import mock_findings_from_config

        match = data["match"]
        market = float(match["market_home_probability"])
        stats = float(match["stats_home_signal"])
        odds = float(match["odds_home_signal"])
        news = float(match["news_home_signal"])
        home_team = match["home_team"]
        away_team = match["away_team"]
        round_id = data["round_id"]
        findings = mock_findings_from_config(data)
        return cls(
            round_id=round_id,
            home_team=home_team,
            away_team=away_team,
            market_home_probability=market,
            stats_home_signal=stats,
            odds_home_signal=odds,
            news_home_signal=news,
            match_date=str(match.get("date") or ""),
            match_time=str(match.get("time") or ""),
            group_name=str(match.get("group") or ""),
            stage_name=str(match.get("round") or match.get("stage") or ""),
            venue_name=str(match.get("ground") or match.get("venue") or ""),
            score=str(match.get("score") or ""),
            findings=findings,
        )


@dataclass(frozen=True)
class KnowledgeView:
    agent_id: str
    access_tier: AccessTier
    visible_findings: list[Finding]
    market_home_probability: float
    stats_home_signal: float
    odds_home_signal: float
    news_home_signal: float

    def to_match_context(self, match: MatchContext) -> MatchContext:
        return MatchContext(
            round_id=match.round_id,
            home_team=match.home_team,
            away_team=match.away_team,
            market_home_probability=self.market_home_probability,
            stats_home_signal=self.stats_home_signal,
            odds_home_signal=self.odds_home_signal,
            news_home_signal=self.news_home_signal,
            match_date=match.match_date,
            match_time=match.match_time,
            group_name=match.group_name,
            stage_name=match.stage_name,
            venue_name=match.venue_name,
            score=match.score,
            findings=self.visible_findings,
        )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "access_tier": self.access_tier,
            "visible_findings": len(self.visible_findings),
            "visible_finding_ids": [finding.finding_id for finding in self.visible_findings],
            "source_probabilities": {
                "market": self.market_home_probability,
                "stats": self.stats_home_signal,
                "odds": self.odds_home_signal,
                "news": self.news_home_signal,
            },
        }


@dataclass(frozen=True)
class DebateClaim:
    round_id: str
    speaker_id: str
    speaker_name: str
    model: str
    persona: str
    access_tier: AccessTier
    visible_findings: int
    claim_type: str
    selection_reason: str
    stated_home_probability: float
    confidence: float
    direction: Side
    message: str
    debate_phase: str = "final"
    room_id: str = ""
    debate_role: str = ""
    evidence_tags: list[str] = field(default_factory=list)
    referenced_evidence: list[dict] = field(default_factory=list)
    dispute: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    genome_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DebateRoom:
    room_id: str
    stance: str
    evidence_focus: str
    participant_ids: list[str]
    representative_ids: list[str]
    claims: list[DebateClaim]
    synthesis_home_probability: float | None
    synthesis_confidence: float
    synthesis: str

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "stance": self.stance,
            "evidence_focus": self.evidence_focus,
            "participant_ids": self.participant_ids,
            "representative_ids": self.representative_ids,
            "claims": [claim.to_dict() for claim in self.claims],
            "synthesis_home_probability": self.synthesis_home_probability,
            "synthesis_confidence": self.synthesis_confidence,
            "synthesis": self.synthesis,
        }


@dataclass(frozen=True)
class SocialAction:
    action_id: str
    round_id: str
    room_id: str
    phase: str
    action_type: str
    actor_id: str
    actor_name: str
    role: str
    stance: str
    target_action_id: str
    target_actor_id: str
    topic: str
    text: str
    grounded_elements: list[dict] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    weight: float = 1.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Forecast:
    agent_id: str
    wallet_address: str
    ens_name: str
    access_tier: AccessTier
    visible_findings: int
    persona: str
    risk_profile: str
    social_stance: str
    activity_level: str
    influence_weight: str
    response_delay: str
    active_windows: str
    home_probability: float
    market_edge: float
    edge_threshold: float
    edge: float
    side: Side
    stake: float
    bankroll: float
    decision_reason: str
    genome_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class BetCommitment:
    agent_id: str
    round_id: str
    commitment: str
    reveal: dict

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CollectiveDecision:
    round_id: str
    match: dict
    method: dict
    match_call: dict
    prediction: dict
    recommendation: dict
    internal_metrics: dict
    score_projection: dict
    vote_breakdown: dict
    top_supporters: list[dict]
    agent_predictions: list[dict]
    agent_votes: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RoundResult:
    round_id: str
    rooms: list[DebateRoom]
    claims: list[DebateClaim]
    social_actions: list[SocialAction]
    forecasts: list[Forecast]
    commitments: list[BetCommitment]
    findings: list[Finding]
    knowledge_views: list[KnowledgeView]
    world_graph: WorldGraph
    collective_decision: CollectiveDecision
    summary: dict

    def to_dict(self) -> dict:
        return {
            "round_id": self.round_id,
            "findings": [finding.to_dict() for finding in self.findings],
            "knowledge_views": [view.to_dict() for view in self.knowledge_views],
            "world_graph": self.world_graph.to_dict(),
            "rooms": [room.to_dict() for room in self.rooms],
            "claims": [claim.to_dict() for claim in self.claims],
            "social_actions": [action.to_dict() for action in self.social_actions],
            "forecasts": [forecast.to_dict() for forecast in self.forecasts],
            "commitments": [commitment.to_dict() for commitment in self.commitments],
            "collective_decision": self.collective_decision.to_dict(),
            "summary": self.summary,
        }
