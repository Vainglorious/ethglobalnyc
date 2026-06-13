"""Lightweight match-round subgraph for run memory."""

from __future__ import annotations

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
        entities.append(
            WorldEntity(
                entity_id=f"finding:{finding.finding_id}",
                entity_type="finding",
                name=finding.finding_name,
                attributes=finding.to_dict(),
            )
        )
        relationships.append(
            WorldRelationship(
                source_id=f"finding:{finding.finding_id}",
                relation_type="concerns",
                target_id=f"match:{match.round_id}",
                weight=finding.confidence,
            )
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
            claim_id = f"debate_claim:{match.round_id}:{claim.speaker_id}"
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
        relationships=relationships,
    )


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().split() if part)


def _dedupe_entities(entities: list[WorldEntity]) -> list[WorldEntity]:
    seen: set[str] = set()
    unique: list[WorldEntity] = []
    for entity in entities:
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        unique.append(entity)
    return unique
