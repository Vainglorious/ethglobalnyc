"""Lightweight match-round subgraph for run memory."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from urllib.parse import urlparse

from .models import DebateClaim, Forecast, MatchContext, WorldEntity, WorldGraph, WorldRelationship
from .scouting_taxonomy import (
    SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES,
    SCOUTING_REQUIRED_CLAIM_TYPES,
    SCOUTING_RESCOUT_RECIPES,
)


def build_world_graph(
    match: MatchContext,
    *,
    claims: list[DebateClaim] | None = None,
    forecasts: list[Forecast] | None = None,
) -> WorldGraph:
    entities: list[WorldEntity] = [
        WorldEntity(
            entity_id=f"team:{_slug(match.home_team)}",
            entity_type="team",
            name=match.home_team,
            attributes={"side": "home"},
        ),
        WorldEntity(
            entity_id=f"team:{_slug(match.away_team)}",
            entity_type="team",
            name=match.away_team,
            attributes={"side": "away"},
        ),
        WorldEntity(
            entity_id=f"match:{match.round_id}",
            entity_type="match",
            name=f"{match.home_team} vs {match.away_team}",
            attributes={
                "round_id": match.round_id,
                "market_home_probability": match.market_home_probability,
                "date": match.match_date,
                "time": match.match_time,
                "group": match.group_name,
                "stage": match.stage_name,
                "venue": match.venue_name,
                "score": match.score,
            },
        ),
    ]
    relationships: list[WorldRelationship] = [
        WorldRelationship(
            source_id=f"team:{_slug(match.home_team)}",
            relation_type="plays_home_in",
            target_id=f"match:{match.round_id}",
        ),
        WorldRelationship(
            source_id=f"team:{_slug(match.away_team)}",
            relation_type="plays_away_in",
            target_id=f"match:{match.round_id}",
        ),
    ]
    _append_match_metadata_nodes(entities, relationships, match)

    for finding in match.findings:
        finding_id = f"finding:{finding.finding_id}"
        scout_id = f"scout:{_slug(finding.scout_name)}"
        entities.append(
            WorldEntity(
                entity_id=finding_id,
                entity_type="finding",
                name=finding.finding_name,
                attributes=finding.to_dict(),
            )
        )
        entities.append(
            WorldEntity(
                entity_id=scout_id,
                entity_type="scout",
                name=finding.scout_name,
                attributes={
                    "access_level": finding.access_level,
                    "source_type": finding.source_type,
                },
            )
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=finding_id,
                    relation_type="concerns",
                    target_id=f"match:{match.round_id}",
                    weight=finding.confidence,
                ),
                WorldRelationship(
                    source_id=scout_id,
                    relation_type="produced",
                    target_id=finding_id,
                    weight=finding.confidence,
                ),
            ]
        )
        _append_evidence_claims(
            entities,
            relationships,
            match=match,
            finding_id=finding_id,
            finding_key=finding.finding_id,
            evidence_claims=finding.evidence_claims,
        )

    _append_scouting_topic_nodes(entities, relationships, match=match)
    _append_team_scouting_topic_nodes(entities, relationships, match=match)

    if forecasts is not None:
        for forecast in forecasts:
            predictor_id = f"predictor:{forecast.agent_id}"
            prediction_id = f"prediction:{match.round_id}:{forecast.agent_id}"
            genome_id = f"genome:{forecast.genome_id}" if forecast.genome_id else ""
            entities.extend(
                [
                    WorldEntity(
                        entity_id=predictor_id,
                        entity_type="predictor",
                        name=forecast.agent_id,
                        attributes={"bankroll": forecast.bankroll, "genome_id": forecast.genome_id},
                    ),
                    WorldEntity(
                        entity_id=prediction_id,
                        entity_type="prediction",
                        name=f"{forecast.agent_id} prediction",
                        attributes=forecast.to_dict(),
                    ),
                ]
            )
            if genome_id:
                entities.append(
                    WorldEntity(
                        entity_id=genome_id,
                        entity_type="genome",
                        name=forecast.genome_id,
                        attributes={"genome_id": forecast.genome_id},
                    )
                )
            relationships.extend(
                [
                    WorldRelationship(
                        source_id=predictor_id,
                        relation_type="made_prediction",
                        target_id=prediction_id,
                    ),
                    WorldRelationship(
                        source_id=prediction_id,
                        relation_type="concerns",
                        target_id=f"match:{match.round_id}",
                    ),
                ]
            )
            if genome_id:
                relationships.append(
                    WorldRelationship(
                        source_id=predictor_id,
                        relation_type="instantiates_genome",
                        target_id=genome_id,
                    )
                )

    if claims is not None:
        for claim in claims:
            phase = claim.debate_phase or "final"
            room = claim.room_id or "global"
            claim_id = f"debate_claim:{match.round_id}:{phase}:{room}:{claim.speaker_id}"
            genome_id = f"genome:{claim.genome_id}" if claim.genome_id else ""
            entities.append(
                WorldEntity(
                    entity_id=claim_id,
                    entity_type="debate_claim",
                    name=f"{claim.speaker_name} claim",
                    attributes=claim.to_dict(),
                )
            )
            relationships.extend(
                [
                    WorldRelationship(
                        source_id=f"predictor:{claim.speaker_id}",
                        relation_type="published_claim",
                        target_id=claim_id,
                        weight=claim.confidence,
                    ),
                    WorldRelationship(
                        source_id=claim_id,
                        relation_type="concerns",
                        target_id=f"match:{match.round_id}",
                        weight=claim.confidence,
                    ),
                ]
            )
            if genome_id:
                relationships.append(
                    WorldRelationship(
                        source_id=claim_id,
                        relation_type="expresses_genome",
                        target_id=genome_id,
                        weight=claim.confidence,
                    )
                )
            if claim.dispute.get("target_claim_id"):
                relationships.append(
                    WorldRelationship(
                        source_id=claim_id,
                        relation_type="disputes",
                        target_id=str(claim.dispute["target_claim_id"]),
                        weight=claim.confidence,
                        attributes={
                            "critique_type": claim.dispute.get("critique_type"),
                            "probability_gap": claim.dispute.get("probability_gap"),
                            "target_subject": claim.dispute.get("target_subject"),
                            "counter_subject": claim.dispute.get("counter_subject"),
                        },
                    )
                )

    return WorldGraph(
        graph_id=f"world_graph:{match.round_id}",
        round_id=match.round_id,
        entities=_dedupe_entities(entities),
        relationships=_dedupe_relationships(relationships),
    )


def _append_evidence_claims(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
    finding_id: str,
    finding_key: str,
    evidence_claims: list[dict],
) -> None:
    for index, evidence in enumerate(evidence_claims):
        if not _admissible_evidence(evidence):
            continue
        claim_id = f"evidence_claim:{_stable_key(finding_key, str(index), evidence.get('claim', ''))}"
        source_url = str(evidence.get("source_url") or "")
        source_title = str(evidence.get("source_title") or "Source")
        source_id = f"source:{_stable_key(source_url or source_title)}"
        team = _normal_text(evidence.get("team"))
        player = _normal_text(evidence.get("player"))
        claim_type = _normal_text(evidence.get("claim_type"))
        impact = _normal_text(evidence.get("impact"))
        confidence = _float_or_default(evidence.get("confidence"), 0.5)

        entities.append(
            WorldEntity(
                entity_id=claim_id,
                entity_type="evidence_claim",
                name=_claim_name(evidence),
                attributes={
                    **evidence,
                    "finding_id": finding_key,
                    "match_id": f"match:{match.round_id}",
                },
            )
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=finding_id,
                    relation_type="has_evidence_claim",
                    target_id=claim_id,
                    weight=confidence,
                ),
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="concerns",
                    target_id=f"match:{match.round_id}",
                    weight=confidence,
                ),
            ]
        )
        if claim_type:
            claim_type_id = f"claim_type:{_slug(claim_type)}"
            topic_id = f"scouting_topic:{_stable_key(match.round_id, claim_type)}"
            entities.append(
                WorldEntity(
                    entity_id=claim_type_id,
                    entity_type="claim_type",
                    name=claim_type,
                    attributes={},
                )
            )
            relationships.append(
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="has_claim_type",
                    target_id=claim_type_id,
                    weight=confidence,
                )
            )
            relationships.append(
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="supports_scouting_topic",
                    target_id=topic_id,
                    weight=confidence,
                )
            )
            matched_team = _evidence_match_team(evidence, match)
            if matched_team:
                relationships.append(
                    WorldRelationship(
                        source_id=claim_id,
                        relation_type="supports_team_scouting_topic",
                        target_id=f"team_scouting_topic:{_stable_key(match.round_id, matched_team, claim_type)}",
                        weight=confidence,
                    )
                )
        if impact:
            impact_id = f"claim_impact:{_slug(impact)}"
            entities.append(
                WorldEntity(
                    entity_id=impact_id,
                    entity_type="claim_impact",
                    name=impact,
                    attributes=_impact_attributes(impact),
                )
            )
            relationships.append(
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="has_claim_impact",
                    target_id=impact_id,
                    weight=confidence,
                )
            )
        _append_metric_nodes(
            entities,
            relationships,
            claim_id=claim_id,
            evidence=evidence,
            confidence=confidence,
        )
        _append_player_stat_line_node(
            entities,
            relationships,
            claim_id=claim_id,
            evidence=evidence,
            confidence=confidence,
        )
        _append_match_result_node(
            entities,
            relationships,
            match=match,
            claim_id=claim_id,
            evidence=evidence,
            confidence=confidence,
        )
        _append_availability_event_node(
            entities,
            relationships,
            match=match,
            claim_id=claim_id,
            evidence=evidence,
            confidence=confidence,
        )
        _append_formation_node(
            entities,
            relationships,
            match=match,
            claim_id=claim_id,
            evidence=evidence,
            confidence=confidence,
        )

        if source_url or source_title:
            domain = _domain(source_url)
            source_kind = _normal_text(evidence.get("source_kind"))
            source_quality = _normal_text(evidence.get("source_quality"))
            source_recency = _normal_text(evidence.get("source_recency_bucket"))
            entities.append(
                WorldEntity(
                    entity_id=source_id,
                    entity_type="source",
                    name=source_title,
                    attributes={
                        "title": source_title,
                        "url": source_url,
                        "domain": domain,
                        "published_at": str(evidence.get("source_published") or ""),
                        "published_date": str(evidence.get("source_published_date") or ""),
                        "recency_days": evidence.get("source_recency_days"),
                        "recency_bucket": source_recency,
                        "source_kind": source_kind,
                        "source_quality": source_quality,
                        "trust_score": _source_quality_score(source_quality),
                    },
                )
            )
            relationships.append(
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="evidenced_by",
                    target_id=source_id,
                    weight=confidence,
                )
            )
            if domain:
                domain_id = f"source_domain:{_slug(domain)}"
                entities.append(
                    WorldEntity(
                        entity_id=domain_id,
                        entity_type="source_domain",
                        name=domain,
                        attributes={},
                    )
                )
                relationships.append(
                    WorldRelationship(
                        source_id=source_id,
                        relation_type="from_domain",
                        target_id=domain_id,
                        weight=confidence,
                    )
                )
            if source_kind:
                kind_id = f"source_kind:{_slug(source_kind)}"
                entities.append(
                    WorldEntity(
                        entity_id=kind_id,
                        entity_type="source_kind",
                        name=source_kind,
                        attributes={},
                    )
                )
                relationships.append(
                    WorldRelationship(
                        source_id=source_id,
                        relation_type="has_source_kind",
                        target_id=kind_id,
                        weight=confidence,
                    )
                )
            if source_quality:
                quality_id = f"source_quality:{_slug(source_quality)}"
                quality_score = _source_quality_score(source_quality)
                entities.append(
                    WorldEntity(
                        entity_id=quality_id,
                        entity_type="source_quality",
                        name=source_quality,
                        attributes={"trust_score": quality_score},
                    )
                )
                relationships.append(
                    WorldRelationship(
                        source_id=source_id,
                        relation_type="has_source_quality",
                        target_id=quality_id,
                        weight=quality_score,
                    )
                )
            if source_recency:
                recency_id = f"source_recency:{_slug(source_recency)}"
                entities.append(
                    WorldEntity(
                        entity_id=recency_id,
                        entity_type="source_recency",
                        name=source_recency,
                        attributes={},
                    )
                )
                relationships.append(
                    WorldRelationship(
                        source_id=source_id,
                        relation_type="has_source_recency",
                        target_id=recency_id,
                        weight=confidence,
                    )
                )

        if team:
            team_id = f"team:{_slug(team)}"
            entities.append(WorldEntity(entity_id=team_id, entity_type="team", name=team, attributes={}))
            relationships.append(
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="about_team",
                    target_id=team_id,
                    weight=confidence,
                )
            )

        if player:
            player_id = f"player:{_slug(player)}"
            entities.append(
                WorldEntity(
                    entity_id=player_id,
                    entity_type="player",
                    name=player,
                    attributes={"team": team} if team else {},
                )
            )
            relationships.append(
                WorldRelationship(
                    source_id=claim_id,
                    relation_type="about_player",
                    target_id=player_id,
                    weight=confidence,
                )
            )
            if team:
                relationships.append(
                    WorldRelationship(
                        source_id=player_id,
                        relation_type="member_of",
                        target_id=f"team:{_slug(team)}",
                    )
                )
            _append_player_context_nodes(
                entities,
                relationships,
                player_id=player_id,
                evidence=evidence,
                confidence=confidence,
    )


def _append_match_metadata_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    match: MatchContext,
) -> None:
    match_id = f"match:{match.round_id}"
    if match.venue_name:
        venue_id = f"venue:{_slug(match.venue_name)}"
        entities.append(
            WorldEntity(
                entity_id=venue_id,
                entity_type="venue",
                name=match.venue_name,
                attributes={},
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=match_id,
                relation_type="played_at",
                target_id=venue_id,
            )
        )
    if match.group_name:
        group_id = f"group:{_slug(match.group_name)}"
        entities.append(
            WorldEntity(
                entity_id=group_id,
                entity_type="group",
                name=match.group_name,
                attributes={},
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=match_id,
                relation_type="part_of_group",
                target_id=group_id,
            )
        )
    if match.stage_name:
        stage_id = f"stage:{_slug(match.stage_name)}"
        entities.append(
            WorldEntity(
                entity_id=stage_id,
                entity_type="stage",
                name=match.stage_name,
                attributes={},
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=match_id,
                relation_type="part_of_stage",
                target_id=stage_id,
            )
        )


def _append_scouting_topic_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    claim_counts: Counter[str] = Counter()
    source_urls_by_type: dict[str, set[str]] = defaultdict(set)
    metric_counts: Counter[str] = Counter()
    for finding in match.findings:
        for evidence in finding.evidence_claims:
            if not _admissible_evidence(evidence):
                continue
            claim_type = _normal_text(evidence.get("claim_type"))
            if not claim_type:
                continue
            claim_counts[claim_type] += 1
            source_url = _normal_text(evidence.get("source_url"))
            if source_url:
                source_urls_by_type[claim_type].add(source_url)
            if evidence.get("metrics"):
                metric_counts[claim_type] += 1

    all_topics = sorted(set(SCOUTING_REQUIRED_CLAIM_TYPES) | set(claim_counts))
    for claim_type in all_topics:
        claim_count = claim_counts[claim_type]
        coverage_status = "covered" if claim_count else "missing"
        topic_id = f"scouting_topic:{_stable_key(match.round_id, claim_type)}"
        claim_type_id = f"claim_type:{_slug(claim_type)}"
        entities.extend(
            [
                WorldEntity(
                    entity_id=topic_id,
                    entity_type="scouting_topic",
                    name=claim_type,
                    attributes={
                        "claim_type": claim_type,
                        "required": claim_type in SCOUTING_REQUIRED_CLAIM_TYPES,
                        "coverage_status": coverage_status,
                        "claim_count": claim_count,
                        "unique_source_count": len(source_urls_by_type.get(claim_type, set())),
                        "metric_claim_count": metric_counts[claim_type],
                    },
                ),
                WorldEntity(
                    entity_id=claim_type_id,
                    entity_type="claim_type",
                    name=claim_type,
                    attributes={},
                ),
            ]
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=f"match:{match.round_id}",
                    relation_type="has_scouting_topic",
                    target_id=topic_id,
                    weight=1.0 if claim_count else 0.0,
                ),
                WorldRelationship(
                    source_id=topic_id,
                    relation_type="tracks_claim_type",
                    target_id=claim_type_id,
                    weight=1.0 if claim_count else 0.0,
                ),
            ]
        )


def _append_team_scouting_topic_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    team_names = (match.home_team, match.away_team)
    claim_counts: Counter[tuple[str, str]] = Counter()
    metric_counts: Counter[tuple[str, str]] = Counter()
    dated_counts: Counter[tuple[str, str]] = Counter()
    recent_counts: Counter[tuple[str, str]] = Counter()
    strong_or_official_counts: Counter[tuple[str, str]] = Counter()
    source_urls_by_team_type: dict[tuple[str, str], set[str]] = defaultdict(set)
    players_by_team_type: dict[tuple[str, str], set[str]] = defaultdict(set)
    observed_topics: set[str] = set()

    for finding in match.findings:
        for evidence in finding.evidence_claims:
            if not _admissible_evidence(evidence):
                continue
            claim_type = _normal_text(evidence.get("claim_type"))
            team = _evidence_match_team(evidence, match)
            if not claim_type or not team:
                continue
            key = (team, claim_type)
            observed_topics.add(claim_type)
            claim_counts[key] += 1
            source_url = _normal_text(evidence.get("source_url"))
            if source_url:
                source_urls_by_team_type[key].add(source_url)
            player = _normal_text(evidence.get("player"))
            if player:
                players_by_team_type[key].add(player)
            if evidence.get("metrics"):
                metric_counts[key] += 1
            if _normal_text(evidence.get("source_published_date")):
                dated_counts[key] += 1
            if _normal_text(evidence.get("source_recency_bucket")) in {"last_7_days", "last_30_days"}:
                recent_counts[key] += 1
            if _normal_text(evidence.get("source_quality")).lower() == "strong" or _normal_text(
                evidence.get("source_kind")
            ).lower() in {"official", "stats", "news"}:
                strong_or_official_counts[key] += 1

    all_topics = sorted(set(SCOUTING_REQUIRED_CLAIM_TYPES) | observed_topics)
    for team in team_names:
        side = "home" if team == match.home_team else "away"
        team_id = f"team:{_slug(team)}"
        for claim_type in all_topics:
            key = (team, claim_type)
            claim_count = claim_counts[key]
            coverage_status = "covered" if claim_count else "missing"
            fresh_required = claim_type in SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES
            freshness_status = _topic_freshness_status(
                claim_count=claim_count,
                fresh_required=fresh_required,
                recent_claim_count=recent_counts[key],
            )
            source_strength_status = (
                "strong_or_official" if strong_or_official_counts[key] else ("missing" if not claim_count else "needs_stronger_source")
            )
            topic_id = f"team_scouting_topic:{_stable_key(match.round_id, team, claim_type)}"
            claim_type_id = f"claim_type:{_slug(claim_type)}"
            entities.extend(
                [
                    WorldEntity(
                        entity_id=topic_id,
                        entity_type="team_scouting_topic",
                        name=f"{team} {claim_type}",
                        attributes={
                            "team": team,
                            "side": side,
                            "claim_type": claim_type,
                            "required": claim_type in SCOUTING_REQUIRED_CLAIM_TYPES,
                            "coverage_status": coverage_status,
                            "claim_count": claim_count,
                            "unique_source_count": len(source_urls_by_team_type.get(key, set())),
                            "metric_claim_count": metric_counts[key],
                            "player_count": len(players_by_team_type.get(key, set())),
                            "freshness_required": fresh_required,
                            "freshness_status": freshness_status,
                            "dated_claim_count": dated_counts[key],
                            "recent_30d_claim_count": recent_counts[key],
                            "strong_or_official_claim_count": strong_or_official_counts[key],
                            "source_strength_status": source_strength_status,
                        },
                    ),
                    WorldEntity(
                        entity_id=claim_type_id,
                        entity_type="claim_type",
                        name=claim_type,
                        attributes={},
                    ),
                ]
            )
            relationships.extend(
                [
                    WorldRelationship(
                        source_id=team_id,
                        relation_type="has_team_scouting_topic",
                        target_id=topic_id,
                        weight=1.0 if claim_count else 0.0,
                    ),
                    WorldRelationship(
                        source_id=f"match:{match.round_id}",
                        relation_type="has_team_scouting_topic",
                        target_id=topic_id,
                        weight=1.0 if claim_count else 0.0,
                    ),
                    WorldRelationship(
                        source_id=topic_id,
                        relation_type="tracks_claim_type",
                        target_id=claim_type_id,
                        weight=1.0 if claim_count else 0.0,
                    ),
                ]
            )
            if claim_type in SCOUTING_REQUIRED_CLAIM_TYPES and not claim_count:
                _append_scouting_gap_node(
                    entities,
                    relationships,
                    match=match,
                    team=team,
                    team_id=team_id,
                    side=side,
                    claim_type=claim_type,
                    topic_id=topic_id,
                    claim_type_id=claim_type_id,
                )
            elif claim_type in SCOUTING_REQUIRED_CLAIM_TYPES and freshness_status == "needs_fresh_source":
                _append_scouting_gap_node(
                    entities,
                    relationships,
                    match=match,
                    team=team,
                    team_id=team_id,
                    side=side,
                    claim_type=claim_type,
                    topic_id=topic_id,
                    claim_type_id=claim_type_id,
                    status="needs_fresh_rescout",
                    gap_reason="covered_topic_without_recent_source",
                )


def _append_scouting_gap_node(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
    team: str,
    team_id: str,
    side: str,
    claim_type: str,
    topic_id: str,
    claim_type_id: str,
    status: str = "needs_rescout",
    gap_reason: str = "missing_required_topic",
) -> None:
    recipe = SCOUTING_RESCOUT_RECIPES.get(claim_type, {})
    gap_id = f"scouting_gap:{_stable_key(match.round_id, team, claim_type, status)}"
    entities.append(
        WorldEntity(
            entity_id=gap_id,
            entity_type="scouting_gap",
            name=f"{team} {claim_type} gap",
            attributes={
                "status": status,
                "gap_reason": gap_reason,
                "team": team,
                "side": side,
                "claim_type": claim_type,
                "priority": int(recipe.get("priority") or 40),
                "recommended_scout": str(recipe.get("recommended_scout") or f"{claim_type}_scout"),
                "query_focus": str(recipe.get("query_focus") or claim_type.replace("_", " ")),
                "acceptance_criteria": list(recipe.get("acceptance_criteria") or []),
                "target_entity_id": topic_id,
                "write_policy": "Admit only sourced evidence_claims; keep the KG topic missing when no admissible source is found.",
            },
        )
    )
    relationships.extend(
        [
            WorldRelationship(
                source_id=f"match:{match.round_id}",
                relation_type="has_scouting_gap",
                target_id=gap_id,
                weight=1.0,
            ),
            WorldRelationship(
                source_id=team_id,
                relation_type="has_scouting_gap",
                target_id=gap_id,
                weight=1.0,
            ),
            WorldRelationship(
                source_id=gap_id,
                relation_type="targets_team_scouting_topic",
                target_id=topic_id,
                weight=1.0,
            ),
            WorldRelationship(
                source_id=gap_id,
                relation_type="tracks_claim_type",
                target_id=claim_type_id,
                weight=1.0,
            ),
        ]
    )


def _topic_freshness_status(*, claim_count: int, fresh_required: bool, recent_claim_count: int) -> str:
    if not claim_count:
        return "missing"
    if not fresh_required:
        return "not_required"
    if recent_claim_count:
        return "fresh"
    return "needs_fresh_source"


def _append_metric_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    claim_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, dict):
        return
    for key, value in metrics.items():
        if value in {None, ""}:
            continue
        metric_id = f"metric:{_stable_key(claim_id, str(key), str(value))}"
        entities.append(
            WorldEntity(
                entity_id=metric_id,
                entity_type="metric",
                name=str(key),
                attributes={
                    "metric_key": str(key),
                    "value": value,
                    "unit": _metric_unit(str(key)),
                    "claim_id": claim_id,
                    "subject": evidence.get("subject"),
                    "team": evidence.get("team"),
                    "player": evidence.get("player"),
                    "source_url": evidence.get("source_url"),
                },
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=claim_id,
                relation_type="has_metric",
                target_id=metric_id,
                weight=confidence,
            )
        )


def _append_player_context_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    player_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, dict):
        return
    club = _normal_text(metrics.get("club"))
    if club:
        club_id = f"club:{_slug(club)}"
        entities.append(WorldEntity(entity_id=club_id, entity_type="club", name=club, attributes={}))
        relationships.append(
            WorldRelationship(
                source_id=player_id,
                relation_type="affiliated_with",
                target_id=club_id,
                weight=confidence,
            )
        )
    position = _normal_text(metrics.get("position"))
    if position:
        position_id = f"position:{_slug(position)}"
        entities.append(WorldEntity(entity_id=position_id, entity_type="position", name=position, attributes={}))
        relationships.append(
            WorldRelationship(
                source_id=player_id,
                relation_type="plays_position",
                target_id=position_id,
                weight=confidence,
            )
        )


def _append_player_stat_line_node(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    claim_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    player = _normal_text(evidence.get("player"))
    if not player:
        return
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, dict):
        return
    performance_keys = {
        "goals",
        "assists",
        "appearances",
        "clean_sheets",
        "blocked_shots",
        "key_passes_per_game",
        "pass_completion_pct",
        "xg",
        "xa",
    }
    stat_keys = {*performance_keys, "minutes"}
    stat_metrics = {
        key: value
        for key, value in metrics.items()
        if key in stat_keys
        and value not in {None, ""}
    }
    if not stat_metrics or not any(key in stat_metrics for key in performance_keys):
        return
    team = _normal_text(evidence.get("team"))
    line_id = f"player_stat_line:{_stable_key(claim_id, player, str(sorted(stat_metrics.items())))}"
    entities.append(
        WorldEntity(
            entity_id=line_id,
            entity_type="player_stat_line",
            name=f"{player} stat line",
            attributes={
                "player": player,
                "team": team,
                "claim_id": claim_id,
                "source_url": evidence.get("source_url"),
                "metrics": stat_metrics,
            },
        )
    )
    relationships.extend(
        [
            WorldRelationship(
                source_id=claim_id,
                relation_type="mentions_player_stat_line",
                target_id=line_id,
                weight=confidence,
            ),
            WorldRelationship(
                source_id=line_id,
                relation_type="about_player",
                target_id=f"player:{_slug(player)}",
                weight=confidence,
            ),
        ]
    )
    if team:
        relationships.append(
            WorldRelationship(
                source_id=line_id,
                relation_type="about_team",
                target_id=f"team:{_slug(team)}",
                weight=confidence,
            )
        )


def _append_match_result_node(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
    claim_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, dict) or metrics.get("historical_result_signal") != "explicit_score":
        return
    team_a = _normal_text(metrics.get("historical_team_a"))
    team_b = _normal_text(metrics.get("historical_team_b"))
    score_a = metrics.get("historical_team_a_score")
    score_b = metrics.get("historical_team_b_score")
    if not team_a or not team_b or score_a in {None, ""} or score_b in {None, ""}:
        return
    label = _normal_text(metrics.get("historical_result_label")) or f"{team_a} {score_a}-{score_b} {team_b}"
    result_id = f"match_result:{_stable_key(match.round_id, team_a, team_b, str(score_a), str(score_b), str(evidence.get('source_url') or ''))}"
    entities.append(
        WorldEntity(
            entity_id=result_id,
            entity_type="match_result",
            name=label,
            attributes={
                "team_a": team_a,
                "team_b": team_b,
                "team_a_score": score_a,
                "team_b_score": score_b,
                "source_url": evidence.get("source_url"),
                "claim_id": claim_id,
            },
        )
    )
    relationships.extend(
        [
            WorldRelationship(
                source_id=claim_id,
                relation_type="mentions_result",
                target_id=result_id,
                weight=confidence,
            ),
            WorldRelationship(
                source_id=result_id,
                relation_type="historical_context_for",
                target_id=f"match:{match.round_id}",
                weight=confidence,
            ),
            WorldRelationship(
                source_id=result_id,
                relation_type="team_a",
                target_id=f"team:{_slug(team_a)}",
                weight=confidence,
            ),
            WorldRelationship(
                source_id=result_id,
                relation_type="team_b",
                target_id=f"team:{_slug(team_b)}",
                weight=confidence,
            ),
        ]
    )


def _append_availability_event_node(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
    claim_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    if _normal_text(evidence.get("claim_type")) != "injury_availability":
        return
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, dict):
        return
    status = _normal_text(metrics.get("availability_status"))
    if not status:
        return
    player = _normal_text(evidence.get("player"))
    team = _normal_text(evidence.get("team"))
    body_part = _normal_text(metrics.get("injury_body_part"))
    subject = player or team or _normal_text(evidence.get("subject"))
    event_id = f"availability_event:{_stable_key(match.round_id, subject, status, body_part, str(evidence.get('source_url') or ''), str(evidence.get('claim') or ''))}"
    entities.append(
        WorldEntity(
            entity_id=event_id,
            entity_type="availability_event",
            name=f"{subject or 'availability'} {status}".strip(),
            attributes={
                "status": status,
                "body_part": body_part,
                "team": team,
                "player": player,
                "claim_id": claim_id,
                "source_url": evidence.get("source_url"),
            },
        )
    )
    relationships.extend(
        [
            WorldRelationship(
                source_id=claim_id,
                relation_type="mentions_availability_event",
                target_id=event_id,
                weight=confidence,
            ),
            WorldRelationship(
                source_id=event_id,
                relation_type="availability_context_for",
                target_id=f"match:{match.round_id}",
                weight=confidence,
            ),
        ]
    )
    status_id = f"availability_status:{_slug(status)}"
    entities.append(WorldEntity(entity_id=status_id, entity_type="availability_status", name=status, attributes={}))
    relationships.append(
        WorldRelationship(
            source_id=event_id,
            relation_type="has_availability_status",
            target_id=status_id,
            weight=confidence,
        )
    )
    if body_part:
        body_part_id = f"body_part:{_slug(body_part)}"
        entities.append(WorldEntity(entity_id=body_part_id, entity_type="body_part", name=body_part, attributes={}))
        relationships.append(
            WorldRelationship(
                source_id=event_id,
                relation_type="has_body_part",
                target_id=body_part_id,
                weight=confidence,
            )
        )
    if player:
        relationships.append(
            WorldRelationship(
                source_id=event_id,
                relation_type="about_player",
                target_id=f"player:{_slug(player)}",
                weight=confidence,
            )
        )
    if team:
        relationships.append(
            WorldRelationship(
                source_id=event_id,
                relation_type="about_team",
                target_id=f"team:{_slug(team)}",
                weight=confidence,
            )
        )


def _append_formation_node(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
    claim_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    metrics = evidence.get("metrics") or {}
    if not isinstance(metrics, dict):
        return
    formation = _normal_text(metrics.get("formation"))
    if not formation:
        return
    team = _normal_text(evidence.get("team"))
    formation_id = f"formation:{_slug(formation)}"
    entities.append(
        WorldEntity(
            entity_id=formation_id,
            entity_type="formation",
            name=formation,
            attributes={"team": team} if team else {},
        )
    )
    relationships.extend(
        [
            WorldRelationship(
                source_id=claim_id,
                relation_type="mentions_formation",
                target_id=formation_id,
                weight=confidence,
            ),
            WorldRelationship(
                source_id=formation_id,
                relation_type="formation_context_for",
                target_id=f"match:{match.round_id}",
                weight=confidence,
            ),
        ]
    )
    if team:
        relationships.append(
            WorldRelationship(
                source_id=formation_id,
                relation_type="used_by_team",
                target_id=f"team:{_slug(team)}",
                weight=confidence,
            )
        )


def _metric_unit(metric_key: str) -> str:
    if metric_key.endswith("_year"):
        return "year"
    if metric_key.endswith("_pct"):
        return "percent"
    if metric_key in {
        "goals",
        "assists",
        "appearances",
        "minutes",
        "clean_sheets",
        "blocked_shots",
        "international_caps",
        "international_goals",
    }:
        return "count"
    if metric_key.endswith("_per_game"):
        return "per_game"
    if metric_key.endswith("_signal"):
        return "label"
    if metric_key.endswith("_score"):
        return "goals"
    if metric_key in {"availability_status", "injury_body_part"}:
        return "label"
    if metric_key == "formation":
        return "shape"
    return "label"


def _admissible_evidence(evidence: dict) -> bool:
    if not evidence.get("claim_type") or not evidence.get("claim"):
        return False
    if not evidence.get("source_url") and not evidence.get("source_title"):
        return False
    if str(evidence.get("source_quality") or "").lower() == "weak":
        return False
    if str(evidence.get("source_kind") or "").lower() == "search" and str(
        evidence.get("source_quality") or ""
    ).lower() != "strong":
        return False
    return True


def _evidence_match_team(evidence: dict, match: MatchContext) -> str:
    candidates = (
        _normal_text(evidence.get("team")),
        _normal_text(evidence.get("subject")),
    )
    teams_by_slug = {
        _slug(match.home_team): match.home_team,
        _slug(match.away_team): match.away_team,
    }
    for candidate in candidates:
        if not candidate:
            continue
        team = teams_by_slug.get(_slug(candidate))
        if team:
            return team
    return ""


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().split() if part)


def _stable_key(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _normal_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"none", "unknown", "null"} else text


def _float_or_default(value: object, baseline: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return baseline


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower().removeprefix("www.")


def _source_quality_score(source_quality: str) -> float:
    return {
        "strong": 0.85,
        "medium": 0.55,
        "weak": 0.2,
    }.get(source_quality.lower(), 0.4)


def _impact_attributes(impact: str) -> dict:
    side = ""
    effect = "context"
    if impact.endswith("_home"):
        side = "home"
    elif impact.endswith("_away"):
        side = "away"
    if impact.startswith("negative_"):
        effect = "negative"
    elif impact.startswith("positive_"):
        effect = "positive"
    elif impact.startswith("context_"):
        effect = "context"
    return {"side": side, "effect": effect}


def _claim_name(evidence: dict) -> str:
    subject = _normal_text(evidence.get("subject")) or _normal_text(evidence.get("team")) or "Evidence"
    claim_type = _normal_text(evidence.get("claim_type")) or "claim"
    return f"{subject} {claim_type}".replace("_", " ")


def _dedupe_entities(entities: list[WorldEntity]) -> list[WorldEntity]:
    seen: set[str] = set()
    unique: list[WorldEntity] = []
    for entity in entities:
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        unique.append(entity)
    return unique


def _dedupe_relationships(relationships: list[WorldRelationship]) -> list[WorldRelationship]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[WorldRelationship] = []
    for relationship in relationships:
        key = (relationship.source_id, relationship.relation_type, relationship.target_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(relationship)
    return unique
