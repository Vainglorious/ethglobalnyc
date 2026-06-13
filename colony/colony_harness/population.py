"""Population state persistence for Colony harness runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .agent import AntAgent
from .genes import Genome


POPULATION_SCHEMA_VERSION = 1


def agent_to_state(agent: AntAgent) -> dict[str, Any]:
    state = {
        "agent_id": agent.agent_id,
        "name": agent.name,
        "genome_id": agent.genome_id,
        "generation": agent.generation,
        "bankroll": round(agent.bankroll, 4),
        "accuracy": round(agent.accuracy, 4),
        "wallet_address": agent.wallet_address,
        "ens_name": agent.ens_name,
        "parent_agent_id": agent.parent_agent_id,
        "lineage_id": agent.lineage_id,
        "lineage_root_agent_id": agent.lineage_root_agent_id,
        "verified_lineage": agent.verified_lineage,
        "world_human_id": agent.world_human_id,
        "genome": agent.genome.to_dict(),
    }
    if agent.evolution_role:
        state["evolution_role"] = agent.evolution_role
    if agent.parent_genome_id:
        state["parent_genome_id"] = agent.parent_genome_id
    if agent.previous_genome_id:
        state["previous_genome_id"] = agent.previous_genome_id
    if agent.last_settlement:
        state["last_settlement"] = agent.last_settlement
    return state


def agent_from_state(data: dict[str, Any]) -> AntAgent:
    genome = Genome.from_dict(data["genome"])
    expected_genome_id = str(data.get("genome_id") or "")
    if expected_genome_id and expected_genome_id != genome.stable_id():
        raise ValueError(
            f"Population state genome_id mismatch for {data.get('agent_id')}: "
            f"{expected_genome_id} != {genome.stable_id()}"
        )
    return AntAgent(
        agent_id=str(data["agent_id"]),
        name=str(data.get("name") or data["agent_id"]).replace("_", "-"),
        generation=int(data.get("generation") or 0),
        genome=genome,
        bankroll=float(data.get("bankroll") or 0.0),
        accuracy=float(data.get("accuracy") or 0.0),
        wallet_address=str(data.get("wallet_address") or ""),
        ens_name=str(data.get("ens_name") or ""),
        parent_agent_id=str(data.get("parent_agent_id") or ""),
        lineage_id=str(data.get("lineage_id") or ""),
        lineage_root_agent_id=str(data.get("lineage_root_agent_id") or ""),
        verified_lineage=bool(data.get("verified_lineage") or False),
        world_human_id=str(data.get("world_human_id") or ""),
        evolution_role=str(data.get("evolution_role") or ""),
        parent_genome_id=str(data.get("parent_genome_id") or ""),
        previous_genome_id=str(data.get("previous_genome_id") or ""),
        last_settlement=dict(data.get("last_settlement") or {}),
    )


def population_to_state(
    agents: list[AntAgent],
    *,
    seed: int,
    note: str = "",
) -> dict[str, Any]:
    return {
        "schema_version": POPULATION_SCHEMA_VERSION,
        "seed": seed,
        "note": note,
        "population_size": len(agents),
        "agents": [agent_to_state(agent) for agent in agents],
    }


def save_population_state(
    path: str | Path,
    agents: list[AntAgent],
    *,
    seed: int,
    note: str = "",
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = population_to_state(agents, seed=seed, note=note)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def load_population_state(path: str | Path) -> list[AntAgent]:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if int(payload.get("schema_version") or 0) != POPULATION_SCHEMA_VERSION:
        raise ValueError(f"Unsupported population schema_version in {source}")
    agents = [agent_from_state(record) for record in payload.get("agents") or []]
    if not agents:
        raise ValueError(f"Population state has no agents: {source}")
    _validate_unique_ids(agents)
    normalize_agent_lineages(agents)
    return agents


def normalize_agent_lineages(agents: list[AntAgent]) -> None:
    """Backfill lineage metadata for older population files."""
    agents_by_id = {agent.agent_id: agent for agent in agents}
    for agent in agents:
        if not agent.parent_agent_id and agent.parent_genome_id:
            parent = _find_parent_by_genome(agents, agent.parent_genome_id)
            if parent is not None:
                agent.parent_agent_id = parent.agent_id
        if not agent.lineage_root_agent_id:
            agent.lineage_root_agent_id = _lineage_root_id(agent, agents_by_id)
        if not agent.lineage_id:
            agent.lineage_id = f"lineage_{agent.lineage_root_agent_id or agent.agent_id}"
        root = agents_by_id.get(agent.lineage_root_agent_id)
        if root is not None and root is not agent:
            agent.verified_lineage = bool(agent.verified_lineage or root.verified_lineage)
            if not agent.world_human_id:
                agent.world_human_id = root.world_human_id


def _validate_unique_ids(agents: list[AntAgent]) -> None:
    agent_ids = [agent.agent_id for agent in agents]
    duplicate_agent_ids = sorted({agent_id for agent_id in agent_ids if agent_ids.count(agent_id) > 1})
    if duplicate_agent_ids:
        raise ValueError(f"Duplicate agent_id values in population state: {duplicate_agent_ids}")


def _find_parent_by_genome(agents: list[AntAgent], genome_id: str) -> AntAgent | None:
    for agent in agents:
        if agent.genome_id == genome_id:
            return agent
    return None


def _lineage_root_id(agent: AntAgent, agents_by_id: dict[str, AntAgent]) -> str:
    seen: set[str] = set()
    current = agent
    while current.parent_agent_id and current.parent_agent_id not in seen:
        seen.add(current.agent_id)
        parent = agents_by_id.get(current.parent_agent_id)
        if parent is None:
            break
        current = parent
    return current.agent_id
