"""Lightweight match-round subgraph for run memory."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse

from .models import DebateClaim, Forecast, MatchContext, WorldEntity, WorldGraph, WorldRelationship


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

    for finding in match.findings:
        finding_id = f"finding:{finding.finding_id}"
        entities.append(
            WorldEntity(
                entity_id=finding_id,
                entity_type="finding",
                name=finding.finding_name,
                attributes=finding.to_dict(),
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=finding_id,
                relation_type="concerns",
                target_id=f"match:{match.round_id}",
                weight=finding.confidence,
            )
        )
        _append_evidence_claims(
            entities,
            relationships,
            match=match,
            finding_id=finding_id,
            finding_key=finding.finding_id,
            evidence_claims=finding.evidence_claims,
        )

    if forecasts is not None:
        for forecast in forecasts:
            predictor_id = f"predictor:{forecast.agent_id}"
            prediction_id = f"prediction:{match.round_id}:{forecast.agent_id}"
            entities.extend(
                [
                    WorldEntity(
                        entity_id=predictor_id,
                        entity_type="predictor",
                        name=forecast.agent_id,
                        attributes={"bankroll": forecast.bankroll},
                    ),
                    WorldEntity(
                        entity_id=prediction_id,
                        entity_type="prediction",
                        name=f"{forecast.agent_id} prediction",
                        attributes=forecast.to_dict(),
                    ),
                ]
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

    if claims is not None:
        for claim in claims:
            phase = claim.debate_phase or "final"
            room = claim.room_id or "global"
            claim_id = f"debate_claim:{match.round_id}:{phase}:{room}:{claim.speaker_id}"
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
        claim_id = f"evidence_claim:{_stable_key(finding_key, str(index), evidence.get('claim', ''))}"
        source_url = str(evidence.get("source_url") or "")
        source_title = str(evidence.get("source_title") or "Source")
        source_id = f"source:{_stable_key(source_url or source_title)}"
        team = _normal_text(evidence.get("team"))
        player = _normal_text(evidence.get("player"))
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

        if source_url or source_title:
            entities.append(
                WorldEntity(
                    entity_id=source_id,
                    entity_type="source",
                    name=source_title,
                    attributes={
                        "title": source_title,
                        "url": source_url,
                        "domain": _domain(source_url),
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


def _float_or_default(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _domain(url: str) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower()


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
