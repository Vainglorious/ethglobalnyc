"""Access-filtered knowledge views for Colony predictors."""

from __future__ import annotations

from collections.abc import Iterable

from .agent import AntAgent
from .models import AccessTier, Finding, KnowledgeView, MatchContext


class KnowledgeAccessPolicy:
    """Turn a predictor budget into a filtered view of the full match graph."""

    shared_budget_threshold = 0.75
    private_budget_threshold = 1.5

    def tier_for_agent(self, agent: AntAgent) -> AccessTier:
        budget = agent.genome.query_budget
        if budget >= self.private_budget_threshold:
            return "private"
        if budget >= self.shared_budget_threshold:
            return "shared"
        return "public"

    def visible_findings(self, findings: Iterable[Finding], access_tier: AccessTier) -> list[Finding]:
        allowed = _allowed_levels(access_tier)
        return [finding for finding in findings if finding.access_level in allowed]


def build_knowledge_views(
    match: MatchContext,
    agents: Iterable[AntAgent],
    policy: KnowledgeAccessPolicy | None = None,
) -> dict[str, KnowledgeView]:
    access_policy = policy or KnowledgeAccessPolicy()
    views: dict[str, KnowledgeView] = {}
    for agent in agents:
        tier = access_policy.tier_for_agent(agent)
        findings = access_policy.visible_findings(match.findings, tier)
        views[agent.agent_id] = KnowledgeView(
            agent_id=agent.agent_id,
            access_tier=tier,
            visible_findings=findings,
            market_home_probability=_source_probability(
                findings,
                source_types={"market"},
                baseline=match.market_home_probability,
            ),
            stats_home_signal=_source_probability(
                findings,
                source_types={"stats", "lineup"},
                baseline=match.stats_home_signal,
            ),
            odds_home_signal=_source_probability(
                findings,
                source_types={"odds"},
                baseline=match.odds_home_signal,
            ),
            news_home_signal=_source_probability(
                findings,
                source_types={"news", "social", "weather", "retrieval"},
                baseline=match.news_home_signal,
            ),
        )
    return views


def _allowed_levels(access_tier: AccessTier) -> set[str]:
    if access_tier == "private":
        return {"public", "shared", "private"}
    if access_tier == "shared":
        return {"public", "shared"}
    return {"public"}


def _source_probability(findings: list[Finding], *, source_types: set[str], baseline: float) -> float:
    weighted_total = 0.0
    weight = 0.0
    for finding in findings:
        if finding.source_type not in source_types or finding.home_probability is None:
            continue
        confidence = max(finding.confidence, 0.01)
        weighted_total += finding.home_probability * confidence
        weight += confidence
    if weight <= 0:
        return baseline
    return round(weighted_total / weight, 4)
