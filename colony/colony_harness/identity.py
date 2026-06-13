"""ENS identity-card helpers for Colony agents."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .agent import AntAgent


ADJECTIVES = [
    "amber",
    "brisk",
    "cold",
    "ember",
    "fable",
    "gold",
    "iron",
    "lumen",
    "onyx",
    "quiet",
    "sable",
    "silver",
]

NOUNS = [
    "oracle",
    "scout",
    "striker",
    "market",
    "signal",
    "keeper",
    "wager",
    "edge",
    "lens",
    "runner",
    "seer",
    "vector",
]


def build_identity_records(
    agents: list[AntAgent],
    *,
    ens_parent: str,
    profile_base_url: str = "https://colony.app/ants",
) -> dict[str, Any]:
    parent = _normalize_parent(ens_parent)
    assign_ens_names(agents, ens_parent=parent)
    by_id = {agent.agent_id: agent for agent in agents}
    records = []
    for agent in agents:
        records.append(_agent_identity_record(agent, agents_by_id=by_id, ens_parent=parent, profile_base_url=profile_base_url))
    return {
        "schema_version": 1,
        "ens_parent": parent,
        "records": records,
    }


def write_identity_records(
    path: str | Path,
    agents: list[AntAgent],
    *,
    ens_parent: str,
    profile_base_url: str = "https://colony.app/ants",
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_identity_records(agents, ens_parent=ens_parent, profile_base_url=profile_base_url)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def ens_name_for_agent(agent: AntAgent, ens_parent: str) -> str:
    label = identity_label_for_agent(agent)
    return f"{label}.{_normalize_parent(ens_parent)}"


def assign_ens_names(agents: list[AntAgent], *, ens_parent: str) -> None:
    parent = _normalize_parent(ens_parent)
    for agent in agents:
        agent.ens_name = ens_name_for_agent(agent, parent)


def identity_label_for_agent(agent: AntAgent) -> str:
    if agent.generation == 0:
        return f"root-{_name_token(agent.agent_id, 0)}-{_agent_number(agent.agent_id)}"
    return f"{_name_token(agent.genome_id, 0)}-{_name_token(agent.genome_id, 1)}-{_agent_number(agent.agent_id)}"


def _agent_identity_record(
    agent: AntAgent,
    *,
    agents_by_id: dict[str, AntAgent],
    ens_parent: str,
    profile_base_url: str,
) -> dict[str, Any]:
    ens_name = ens_name_for_agent(agent, ens_parent)
    root = _lineage_root(agent, agents_by_id)
    root_ens_name = ens_name_for_agent(root, ens_parent)
    parent_agent = agents_by_id.get(agent.parent_agent_id) if agent.parent_agent_id else None
    parent_ens_name = ens_name_for_agent(parent_agent, ens_parent) if parent_agent else ""
    profile_url = f"{profile_base_url.rstrip('/')}/{agent.agent_id}.json"
    verified_lineage = bool(agent.verified_lineage or root.verified_lineage)
    world_human_id = agent.world_human_id or root.world_human_id
    world_status = "inherited_verified" if verified_lineage and agent.agent_id != root.agent_id else (
        "verified_root" if verified_lineage else "unverified"
    )
    description = _description(agent, parent_ens_name=parent_ens_name, world_status=world_status)
    capabilities = _capabilities(agent)
    agent_context = {
        "schema": "ensip-26",
        "kind": "colony_ant",
        "agent_id": agent.agent_id,
        "ens_name": ens_name,
        "display_name": _display_name(ens_name),
        "description": description,
        "capabilities": capabilities,
        "generation": agent.generation,
        "parent": parent_ens_name,
        "lineage": root_ens_name,
        "world_status": world_status,
        "wallets": {
            "evm": agent.wallet_address,
            "arc_testnet": agent.wallet_address,
        },
        "profile": profile_url,
        "endpoints": {
            "web": profile_url,
        },
    }
    text_records = {
        "description": description,
        "url": profile_url,
        "agent-context": json.dumps(agent_context, sort_keys=True, separators=(",", ":")),
        "agent-endpoint[web]": profile_url,
        "com.colony.agent_id": agent.agent_id,
        "com.colony.parent": parent_ens_name,
        "com.colony.lineage": root_ens_name,
        "com.colony.world": world_status,
        "com.colony.capabilities": ",".join(capabilities),
        "com.colony.profile": profile_url,
    }
    return {
        "agent_id": agent.agent_id,
        "ens_name": ens_name,
        "label": ens_name.removesuffix(f".{ens_parent}"),
        "addr": agent.wallet_address,
        "text": text_records,
        "profile": {
            "agent_id": agent.agent_id,
            "ens_name": ens_name,
            "display_name": _display_name(ens_name),
            "generation": agent.generation,
            "parent": {
                "agent_id": agent.parent_agent_id,
                "ens_name": parent_ens_name,
            },
            "lineage": {
                "lineage_id": root.lineage_id or f"lineage_{root.agent_id}",
                "root_agent_id": root.agent_id,
                "root_name": root_ens_name,
                "verified_lineage": verified_lineage,
                "verification_source": "world_id_root" if verified_lineage else "",
                "verified_inherited": bool(verified_lineage and agent.agent_id != root.agent_id),
                "world_human_id": world_human_id,
            },
            "wallets": {
                "evm": agent.wallet_address,
                "arc_testnet": agent.wallet_address,
            },
            "state": {
                "status": "alive",
                "bankroll": round(agent.bankroll, 4),
                "accuracy": round(agent.accuracy, 4),
                "genome_hash": agent.genome.public_hash(),
                "genome_id": agent.genome_id,
            },
        },
    }


def _lineage_root(agent: AntAgent, agents_by_id: dict[str, AntAgent]) -> AntAgent:
    if agent.lineage_root_agent_id:
        return agents_by_id.get(agent.lineage_root_agent_id, agent)
    if agent.parent_agent_id:
        parent = agents_by_id.get(agent.parent_agent_id)
        if parent is not None:
            return _lineage_root(parent, agents_by_id)
    return agent


def _description(agent: AntAgent, *, parent_ens_name: str, world_status: str) -> str:
    status = "verified" if world_status in {"verified_root", "inherited_verified"} else "unverified"
    if parent_ens_name:
        return f"Gen {agent.generation} {status} ant, child of {parent_ens_name}, alive"
    return f"Gen {agent.generation} {status} lineage root, alive"


def _capabilities(agent: AntAgent) -> list[str]:
    weights = agent.genome.source_weights.normalized().to_dict()
    top_source = max(weights, key=weights.get)
    capabilities = ["forecast", "debate", "trade"]
    if top_source in {"stats", "odds", "news"}:
        capabilities.insert(0, f"{top_source}_scout")
    if agent.genome.herd_bias < -0.25:
        capabilities.append("contrarian")
    if agent.verified_lineage:
        capabilities.append("verified_lineage")
    return capabilities


def _display_name(ens_name: str) -> str:
    label = ens_name.split(".", 1)[0]
    return " ".join(part.capitalize() for part in label.split("-"))


def _name_token(seed: str, offset: int) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    if offset == 0:
        return ADJECTIVES[digest[0] % len(ADJECTIVES)]
    return NOUNS[digest[1] % len(NOUNS)]


def _agent_number(agent_id: str) -> str:
    match = re.search(r"(\d+)$", agent_id)
    if not match:
        return "0"
    return str(int(match.group(1)))


def _normalize_parent(value: str) -> str:
    parent = value.strip().lower().strip(".")
    if not parent:
        raise ValueError("ENS parent cannot be empty")
    return parent
