"""Build the World Cup tournament knowledge graph from schedule data."""

from __future__ import annotations

import json
import re
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import WorldEntity, WorldGraph, WorldRelationship

OPENFOOTBALL_2026_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

OFFLINE_SAMPLE = {
    "name": "World Cup 2026",
    "matches": [
        {
            "round": "Matchday 3",
            "date": "2026-06-13",
            "time": "12:00 UTC-7",
            "team1": "Qatar",
            "team2": "Switzerland",
            "group": "Group B",
            "ground": "San Francisco Bay Area (Santa Clara)",
        },
        {
            "round": "Matchday 3",
            "date": "2026-06-13",
            "time": "18:00 UTC-4",
            "team1": "Brazil",
            "team2": "Morocco",
            "group": "Group C",
            "ground": "New York/New Jersey (East Rutherford)",
        },
        {
            "round": "Matchday 3",
            "date": "2026-06-13",
            "time": "21:00 UTC-4",
            "team1": "Haiti",
            "team2": "Scotland",
            "group": "Group C",
            "ground": "Boston (Foxborough)",
        },
        {
            "round": "Matchday 6",
            "date": "2026-06-16",
            "time": "15:00 UTC-4",
            "team1": "France",
            "team2": "Senegal",
            "group": "Group I",
            "ground": "New York/New Jersey (East Rutherford)",
        },
    ],
}


