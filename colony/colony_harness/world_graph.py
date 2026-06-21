"""Lightweight match-round subgraph for run memory."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

from .models import DebateClaim, Forecast, MatchContext, WorldEntity, WorldGraph, WorldRelationship
from .scouting_taxonomy import (
    SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES,
    SCOUTING_REQUIRED_CLAIM_TYPES,
    SCOUTING_RESCOUT_RECIPES,
    scouting_topic_quality,
)

KG_SCHEMA_VERSION = "scouting-kg-v1"


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
    _append_team_match_profile_nodes(entities, relationships, match=match)
    _append_player_match_profile_nodes(entities, relationships, match=match)
    _append_source_domain_profile_nodes(entities, relationships, match=match)
    _append_scout_match_profile_nodes(entities, relationships, match=match)

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
                        attributes={
                            "bankroll": forecast.bankroll,
                            "genome_id": forecast.genome_id,
                            "model": forecast.model,
                        },
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
            is_synthesis = claim.speaker_id == "colony_synthesis"
            speaker_entity_id = (
                f"synthesis:{claim.speaker_id}" if is_synthesis else f"predictor:{claim.speaker_id}"
            )
            speaker_entity_type = "synthesis" if is_synthesis else "predictor"
            entities.extend(
                [
                    WorldEntity(
                        entity_id=speaker_entity_id,
                        entity_type=speaker_entity_type,
                        name=claim.speaker_name or claim.speaker_id,
                        attributes={
                            "speaker_id": claim.speaker_id,
                            "model": claim.model,
                            "persona": claim.persona,
                            "access_tier": claim.access_tier,
                            "genome_id": claim.genome_id,
                        },
                    ),
                    WorldEntity(
                        entity_id=claim_id,
                        entity_type="debate_claim",
                        name=f"{claim.speaker_name} claim",
                        attributes=claim.to_dict(),
                    ),
                ]
            )
            relationships.extend(
                [
                    WorldRelationship(
                        source_id=speaker_entity_id,
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
        claim_id = _evidence_claim_id(finding_key, index, evidence)
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
                    attributes=_claim_type_attributes(claim_type),
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
        _append_claim_quality_nodes(
            entities,
            relationships,
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
                        attributes=_vocabulary_attributes("source_domain", domain),
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
                        attributes=_vocabulary_attributes("source_kind", source_kind),
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
                        attributes=_vocabulary_attributes("source_recency", source_recency),
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
                attributes=_vocabulary_attributes("venue", match.venue_name),
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
                attributes=_vocabulary_attributes("group", match.group_name),
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
                attributes=_vocabulary_attributes("stage", match.stage_name),
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=match_id,
                relation_type="part_of_stage",
                target_id=stage_id,
            )
        )


def _append_claim_quality_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    claim_id: str,
    evidence: dict,
    confidence: float,
) -> None:
    for tag in _claim_quality_tags(evidence, confidence=confidence):
        quality_id = f"claim_quality:{_slug(tag)}"
        entities.append(
            WorldEntity(
                entity_id=quality_id,
                entity_type="claim_quality",
                name=tag,
                attributes=_claim_quality_attributes(tag),
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=claim_id,
                relation_type="has_claim_quality",
                target_id=quality_id,
                weight=confidence,
            )
        )


def _claim_quality_tags(evidence: dict, *, confidence: float) -> list[str]:
    tags: list[str] = []
    claim_type = _normal_text(evidence.get("claim_type"))
    source_kind = _normal_text(evidence.get("source_kind")).lower()
    source_quality = _normal_text(evidence.get("source_quality")).lower()
    recency_bucket = _normal_text(evidence.get("source_recency_bucket")).lower()
    metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), dict) else {}

    if evidence.get("source_url"):
        tags.append("source_locked")
    if source_quality == "strong" or source_kind in {"official", "stats", "news", "reference"}:
        tags.append("strong_or_official_source")
    if recency_bucket in {"last_7_days", "last_30_days"}:
        tags.append("fresh_source")
    if _normal_text(evidence.get("source_published_date")):
        tags.append("dated_source")
    if metrics:
        tags.append("metric_backed")
    if _normal_text(evidence.get("team")):
        tags.append("team_specific")
    if _normal_text(evidence.get("player")):
        tags.append("player_specific")
    if metrics.get("verification_signal") in {"official", "reported"}:
        tags.append("social_verified_signal")
    if metrics.get("rumor_signal"):
        tags.append("rumor_signal")
    if any(key in metrics for key in ("telegram_views", "telegram_forwards", "telegram_reactions")):
        tags.append("engagement_backed")
    if claim_type == "market_snapshot" and source_kind == "market_snapshot":
        tags.append("market_snapshot")
    if claim_type == "market_snapshot" and any(
        key in metrics
        for key in (
            "visible_price_probability",
            "buy_yes_price_probability",
            "buy_no_price_probability",
        )
    ):
        tags.append("visible_market_price")
    if claim_type in {
        "injury_availability",
        "injury_return",
        "lineup",
        "player_form",
        "key_players",
        "player_ratings",
        "coach_form",
        "attacking_profile",
        "defensive_profile",
        "tactical",
        "social_signal",
    } and (
        "fresh_source" in tags or "metric_backed" in tags or "strong_or_official_source" in tags
    ):
        tags.append("match_actionable")
    if claim_type in {"injury_availability", "injury_return"} and metrics.get("availability_status"):
        tags.append("availability_status")
    if claim_type == "match_history" and metrics.get("historical_result_signal") == "explicit_score":
        tags.append("explicit_score")
    if claim_type == "match_history" and metrics.get("historical_record_signal"):
        tags.append("h2h_record")
    if claim_type == "recent_form" and any(
        key in metrics
        for key in (
            "recent_sample_matches",
            "recent_wins",
            "recent_draws",
            "recent_losses",
            "unbeaten_matches",
            "winning_streak_matches",
        )
    ):
        tags.append("recent_results_window")
    if claim_type in {"player_form", "key_players", "player_ratings", "attacking_profile"} and any(
        key in metrics
        for key in (
            "goals",
            "assists",
            "goal_contributions",
            "appearances",
            "minutes",
            "starts",
            "xg",
            "xa",
            "average_rating",
            "chances_created",
            "key_passes_per_game",
            "shots_per_game",
        )
    ):
        tags.append("season_output")
    if claim_type == "player_ratings" and metrics.get("rating_signal"):
        tags.append("rating_signal")
    if claim_type == "attacking_profile" and metrics.get("attacking_signal"):
        tags.append("attacking_signal")
    if claim_type == "defensive_profile" and metrics.get("defensive_signal"):
        tags.append("defensive_signal")
    if claim_type == "coach_form" and metrics.get("coach_signal"):
        tags.append("coach_signal")
    if claim_type == "social_signal" and metrics.get("social_signal"):
        tags.append("social_signal")
    if claim_type == "tactical" and metrics.get("formation"):
        tags.append("formation_signal")
    if claim_type in {"lineup", "tactical"} and metrics.get("lineup_signal"):
        tags.append("lineup_signal")
    if _normal_text(evidence.get("extraction_method")) == "deepseek_agent":
        tags.append("agent_extracted")
    if confidence >= 0.6:
        tags.append("higher_confidence")
    return list(dict.fromkeys(tags))


def _claim_quality_attributes(tag: str) -> dict:
    categories = {
        "source_locked": "provenance",
        "strong_or_official_source": "provenance",
        "fresh_source": "freshness",
        "dated_source": "freshness",
        "metric_backed": "specificity",
        "team_specific": "specificity",
        "player_specific": "specificity",
        "social_verified_signal": "provenance",
        "rumor_signal": "provenance",
        "engagement_backed": "provenance",
        "market_snapshot": "provenance",
        "visible_market_price": "specificity",
        "match_actionable": "actionability",
        "availability_status": "actionability",
        "explicit_score": "specificity",
        "h2h_record": "specificity",
        "recent_results_window": "specificity",
        "season_output": "specificity",
        "formation_signal": "specificity",
        "lineup_signal": "specificity",
        "agent_extracted": "producer",
        "higher_confidence": "confidence",
    }
    descriptions = {
        "source_locked": "Claim has a concrete source URL.",
        "strong_or_official_source": "Claim comes from a strong, official, stats, news, or reference source.",
        "fresh_source": "Claim source is within the freshness window tracked by the scout.",
        "dated_source": "Claim has a normalized publication date.",
        "metric_backed": "Claim carries parsed metrics that can become KG facts.",
        "team_specific": "Claim is attached to one of the match teams.",
        "player_specific": "Claim is attached to a named player.",
        "social_verified_signal": "Social claim carries an official or reported-source signal.",
        "rumor_signal": "Social claim is explicitly marked as unconfirmed or rumor-like.",
        "engagement_backed": "Social claim includes visible engagement metadata.",
        "market_snapshot": "Claim comes from a read-only market snapshot.",
        "visible_market_price": "Claim carries visible market price information.",
        "match_actionable": "Claim type and evidence quality make it useful for match scouting.",
        "availability_status": "Claim carries an explicit availability status.",
        "explicit_score": "Claim carries an explicit historical scoreline.",
        "h2h_record": "Claim carries a concrete head-to-head record.",
        "recent_results_window": "Claim carries a concrete recent-results window.",
        "season_output": "Claim carries concrete player season output.",
        "formation_signal": "Claim carries a concrete formation.",
        "lineup_signal": "Claim carries a lineup, predicted XI, starting XI, or squad-depth signal.",
        "agent_extracted": "Claim was extracted by a structured scouting agent.",
        "higher_confidence": "Claim confidence is at least 0.60.",
    }
    return {
        "category": categories.get(tag, "other"),
        "description": descriptions.get(tag, tag.replace("_", " ")),
    }


def _counter_attributes(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


def _season_stat_summary(performance_metrics: dict[str, set[str]]) -> dict[str, int | float]:
    summary: dict[str, int | float] = {}
    for metric_key in (
        "goals",
        "assists",
        "goal_contributions",
        "appearances",
        "minutes",
        "starts",
        "clean_sheets",
        "blocked_shots",
        "chances_created",
        "key_passes_per_game",
        "shots_per_game",
        "average_rating",
        "pass_completion_pct",
        "xg",
        "xa",
    ):
        values = _numeric_metric_values(performance_metrics.get(metric_key) or set())
        if values:
            summary[f"{metric_key}_max"] = _compact_number(max(values))
    goals = summary.get("goals_max")
    assists = summary.get("assists_max")
    explicit_contributions = summary.get("goal_contributions_max")
    if explicit_contributions is None and isinstance(goals, (int, float)) and isinstance(assists, (int, float)):
        summary["goal_contributions_max"] = _compact_number(float(goals) + float(assists))
    if summary:
        summary["metric_count"] = len(summary)
    return summary


def _team_recent_form_summary(recent_form_metrics: dict[str, set[str]]) -> dict[str, int | float]:
    summary: dict[str, int | float] = {}
    for metric_key in (
        "recent_sample_matches",
        "recent_wins",
        "recent_draws",
        "recent_losses",
        "unbeaten_matches",
        "winning_streak_matches",
        "recent_goals_for",
        "recent_goals_against",
    ):
        values = _numeric_metric_values(recent_form_metrics.get(metric_key) or set())
        if values:
            summary[f"{metric_key}_max"] = _compact_number(max(values))
    if summary:
        summary["metric_count"] = len(summary)
    return summary


def _team_match_history_summary(match_history_metrics: dict[str, set[str]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for metric_key in (
        "historical_team_a_score",
        "historical_team_b_score",
        "historical_team_a_wins",
        "historical_team_a_unbeaten",
        "historical_meetings",
        "h2h_recent_sample_matches",
        "h2h_team_a_wins",
        "h2h_draws",
        "h2h_team_a_losses",
        "h2h_team_a_goals_per_match",
    ):
        values = _numeric_metric_values(match_history_metrics.get(metric_key) or set())
        if values:
            summary[f"{metric_key}_max"] = _compact_number(max(values))
    for metric_key in (
        "historical_team_a",
        "historical_team_b",
        "historical_result_label",
        "historical_result_signal",
        "historical_record_signal",
    ):
        values = sorted(str(value) for value in match_history_metrics.get(metric_key) or set() if value)
        if values:
            summary[metric_key] = values[:6]
    if summary:
        summary["metric_count"] = len(summary)
    return summary


def _numeric_metric_values(values: set[str]) -> list[float]:
    numeric_values: list[float] = []
    for value in values:
        try:
            numeric_values.append(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            continue
    return numeric_values


def _compact_number(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 4)


def _append_scouting_topic_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    claim_counts: Counter[str] = Counter()
    source_urls_by_type: dict[str, set[str]] = defaultdict(set)
    players_by_type: dict[str, set[str]] = defaultdict(set)
    metric_counts: Counter[str] = Counter()
    recent_counts: Counter[str] = Counter()
    strong_or_official_counts: Counter[str] = Counter()
    scouts_by_type: dict[str, set[str]] = defaultdict(set)
    extraction_methods_by_type: dict[str, Counter[str]] = defaultdict(Counter)
    quality_counts_by_type: dict[str, Counter[str]] = defaultdict(Counter)
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
            player = _normal_text(evidence.get("player"))
            if player:
                players_by_type[claim_type].add(player)
            if evidence.get("metrics"):
                metric_counts[claim_type] += 1
            if _normal_text(evidence.get("source_recency_bucket")) in {"last_7_days", "last_30_days"}:
                recent_counts[claim_type] += 1
            if _normal_text(evidence.get("source_quality")).lower() == "strong" or _normal_text(
                evidence.get("source_kind")
            ).lower() in {"official", "stats", "news", "reference"}:
                strong_or_official_counts[claim_type] += 1
            scouts_by_type[claim_type].add(finding.scout_name)
            extraction_method = _normal_text(evidence.get("extraction_method"))
            if extraction_method:
                extraction_methods_by_type[claim_type][extraction_method] += 1
            confidence = _float_or_default(evidence.get("confidence"), finding.confidence)
            quality_counts_by_type[claim_type].update(_claim_quality_tags(evidence, confidence=confidence))

    all_topics = sorted(set(SCOUTING_REQUIRED_CLAIM_TYPES) | set(claim_counts))
    for claim_type in all_topics:
        claim_count = claim_counts[claim_type]
        quality_status, quality_reasons = scouting_topic_quality(
            claim_type,
            claim_count=claim_count,
            metric_claim_count=metric_counts[claim_type],
            player_count=len(players_by_type.get(claim_type, set())),
            recent_30d_claim_count=recent_counts[claim_type],
            strong_or_official_claim_count=strong_or_official_counts[claim_type],
            claim_quality_counts=_counter_attributes(quality_counts_by_type[claim_type]),
        )
        coverage_status = "covered" if quality_status == "usable" else quality_status
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
                        "quality_status": quality_status,
                        "quality_reasons": quality_reasons,
                        "claim_count": claim_count,
                        "unique_source_count": len(source_urls_by_type.get(claim_type, set())),
                        "metric_claim_count": metric_counts[claim_type],
                        "scout_count": len(scouts_by_type.get(claim_type, set())),
                        "scout_names": sorted(scouts_by_type.get(claim_type, set())),
                        "extraction_methods": _counter_attributes(extraction_methods_by_type[claim_type]),
                        "claim_quality_counts": _counter_attributes(quality_counts_by_type[claim_type]),
                    },
                ),
                WorldEntity(
                    entity_id=claim_type_id,
                    entity_type="claim_type",
                    name=claim_type,
                    attributes=_claim_type_attributes(claim_type),
                ),
            ]
        )
        for scout_name in sorted(scouts_by_type.get(claim_type, set())):
            relationships.append(
                WorldRelationship(
                    source_id=topic_id,
                    relation_type="covered_by_scout",
                    target_id=f"scout:{_slug(scout_name)}",
                    weight=1.0,
                )
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
    scouts_by_team_type: dict[tuple[str, str], set[str]] = defaultdict(set)
    extraction_methods_by_team_type: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    quality_counts_by_team_type: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
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
            ).lower() in {"official", "stats", "news", "reference"}:
                strong_or_official_counts[key] += 1
            scouts_by_team_type[key].add(finding.scout_name)
            extraction_method = _normal_text(evidence.get("extraction_method"))
            if extraction_method:
                extraction_methods_by_team_type[key][extraction_method] += 1
            confidence = _float_or_default(evidence.get("confidence"), finding.confidence)
            quality_counts_by_team_type[key].update(_claim_quality_tags(evidence, confidence=confidence))

    all_topics = sorted(set(SCOUTING_REQUIRED_CLAIM_TYPES) | observed_topics)
    for team in team_names:
        side = "home" if team == match.home_team else "away"
        team_id = f"team:{_slug(team)}"
        for claim_type in all_topics:
            key = (team, claim_type)
            claim_count = claim_counts[key]
            fresh_required = claim_type in SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES
            freshness_status = _topic_freshness_status(
                claim_count=claim_count,
                fresh_required=fresh_required,
                recent_claim_count=recent_counts[key],
            )
            source_strength_status = (
                "strong_or_official" if strong_or_official_counts[key] else ("missing" if not claim_count else "needs_stronger_source")
            )
            quality_status, quality_reasons = scouting_topic_quality(
                claim_type,
                claim_count=claim_count,
                metric_claim_count=metric_counts[key],
                player_count=len(players_by_team_type.get(key, set())),
                recent_30d_claim_count=recent_counts[key],
                strong_or_official_claim_count=strong_or_official_counts[key],
                claim_quality_counts=_counter_attributes(quality_counts_by_team_type[key]),
            )
            coverage_status = "covered" if quality_status == "usable" else quality_status
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
                            "quality_status": quality_status,
                            "quality_reasons": quality_reasons,
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
                            "scout_count": len(scouts_by_team_type.get(key, set())),
                            "scout_names": sorted(scouts_by_team_type.get(key, set())),
                            "extraction_methods": _counter_attributes(extraction_methods_by_team_type[key]),
                            "claim_quality_counts": _counter_attributes(quality_counts_by_team_type[key]),
                        },
                    ),
                    WorldEntity(
                        entity_id=claim_type_id,
                        entity_type="claim_type",
                        name=claim_type,
                        attributes=_claim_type_attributes(claim_type),
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
            for scout_name in sorted(scouts_by_team_type.get(key, set())):
                relationships.append(
                    WorldRelationship(
                        source_id=topic_id,
                        relation_type="covered_by_scout",
                        target_id=f"scout:{_slug(scout_name)}",
                        weight=1.0,
                    )
                )
            if claim_type in SCOUTING_REQUIRED_CLAIM_TYPES and quality_status != "usable":
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
                    status="needs_fresh_rescout" if freshness_status == "needs_fresh_source" else "needs_rescout",
                    gap_reason="missing_required_topic" if quality_status == "missing" else "needs_better_evidence",
                    quality_status=quality_status,
                    quality_reasons=quality_reasons,
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
                    quality_status=quality_status,
                    quality_reasons=quality_reasons,
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
    quality_status: str = "",
    quality_reasons: list[str] | None = None,
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
                "quality_status": quality_status,
                "quality_reasons": list(quality_reasons or []),
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


def _append_team_match_profile_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    profiles: dict[str, dict] = {}
    for team in (match.home_team, match.away_team):
        profiles[team] = {
            "claim_count": 0,
            "claim_types": Counter(),
            "metric_keys": Counter(),
            "claim_quality_counts": Counter(),
            "source_quality": Counter(),
            "source_kind": Counter(),
            "source_recency": Counter(),
            "source_urls": set(),
            "scout_names": set(),
            "players": set(),
            "availability_statuses": set(),
            "availability_status_counts": Counter(),
            "availability_by_player": defaultdict(set),
            "formations": set(),
            "clubs": set(),
            "positions": set(),
            "recent_form_metrics": defaultdict(set),
            "match_history_metrics": defaultdict(set),
            "claim_ids": set(),
            "highest_confidence": 0.0,
        }

    for finding in match.findings:
        for index, evidence in enumerate(finding.evidence_claims):
            if not _admissible_evidence(evidence):
                continue
            team = _evidence_match_team(evidence, match)
            if not team:
                continue
            profile = profiles[team]
            claim_id = _evidence_claim_id(finding.finding_id, index, evidence)
            claim_type = _normal_text(evidence.get("claim_type"))
            confidence = _float_or_default(evidence.get("confidence"), finding.confidence)
            profile["claim_count"] += 1
            profile["highest_confidence"] = max(profile["highest_confidence"], confidence)
            profile["scout_names"].add(finding.scout_name)
            profile["claim_ids"].add(claim_id)
            if claim_type:
                profile["claim_types"][claim_type] += 1
            player = _normal_text(evidence.get("player"))
            if player:
                profile["players"].add(player)
            source_url = _normal_text(evidence.get("source_url"))
            if source_url:
                profile["source_urls"].add(source_url)
            for source_field, counter_name in (
                ("source_quality", "source_quality"),
                ("source_kind", "source_kind"),
                ("source_recency_bucket", "source_recency"),
            ):
                value = _normal_text(evidence.get(source_field))
                if value:
                    profile[counter_name][value] += 1
            profile["claim_quality_counts"].update(_claim_quality_tags(evidence, confidence=confidence))
            metrics = evidence.get("metrics") or {}
            if not isinstance(metrics, dict):
                continue
            for metric_key, metric_value in metrics.items():
                if metric_value in {None, ""}:
                    continue
                metric_key = str(metric_key)
                profile["metric_keys"][metric_key] += 1
                if metric_key == "availability_status":
                    profile["availability_statuses"].add(str(metric_value))
                    profile["availability_status_counts"][str(metric_value)] += 1
                    if player:
                        profile["availability_by_player"][player].add(str(metric_value))
                elif metric_key == "formation":
                    profile["formations"].add(str(metric_value))
                elif metric_key == "club":
                    profile["clubs"].add(str(metric_value))
                elif metric_key == "position":
                    profile["positions"].add(str(metric_value))
                if claim_type == "recent_form" and metric_key in {
                    "recent_sample_matches",
                    "recent_wins",
                    "recent_draws",
                    "recent_losses",
                    "unbeaten_matches",
                    "winning_streak_matches",
                    "recent_goals_for",
                    "recent_goals_against",
                }:
                    profile["recent_form_metrics"][metric_key].add(str(metric_value))
                if claim_type == "match_history" and metric_key in {
                    "historical_team_a",
                    "historical_team_b",
                    "historical_team_a_score",
                    "historical_team_b_score",
                    "historical_team_a_wins",
                    "historical_team_a_unbeaten",
                    "historical_meetings",
                    "h2h_recent_sample_matches",
                    "h2h_team_a_wins",
                    "h2h_draws",
                    "h2h_team_a_losses",
                    "h2h_team_a_goals_per_match",
                    "historical_result_label",
                    "historical_result_signal",
                    "historical_record_signal",
                }:
                    profile["match_history_metrics"][metric_key].add(str(metric_value))

    for team, profile in profiles.items():
        side = "home" if team == match.home_team else "away"
        profile_id = f"team_match_profile:{_stable_key(match.round_id, team)}"
        team_id = f"team:{_slug(team)}"
        entities.append(
            WorldEntity(
                entity_id=profile_id,
                entity_type="team_match_profile",
                name=f"{team} match profile",
                attributes={
                    "team": team,
                    "side": side,
                    "match_id": f"match:{match.round_id}",
                    "claim_count": profile["claim_count"],
                    "claim_types": _counter_attributes(profile["claim_types"]),
                    "metric_keys": _counter_attributes(profile["metric_keys"]),
                    "claim_quality_counts": _counter_attributes(profile["claim_quality_counts"]),
                    "source_quality": _counter_attributes(profile["source_quality"]),
                    "source_kind": _counter_attributes(profile["source_kind"]),
                    "source_recency": _counter_attributes(profile["source_recency"]),
                    "unique_source_count": len(profile["source_urls"]),
                    "source_urls": sorted(profile["source_urls"])[:12],
                    "scout_names": sorted(profile["scout_names"]),
                    "players": sorted(profile["players"])[:40],
                    "player_count": len(profile["players"]),
                    "availability_statuses": sorted(profile["availability_statuses"]),
                    "availability_status_counts": _counter_attributes(profile["availability_status_counts"]),
                    "availability_conflict_players": sorted(
                        player
                        for player, statuses in profile["availability_by_player"].items()
                        if len(statuses) > 1
                    ),
                    "formations": sorted(profile["formations"]),
                    "clubs": sorted(profile["clubs"])[:40],
                    "positions": sorted(profile["positions"]),
                    "recent_form_summary": _team_recent_form_summary(profile["recent_form_metrics"]),
                    "match_history_summary": _team_match_history_summary(profile["match_history_metrics"]),
                    "evidence_claim_ids": sorted(profile["claim_ids"])[:80],
                    "highest_confidence": round(profile["highest_confidence"], 3),
                },
            )
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=f"match:{match.round_id}",
                    relation_type="has_team_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
                WorldRelationship(
                    source_id=team_id,
                    relation_type="has_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
            ]
        )
        for scout_name in sorted(profile["scout_names"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="covered_by_scout",
                    target_id=f"scout:{_slug(scout_name)}",
                    weight=1.0,
                )
            )
        for claim_type in sorted(profile["claim_types"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="supports_team_scouting_topic",
                    target_id=f"team_scouting_topic:{_stable_key(match.round_id, team, claim_type)}",
                    weight=1.0,
                )
            )
        for player in sorted(profile["players"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="summarizes_player_match_profile",
                    target_id=f"player_match_profile:{_stable_key(match.round_id, team, player)}",
                    weight=1.0,
                )
            )
        for claim_id in sorted(profile["claim_ids"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="summarizes_evidence_claim",
                    target_id=claim_id,
                    weight=1.0,
                )
            )


def _append_source_domain_profile_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    profiles: dict[str, dict] = {}
    for finding in match.findings:
        for index, evidence in enumerate(finding.evidence_claims):
            if not _admissible_evidence(evidence):
                continue
            source_url = _normal_text(evidence.get("source_url"))
            source_title = _normal_text(evidence.get("source_title"))
            domain = _domain(source_url)
            if not domain:
                continue
            profile = profiles.setdefault(
                domain,
                {
                    "claim_count": 0,
                    "claim_types": Counter(),
                    "teams": set(),
                    "team_claim_types": set(),
                    "players": set(),
                    "source_urls": set(),
                    "source_titles": set(),
                    "source_quality": Counter(),
                    "source_kind": Counter(),
                    "source_recency": Counter(),
                    "scout_names": set(),
                    "claim_quality_counts": Counter(),
                    "claim_ids": set(),
                    "highest_confidence": 0.0,
                },
            )
            claim_id = _evidence_claim_id(finding.finding_id, index, evidence)
            claim_type = _normal_text(evidence.get("claim_type"))
            confidence = _float_or_default(evidence.get("confidence"), finding.confidence)
            profile["claim_count"] += 1
            profile["highest_confidence"] = max(profile["highest_confidence"], confidence)
            profile["claim_ids"].add(claim_id)
            if claim_type:
                profile["claim_types"][claim_type] += 1
            team = _evidence_match_team(evidence, match) or _normal_text(evidence.get("team"))
            if team:
                profile["teams"].add(team)
                if claim_type:
                    profile["team_claim_types"].add((team, claim_type))
            player = _normal_text(evidence.get("player"))
            if player:
                profile["players"].add(player)
            profile["source_urls"].add(source_url)
            if source_title:
                profile["source_titles"].add(source_title)
            profile["scout_names"].add(finding.scout_name)
            for source_field, counter_name in (
                ("source_quality", "source_quality"),
                ("source_kind", "source_kind"),
                ("source_recency_bucket", "source_recency"),
            ):
                value = _normal_text(evidence.get(source_field))
                if value:
                    profile[counter_name][value] += 1
            profile["claim_quality_counts"].update(_claim_quality_tags(evidence, confidence=confidence))

    for domain, profile in profiles.items():
        profile_id = f"source_domain_profile:{_stable_key(match.round_id, domain)}"
        domain_id = f"source_domain:{_slug(domain)}"
        entities.append(
            WorldEntity(
                entity_id=profile_id,
                entity_type="source_domain_profile",
                name=f"{domain} source profile",
                attributes={
                    "domain": domain,
                    "match_id": f"match:{match.round_id}",
                    "claim_count": profile["claim_count"],
                    "claim_types": _counter_attributes(profile["claim_types"]),
                    "teams": sorted(profile["teams"]),
                    "players": sorted(profile["players"])[:40],
                    "player_count": len(profile["players"]),
                    "unique_source_count": len(profile["source_urls"]),
                    "source_urls": sorted(profile["source_urls"])[:12],
                    "source_titles": sorted(profile["source_titles"])[:12],
                    "source_quality": _counter_attributes(profile["source_quality"]),
                    "source_kind": _counter_attributes(profile["source_kind"]),
                    "source_recency": _counter_attributes(profile["source_recency"]),
                    "scout_names": sorted(profile["scout_names"]),
                    "claim_quality_counts": _counter_attributes(profile["claim_quality_counts"]),
                    "evidence_claim_ids": sorted(profile["claim_ids"])[:80],
                    "highest_confidence": round(profile["highest_confidence"], 3),
                },
            )
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=f"match:{match.round_id}",
                    relation_type="has_source_domain_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="profiles_domain",
                    target_id=domain_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
            ]
        )
        for scout_name in sorted(profile["scout_names"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="covered_by_scout",
                    target_id=f"scout:{_slug(scout_name)}",
                    weight=1.0,
                )
            )
        for claim_type in sorted(profile["claim_types"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="supports_scouting_topic",
                    target_id=f"scouting_topic:{_stable_key(match.round_id, claim_type)}",
                    weight=1.0,
                )
            )
            for team, team_claim_type in sorted(profile["team_claim_types"]):
                if team_claim_type != claim_type:
                    continue
                relationships.append(
                    WorldRelationship(
                        source_id=profile_id,
                        relation_type="supports_team_scouting_topic",
                        target_id=f"team_scouting_topic:{_stable_key(match.round_id, team, claim_type)}",
                        weight=1.0,
                    )
                )
        for claim_id in sorted(profile["claim_ids"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="summarizes_evidence_claim",
                    target_id=claim_id,
                    weight=1.0,
                )
            )


def _append_scout_match_profile_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    profiles: dict[str, dict] = {}
    for finding in match.findings:
        scout_name = _normal_text(finding.scout_name)
        if not scout_name:
            continue
        profile = profiles.setdefault(
            scout_name,
            {
                "finding_ids": set(),
                "finding_names": set(),
                "access_levels": Counter(),
                "source_types": Counter(),
                "claim_count": 0,
                "claim_types": Counter(),
                "teams": set(),
                "players": set(),
                "source_urls": set(),
                "source_domains": Counter(),
                "source_quality": Counter(),
                "source_kind": Counter(),
                "source_recency": Counter(),
                "extraction_methods": Counter(),
                "claim_quality_counts": Counter(),
                "metric_keys": Counter(),
                "claim_ids": set(),
                "highest_confidence": 0.0,
            },
        )
        profile["finding_ids"].add(f"finding:{finding.finding_id}")
        profile["finding_names"].add(finding.finding_name)
        profile["access_levels"][finding.access_level] += 1
        profile["source_types"][finding.source_type] += 1
        profile["highest_confidence"] = max(profile["highest_confidence"], finding.confidence)
        for index, evidence in enumerate(finding.evidence_claims):
            if not _admissible_evidence(evidence):
                continue
            claim_id = _evidence_claim_id(finding.finding_id, index, evidence)
            claim_type = _normal_text(evidence.get("claim_type"))
            confidence = _float_or_default(evidence.get("confidence"), finding.confidence)
            profile["claim_count"] += 1
            profile["highest_confidence"] = max(profile["highest_confidence"], confidence)
            profile["claim_ids"].add(claim_id)
            if claim_type:
                profile["claim_types"][claim_type] += 1
            team = _evidence_match_team(evidence, match) or _normal_text(evidence.get("team"))
            if team:
                profile["teams"].add(team)
            player = _normal_text(evidence.get("player"))
            if player:
                profile["players"].add(player)
            source_url = _normal_text(evidence.get("source_url"))
            if source_url:
                profile["source_urls"].add(source_url)
                domain = _domain(source_url)
                if domain:
                    profile["source_domains"][domain] += 1
            for source_field, counter_name in (
                ("source_quality", "source_quality"),
                ("source_kind", "source_kind"),
                ("source_recency_bucket", "source_recency"),
                ("extraction_method", "extraction_methods"),
            ):
                value = _normal_text(evidence.get(source_field))
                if value:
                    profile[counter_name][value] += 1
            metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), dict) else {}
            for metric_key in metrics:
                profile["metric_keys"][str(metric_key)] += 1
            profile["claim_quality_counts"].update(_claim_quality_tags(evidence, confidence=confidence))

    for scout_name, profile in profiles.items():
        if not profile["claim_count"]:
            continue
        profile_id = f"scout_match_profile:{_stable_key(match.round_id, scout_name)}"
        scout_id = f"scout:{_slug(scout_name)}"
        entities.append(
            WorldEntity(
                entity_id=profile_id,
                entity_type="scout_match_profile",
                name=f"{scout_name} match profile",
                attributes={
                    "scout_name": scout_name,
                    "match_id": f"match:{match.round_id}",
                    "finding_ids": sorted(profile["finding_ids"]),
                    "finding_names": sorted(profile["finding_names"]),
                    "access_levels": _counter_attributes(profile["access_levels"]),
                    "source_types": _counter_attributes(profile["source_types"]),
                    "claim_count": profile["claim_count"],
                    "claim_types": _counter_attributes(profile["claim_types"]),
                    "teams": sorted(profile["teams"]),
                    "players": sorted(profile["players"])[:40],
                    "player_count": len(profile["players"]),
                    "unique_source_count": len(profile["source_urls"]),
                    "source_urls": sorted(profile["source_urls"])[:12],
                    "source_domains": _counter_attributes(profile["source_domains"]),
                    "source_quality": _counter_attributes(profile["source_quality"]),
                    "source_kind": _counter_attributes(profile["source_kind"]),
                    "source_recency": _counter_attributes(profile["source_recency"]),
                    "extraction_methods": _counter_attributes(profile["extraction_methods"]),
                    "metric_keys": _counter_attributes(profile["metric_keys"]),
                    "claim_quality_counts": _counter_attributes(profile["claim_quality_counts"]),
                    "evidence_claim_ids": sorted(profile["claim_ids"])[:120],
                    "highest_confidence": round(profile["highest_confidence"], 3),
                },
            )
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=f"match:{match.round_id}",
                    relation_type="has_scout_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
                WorldRelationship(
                    source_id=scout_id,
                    relation_type="has_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="profiles_scout",
                    target_id=scout_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
            ]
        )
        for finding_id in sorted(profile["finding_ids"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="summarizes_finding",
                    target_id=finding_id,
                    weight=1.0,
                )
            )
        for claim_type in sorted(profile["claim_types"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="supports_scouting_topic",
                    target_id=f"scouting_topic:{_stable_key(match.round_id, claim_type)}",
                    weight=1.0,
                )
            )
        for claim_id in sorted(profile["claim_ids"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="summarizes_evidence_claim",
                    target_id=claim_id,
                    weight=1.0,
                )
            )


def _append_player_match_profile_nodes(
    entities: list[WorldEntity],
    relationships: list[WorldRelationship],
    *,
    match: MatchContext,
) -> None:
    profiles: dict[tuple[str, str], dict] = {}
    for finding in match.findings:
        for index, evidence in enumerate(finding.evidence_claims):
            if not _admissible_evidence(evidence):
                continue
            player = _normal_text(evidence.get("player"))
            if not player:
                continue
            team = _evidence_match_team(evidence, match) or _normal_text(evidence.get("team"))
            if not team:
                continue
            key = (team, player)
            profile = profiles.setdefault(
                key,
                {
                    "claim_count": 0,
                    "claim_types": Counter(),
                    "metric_keys": Counter(),
                    "claim_quality_counts": Counter(),
                    "source_quality": Counter(),
                    "source_kind": Counter(),
                    "source_recency": Counter(),
                    "source_urls": set(),
                    "scout_names": set(),
                    "clubs": set(),
                    "positions": set(),
                    "availability_statuses": set(),
                    "availability_status_counts": Counter(),
                    "injury_body_parts": set(),
                    "season_labels": set(),
                    "performance_metrics": defaultdict(set),
                    "claim_ids": set(),
                    "highest_confidence": 0.0,
                },
            )
            claim_id = _evidence_claim_id(finding.finding_id, index, evidence)
            claim_type = _normal_text(evidence.get("claim_type"))
            confidence = _float_or_default(evidence.get("confidence"), finding.confidence)
            profile["claim_count"] += 1
            profile["highest_confidence"] = max(profile["highest_confidence"], confidence)
            profile["claim_ids"].add(claim_id)
            if claim_type:
                profile["claim_types"][claim_type] += 1
            profile["scout_names"].add(finding.scout_name)
            source_url = _normal_text(evidence.get("source_url"))
            if source_url:
                profile["source_urls"].add(source_url)
            for source_field, counter_name in (
                ("source_quality", "source_quality"),
                ("source_kind", "source_kind"),
                ("source_recency_bucket", "source_recency"),
            ):
                value = _normal_text(evidence.get(source_field))
                if value:
                    profile[counter_name][value] += 1
            profile["claim_quality_counts"].update(_claim_quality_tags(evidence, confidence=confidence))
            metrics = evidence.get("metrics") or {}
            if not isinstance(metrics, dict):
                continue
            for metric_key, metric_value in metrics.items():
                if metric_value in {None, ""}:
                    continue
                metric_key = str(metric_key)
                profile["metric_keys"][metric_key] += 1
                if metric_key == "club":
                    profile["clubs"].add(str(metric_value))
                elif metric_key == "position":
                    profile["positions"].add(str(metric_value))
                elif metric_key == "availability_status":
                    profile["availability_statuses"].add(str(metric_value))
                    profile["availability_status_counts"][str(metric_value)] += 1
                elif metric_key == "injury_body_part":
                    profile["injury_body_parts"].add(str(metric_value))
                elif metric_key == "season_label":
                    profile["season_labels"].add(str(metric_value))
                elif metric_key in {
                    "goals",
                    "assists",
                    "goal_contributions",
                    "appearances",
                    "minutes",
                    "starts",
                    "clean_sheets",
                    "blocked_shots",
                    "chances_created",
                    "key_passes_per_game",
                    "shots_per_game",
                    "average_rating",
                    "pass_completion_pct",
                    "xg",
                    "xa",
                }:
                    profile["performance_metrics"][metric_key].add(str(metric_value))

    for (team, player), profile in profiles.items():
        side = "home" if team == match.home_team else ("away" if team == match.away_team else "")
        profile_id = f"player_match_profile:{_stable_key(match.round_id, team, player)}"
        player_id = f"player:{_slug(player)}"
        team_id = f"team:{_slug(team)}"
        entities.extend(
            [
                WorldEntity(
                    entity_id=player_id,
                    entity_type="player",
                    name=player,
                    attributes={"team": team},
                ),
                WorldEntity(
                    entity_id=profile_id,
                    entity_type="player_match_profile",
                    name=f"{player} match profile",
                    attributes={
                        "player": player,
                        "team": team,
                        "side": side,
                        "match_id": f"match:{match.round_id}",
                        "claim_count": profile["claim_count"],
                        "claim_types": _counter_attributes(profile["claim_types"]),
                        "metric_keys": _counter_attributes(profile["metric_keys"]),
                        "claim_quality_counts": _counter_attributes(profile["claim_quality_counts"]),
                        "source_quality": _counter_attributes(profile["source_quality"]),
                        "source_kind": _counter_attributes(profile["source_kind"]),
                        "source_recency": _counter_attributes(profile["source_recency"]),
                        "unique_source_count": len(profile["source_urls"]),
                        "source_urls": sorted(profile["source_urls"])[:8],
                        "scout_names": sorted(profile["scout_names"]),
                        "clubs": sorted(profile["clubs"]),
                        "positions": sorted(profile["positions"]),
                        "season_labels": sorted(profile["season_labels"]),
                        "availability_statuses": sorted(profile["availability_statuses"]),
                        "availability_status_counts": _counter_attributes(profile["availability_status_counts"]),
                        "availability_conflict": len(profile["availability_statuses"]) > 1,
                        "injury_body_parts": sorted(profile["injury_body_parts"]),
                        "performance_metrics": {
                            key: sorted(values)
                            for key, values in sorted(profile["performance_metrics"].items())
                        },
                        "season_stat_summary": _season_stat_summary(profile["performance_metrics"]),
                        "evidence_claim_ids": sorted(profile["claim_ids"])[:80],
                        "highest_confidence": round(profile["highest_confidence"], 3),
                    },
                ),
            ]
        )
        relationships.extend(
            [
                WorldRelationship(
                    source_id=f"match:{match.round_id}",
                    relation_type="has_player_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
                WorldRelationship(
                    source_id=team_id,
                    relation_type="has_player_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
                WorldRelationship(
                    source_id=player_id,
                    relation_type="has_match_profile",
                    target_id=profile_id,
                    weight=profile["highest_confidence"] or 1.0,
                ),
            ]
        )
        for scout_name in sorted(profile["scout_names"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="covered_by_scout",
                    target_id=f"scout:{_slug(scout_name)}",
                    weight=1.0,
                )
            )
        for claim_id in sorted(profile["claim_ids"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="summarizes_evidence_claim",
                    target_id=claim_id,
                    weight=1.0,
                )
            )
        for claim_type in sorted(profile["claim_types"]):
            relationships.append(
                WorldRelationship(
                    source_id=profile_id,
                    relation_type="supports_team_scouting_topic",
                    target_id=f"team_scouting_topic:{_stable_key(match.round_id, team, claim_type)}",
                    weight=1.0,
                )
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
        entities.append(
            WorldEntity(
                entity_id=club_id,
                entity_type="club",
                name=club,
                attributes=_vocabulary_attributes("club", club),
            )
        )
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
        entities.append(
            WorldEntity(
                entity_id=position_id,
                entity_type="position",
                name=position,
                attributes=_vocabulary_attributes("position", position),
            )
        )
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
        "goal_contributions",
        "appearances",
        "starts",
        "clean_sheets",
        "blocked_shots",
        "chances_created",
        "key_passes_per_game",
        "shots_per_game",
        "average_rating",
        "pass_completion_pct",
        "xg",
        "xa",
    }
    stat_keys = {*performance_keys, "minutes", "season_label"}
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
    entities.append(
        WorldEntity(
            entity_id=status_id,
            entity_type="availability_status",
            name=status,
            attributes=_vocabulary_attributes("availability_status", status),
        )
    )
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
        entities.append(
            WorldEntity(
                entity_id=body_part_id,
                entity_type="body_part",
                name=body_part,
                attributes=_vocabulary_attributes("body_part", body_part),
            )
        )
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
    if metric_key.endswith("_probability"):
        return "probability"
    if metric_key in {
        "goals",
        "assists",
        "goal_contributions",
        "appearances",
        "minutes",
        "starts",
        "clean_sheets",
        "blocked_shots",
        "chances_created",
        "international_caps",
        "international_goals",
        "recent_sample_matches",
        "recent_wins",
        "recent_draws",
        "recent_losses",
        "unbeaten_matches",
        "winning_streak_matches",
        "recent_goals_for",
        "recent_goals_against",
        "historical_team_a_wins",
        "historical_team_a_unbeaten",
        "historical_meetings",
        "h2h_recent_sample_matches",
        "h2h_team_a_wins",
        "h2h_draws",
        "h2h_team_a_losses",
        "telegram_views",
        "telegram_forwards",
        "telegram_replies",
        "telegram_reactions",
        "visible_button_count",
    }:
        return "count"
    if metric_key.endswith("_per_game"):
        return "per_game"
    if metric_key.endswith("_per_match"):
        return "per_match"
    if metric_key == "average_rating":
        return "rating"
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
    return not _evidence_rejection_reasons(evidence)


def _evidence_rejection_reasons(evidence: dict) -> list[str]:
    reasons: list[str] = []
    if not evidence.get("claim_type"):
        reasons.append("missing_claim_type")
    if not evidence.get("claim"):
        reasons.append("missing_claim")
    if not evidence.get("source_url") and not evidence.get("source_title"):
        reasons.append("missing_source")
    source_quality = str(evidence.get("source_quality") or "").lower()
    source_kind = str(evidence.get("source_kind") or "").lower()
    if source_quality == "weak":
        reasons.append("weak_source")
    if source_kind == "search" and source_quality != "strong":
        reasons.append("weak_search_aggregate")
    impact = str(evidence.get("impact") or "").strip().lower()
    if not impact:
        reasons.append("missing_impact")
    elif impact == "unknown":
        reasons.append("unknown_impact")
    return reasons


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


def _vocabulary_attributes(entity_type: str, value: str) -> dict:
    roles = {
        "availability_status": "availability taxonomy",
        "body_part": "injury taxonomy",
        "claim_type": "scouting taxonomy",
        "club": "player affiliation taxonomy",
        "group": "tournament structure",
        "position": "player role taxonomy",
        "source_domain": "provenance taxonomy",
        "source_kind": "source taxonomy",
        "source_recency": "freshness taxonomy",
        "stage": "tournament structure",
        "venue": "match context",
    }
    return {
        "node_role": roles.get(entity_type, "taxonomy"),
        "value": value,
        "is_domain_fact": entity_type in {"availability_status", "body_part", "club", "group", "position", "stage", "venue"},
        "is_index_node": entity_type in {"claim_type", "source_domain", "source_kind", "source_recency"},
    }


def _claim_type_attributes(claim_type: str) -> dict:
    recipe = SCOUTING_RESCOUT_RECIPES.get(claim_type, {})
    return {
        **_vocabulary_attributes("claim_type", claim_type),
        "claim_type": claim_type,
        "required": claim_type in SCOUTING_REQUIRED_CLAIM_TYPES,
        "freshness_required": claim_type in SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES,
        "recommended_scout": str(recipe.get("recommended_scout") or f"{claim_type}_scout"),
        "query_focus": str(recipe.get("query_focus") or claim_type.replace("_", " ")),
        "acceptance_criteria": list(recipe.get("acceptance_criteria") or []),
    }


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


def _evidence_claim_id(finding_key: str, index: int, evidence: dict) -> str:
    return f"evidence_claim:{_stable_key(finding_key, str(index), str(evidence.get('claim') or ''))}"


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
