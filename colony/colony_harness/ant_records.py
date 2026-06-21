"""Supabase row helpers for persistent colony ants."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .agent import AntAgent
from .colony_config import normalize_colony_config
from .genes import Genome
from .harness import ColonyHarness
from .population import agent_from_state


def ant_to_supabase_row(
    agent: AntAgent,
    *,
    pubkey: str,
    colony_config: dict[str, Any] | None = None,
    status: str = "alive",
) -> dict[str, Any]:
    normalized_config = normalize_colony_config(colony_config)
    genome = agent.genome
    weights = genome.source_weights.normalized().to_dict()
    risk_profile = risk_profile_for_genome(genome)
    datafeed_interests = datafeed_interests_for_genome(genome, normalized_config)
    strategy = {
        "preset": normalized_config["preset"],
        "estimator": genome.estimator,
        "risk_profile": risk_profile,
        "risk_appetite": genome.risk_appetite,
        "edge_threshold": genome.edge_threshold,
        "query_budget": genome.query_budget,
        "herd_bias": genome.herd_bias,
        "source_weights": weights,
    }

    return {
        "pubkey": pubkey,
        "agent_id": agent.agent_id,
        "name": agent.name,
        "status": status,
        "generation": agent.generation,
        "parent_agent_id": agent.parent_agent_id,
        "lineage_id": agent.lineage_id,
        "lineage_root_agent_id": agent.lineage_root_agent_id,
        "genome_id": agent.genome_id,
        "genome": genome.to_dict(),
        "strategy": strategy,
        "datafeed_interests": datafeed_interests,
        "model": genome.model,
        "persona": genome.persona,
        "risk_profile": risk_profile,
        "bankroll": round(agent.bankroll, 4),
        "accuracy": round(agent.accuracy, 4),
        "wallet_address": agent.wallet_address,
        "ens_name": agent.ens_name,
        "metadata": {
            "world_status": agent.world_status,
            "world_access_tier": agent.world_access_tier,
            "world_verified": agent.world_verified,
            "world_human_id": agent.world_human_id,
            "verified_lineage": agent.verified_lineage,
            "evolution_role": agent.evolution_role,
            "parent_genome_id": agent.parent_genome_id,
            "previous_genome_id": agent.previous_genome_id,
        },
    }


def generate_ant_rows(
    *,
    pubkey: str,
    colony_config: dict[str, Any] | None,
    population_size: int,
    seed: int = 42,
    status: str = "alive",
) -> list[dict[str, Any]]:
    if population_size < 1:
        raise ValueError("population_size must be positive")
    harness = ColonyHarness(
        population_size=population_size,
        speaker_slots=min(6, population_size),
        seed=seed,
        colony_config=colony_config,
    )
    return [
        ant_to_supabase_row(agent, pubkey=pubkey, colony_config=colony_config, status=status)
        for agent in harness.agents
    ]


def supabase_row_to_agent(row: dict[str, Any]) -> AntAgent:
    genome_payload = row.get("genome")
    if not isinstance(genome_payload, dict):
        raise ValueError(f"Ant row has no genome object: {row.get('agent_id')}")
    genome = Genome.from_dict(genome_payload)
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    state = {
        "agent_id": str(row["agent_id"]),
        "name": str(row.get("name") or row["agent_id"]),
        "genome_id": str(row.get("genome_id") or genome.stable_id()),
        "generation": int(row.get("generation") or 0),
        "bankroll": _float(row.get("bankroll"), 0.0),
        "accuracy": _float(row.get("accuracy"), 0.0),
        "wallet_address": str(row.get("wallet_address") or ""),
        "ens_name": str(row.get("ens_name") or ""),
        "parent_agent_id": str(row.get("parent_agent_id") or ""),
        "lineage_id": str(row.get("lineage_id") or ""),
        "lineage_root_agent_id": str(row.get("lineage_root_agent_id") or ""),
        "verified_lineage": bool(metadata.get("verified_lineage") or False),
        "world_verified": bool(metadata.get("world_verified") or False),
        "world_human_id": str(metadata.get("world_human_id") or ""),
        "evolution_role": str(metadata.get("evolution_role") or ""),
        "parent_genome_id": str(metadata.get("parent_genome_id") or ""),
        "previous_genome_id": str(metadata.get("previous_genome_id") or ""),
        "genome": genome.to_dict(),
    }
    return agent_from_state(state)


def risk_profile_for_genome(genome: Genome) -> str:
    if genome.risk_appetite >= 0.135 or genome.edge_threshold <= 0.035:
        return "risky"
    if genome.risk_appetite <= 0.06 or genome.edge_threshold >= 0.105:
        return "secure"
    return "balanced"


def datafeed_interests_for_genome(genome: Genome, colony_config: dict[str, Any] | None = None) -> list[str]:
    normalized_config = normalize_colony_config(colony_config)
    interests: list[str] = []
    for item in normalized_config["kg_focus"]:
        _append_unique(interests, item)

    weights = genome.source_weights.normalized().to_dict()
    for label, value in sorted(weights.items(), key=lambda item: item[1], reverse=True):
        if value >= 0.24:
            _append_unique(interests, label)

    if genome.estimator == "llm":
        _append_unique(interests, "llm_reasoning")
    if "scout" in genome.persona:
        _append_unique(interests, "availability")
    if "contrarian" in genome.persona or "value" in genome.persona:
        _append_unique(interests, "market_mispricing")
    return interests


def next_agent_index(rows: list[dict[str, Any]]) -> int:
    next_index = 0
    for row in rows:
        agent_id = str(row.get("agent_id") or "")
        match = re.fullmatch(r"ant_(\d+)", agent_id)
        if not match:
            continue
        next_index = max(next_index, int(match.group(1)) + 1)
    return next_index


def _append_unique(items: list[str], value: str) -> None:
    cleaned = str(value).strip()
    if cleaned and cleaned not in items:
        items.append(cleaned)


def _float(value: Any, fallback: float) -> float:
    if value is None:
        return fallback
    if isinstance(value, Decimal):
        return float(value)
    return float(value)