def load_openfootball_schedule(
    *,
    source_url: str = OPENFOOTBALL_2026_URL,
    cache_path: str | Path | None = None,
    force_refresh: bool = False,
    offline_sample: bool = False,
    timeout_seconds: int = 20,
) -> dict[str, Any]:
    if offline_sample:
        return OFFLINE_SAMPLE

    cache = Path(cache_path) if cache_path is not None else None
    if cache is not None and cache.exists() and not force_refresh:
        return json.loads(cache.read_text(encoding="utf-8"))

    request = urllib.request.Request(source_url, headers={"User-Agent": "ColonyHarness/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))

    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def build_tournament_graph(schedule: dict[str, Any], *, graph_id: str = "tournament:world_cup_2026") -> WorldGraph:
    tournament_name = str(schedule.get("name") or "World Cup 2026")
    matches = list(schedule.get("matches") or [])
    tournament_id = _entity_id("tournament", tournament_name)

    entities: list[WorldEntity] = [
        WorldEntity(
            entity_id=tournament_id,
            entity_type="tournament",
            name=tournament_name,
            attributes={"source": "openfootball/worldcup.json", "matches": len(matches)},
        )
    ]
    relationships: list[WorldRelationship] = []
    team_groups: dict[str, set[str]] = defaultdict(set)

    for index, match in enumerate(matches, start=1):
        group_name = match.get("group")
        stage_name = str(match.get("round") or "Unknown round")
        ground_name = str(match.get("ground") or "Unknown venue")
        team1 = str(match.get("team1") or "TBD")
        team2 = str(match.get("team2") or "TBD")
        match_id = _match_id(match, index)
        stage_id = _entity_id("stage", stage_name)
        venue_id = _entity_id("venue", ground_name)

        entities.extend(
            [
                WorldEntity(
                    entity_id=stage_id,
                    entity_type="stage",
                    name=stage_name,
                    attributes={"round": stage_name},
                ),
                WorldEntity(
                    entity_id=venue_id,
                    entity_type="venue",
                    name=ground_name,
                    attributes={"ground": ground_name},
                ),
                WorldEntity(
                    entity_id=match_id,
                    entity_type="match",
                    name=f"{team1} vs {team2}",
                    attributes={
                        "round": stage_name,
                        "date": match.get("date"),
                        "time": match.get("time"),
                        "group": group_name,
                        "ground": ground_name,
                        "team1": team1,
                        "team2": team2,
                        "score": match.get("score"),
                        "num": match.get("num"),
                    },
                ),
            ]
        )
        relationships.extend(
            [
                WorldRelationship(source_id=match_id, relation_type="part_of", target_id=tournament_id),
                WorldRelationship(source_id=match_id, relation_type="in_stage", target_id=stage_id),
                WorldRelationship(source_id=match_id, relation_type="played_at", target_id=venue_id),
            ]
        )

        if group_name:
            group_id = _entity_id("group", str(group_name))
            entities.append(
                WorldEntity(
                    entity_id=group_id,
                    entity_type="group",
                    name=str(group_name),
                    attributes={"group": group_name},
                )
            )
            relationships.extend(
                [
                    WorldRelationship(source_id=group_id, relation_type="part_of", target_id=tournament_id),
                    WorldRelationship(source_id=match_id, relation_type="in_group", target_id=group_id),
                ]
            )

        for side, team in (("home", team1), ("away", team2)):
            if _is_placeholder_team(team):
                continue
            team_id = _entity_id("team", team)
            entities.append(WorldEntity(entity_id=team_id, entity_type="team", name=team, attributes={}))
            relationships.append(
                WorldRelationship(
                    source_id=team_id,
                    relation_type=f"plays_{side}_in",
                    target_id=match_id,
                    attributes={"side": side},
                )
            )
            if group_name:
                team_groups[team_id].add(str(group_name))

    for team_id, groups in team_groups.items():
        for group_name in sorted(groups):
            relationships.append(
                WorldRelationship(
                    source_id=team_id,
                    relation_type="member_of",
                    target_id=_entity_id("group", group_name),
                )
            )

    return WorldGraph(
        graph_id=graph_id,
        round_id="world_cup_2026",
        entities=_dedupe_entities(entities),
        relationships=_dedupe_relationships(relationships),
    )


def graph_summary(graph: WorldGraph) -> dict[str, Any]:
    entity_counts: dict[str, int] = defaultdict(int)
    relationship_counts: dict[str, int] = defaultdict(int)
    for entity in graph.entities:
        entity_counts[entity.entity_type] += 1
    for relationship in graph.relationships:
        relationship_counts[relationship.relation_type] += 1
    return {
        "graph_id": graph.graph_id,
        "entities": len(graph.entities),
        "relationships": len(graph.relationships),
        "entity_types": dict(sorted(entity_counts.items())),
        "relationship_types": dict(sorted(relationship_counts.items())),
    }


def matches_for_teams(graph: WorldGraph, teams: set[str]) -> list[WorldEntity]:
    wanted = {_slug(team) for team in teams}
    matches: list[WorldEntity] = []
    for entity in graph.entities:
        if entity.entity_type != "match":
            continue
        team1 = _slug(str(entity.attributes.get("team1", "")))
        team2 = _slug(str(entity.attributes.get("team2", "")))
        if team1 in wanted or team2 in wanted:
            matches.append(entity)
    return matches


def write_graph(path: str | Path, graph: WorldGraph) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(graph.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def write_summary(path: str | Path, graph: WorldGraph, *, focused_matches: list[WorldEntity] | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = graph_summary(graph)
    lines = [
        "# World Cup KG Summary",
        "",
        f"- Graph id: {summary['graph_id']}",
        f"- Entities: {summary['entities']}",
        f"- Relationships: {summary['relationships']}",
        "",
        "## Entity Types",
        "",
    ]
    for label, count in summary["entity_types"].items():
        lines.append(f"- {label}: {count}")
    lines.extend(["", "## Relationship Types", ""])
    for label, count in summary["relationship_types"].items():
        lines.append(f"- {label}: {count}")
    if focused_matches is not None:
        lines.extend(["", "## Focused Matches", ""])
        for match in focused_matches:
            attrs = match.attributes
            lines.append(
                f"- {attrs.get('date')} {attrs.get('time')}: {attrs.get('team1')} vs {attrs.get('team2')} "
                f"({attrs.get('group') or attrs.get('round')}, {attrs.get('ground')})"
            )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _match_id(match: dict[str, Any], index: int) -> str:
    if match.get("num") is not None:
        return f"match:world_cup_2026:{int(match['num']):03d}"
    parts = [
        str(match.get("date") or "unknown_date"),
        str(match.get("team1") or "team1"),
        str(match.get("team2") or "team2"),
    ]
    return f"match:world_cup_2026:{index:03d}:{_slug('-'.join(parts))}"


def _entity_id(entity_type: str, name: str) -> str:
    return f"{entity_type}:{_slug(name)}"


def _slug(value: str) -> str:
    lowered = value.lower().strip()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
    return normalized.strip("_") or "unknown"


def _is_placeholder_team(value: str) -> bool:
    normalized = value.strip().upper()
    if normalized in {"TBD", ""}:
        return True
    return bool(re.fullmatch(r"(W|L)?\d+[A-Z]?(?:/[A-Z0-9]+)*|[123][A-Z](?:/[A-Z0-9]+)*", normalized))


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
