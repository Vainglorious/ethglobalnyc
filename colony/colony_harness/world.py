"""Worldcoin AgentKit verification receipts for Colony agents."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent import AntAgent


DEFAULT_WORLD_VERIFICATION_STORE = (
    Path(__file__).resolve().parents[1] / "secrets" / "world-agentkit-verifications.local.json"
)


@dataclass(frozen=True)
class WorldVerification:
    agent_id: str
    wallet_address: str
    ens_name: str
    tx_hash: str
    merkle_root: str
    nullifier_hash: str
    source: str
    registered_at: str

    @property
    def world_human_id(self) -> str:
        return self.nullifier_hash

    def to_dict(self) -> dict[str, str]:
        return {
            "agent_id": self.agent_id,
            "wallet_address": self.wallet_address,
            "ens_name": self.ens_name,
            "tx_hash": self.tx_hash,
            "merkle_root": self.merkle_root,
            "nullifier_hash": self.nullifier_hash,
            "source": self.source,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldVerification":
        return cls(
            agent_id=str(data.get("agent_id") or ""),
            wallet_address=str(data["wallet_address"]),
            ens_name=str(data.get("ens_name") or ""),
            tx_hash=str(data.get("tx_hash") or ""),
            merkle_root=str(data.get("merkle_root") or ""),
            nullifier_hash=str(data.get("nullifier_hash") or ""),
            source=str(data.get("source") or "worldcoin_agentkit_cli"),
            registered_at=str(data.get("registered_at") or ""),
        )


class WorldVerificationStore:
    """Gitignored local receipt store for Worldcoin AgentKit registrations."""

    def __init__(self, path: str | Path = DEFAULT_WORLD_VERIFICATION_STORE) -> None:
        self.path = Path(path)
        self._data = self._load()

    def add(self, verification: WorldVerification) -> None:
        wallet = _normalize_address(verification.wallet_address)
        records = self._data.setdefault("verifications", {})
        records[wallet] = verification.to_dict()
        records[wallet]["wallet_address"] = wallet
        self.save()

    def by_wallet(self, wallet_address: str) -> WorldVerification | None:
        wallet = _normalize_address(wallet_address)
        record = self._data.get("verifications", {}).get(wallet)
        if not record:
            return None
        return WorldVerification.from_dict(record)

    def apply_to_agents(self, agents: list[AntAgent]) -> int:
        count = 0
        for agent in agents:
            verification = self.by_wallet(agent.wallet_address) if agent.wallet_address else None
            if verification is None:
                continue
            agent.world_verified = True
            agent.world_human_id = verification.world_human_id
            count += 1
        return count

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": 1,
                "warning": "Local Worldcoin AgentKit verification receipts. Do not commit.",
                "verifications": {},
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"World verification store must contain a JSON object: {self.path}")
        data.setdefault("schema_version", 1)
        data.setdefault("warning", "Local Worldcoin AgentKit verification receipts. Do not commit.")
        data.setdefault("verifications", {})
        return data


def apply_world_verifications(
    agents: list[AntAgent],
    *,
    store_path: str | Path,
    required_agents: list[str] | None = None,
    required_roots: list[str] | None = None,
    allow_manual: bool = False,
) -> int:
    store = WorldVerificationStore(store_path)
    required = list(required_agents or []) + list(required_roots or [])
    verified_count = 0
    if required:
        for wanted in required:
            agent = find_agent_for_world_agent(agents, wanted)
            if agent is None:
                raise ValueError(f"World verified agent did not match any agent_id or wallet address: {wanted}")
            verification = store.by_wallet(agent.wallet_address) if agent.wallet_address else None
            if verification is not None:
                agent.world_verified = True
                agent.world_human_id = verification.world_human_id
                verified_count += 1
                continue
            if not allow_manual:
                raise ValueError(
                    f"{agent.agent_id} ({agent.wallet_address}) has no Worldcoin AgentKit receipt. "
                    "Run colony/register_world_agent.py for this agent first, or pass --allow-manual-world-agent for local testing."
                )
            agent.world_verified = True
            verified_count += 1
    return verified_count


def find_agent_for_world_agent(agents: list[AntAgent], wanted: str) -> AntAgent | None:
    normalized = wanted.lower()
    return next(
        (
            candidate
            for candidate in agents
            if candidate.agent_id.lower() == normalized
            or (candidate.wallet_address and candidate.wallet_address.lower() == normalized)
        ),
        None,
    )


def find_agent_for_world_root(agents: list[AntAgent], wanted: str) -> AntAgent | None:
    return find_agent_for_world_agent(agents, wanted)


def build_verification(
    *,
    agent_id: str,
    wallet_address: str,
    ens_name: str,
    tx_hash: str = "",
    merkle_root: str = "",
    nullifier_hash: str = "",
    source: str = "worldcoin_agentkit_cli",
) -> WorldVerification:
    return WorldVerification(
        agent_id=agent_id,
        wallet_address=_normalize_address(wallet_address),
        ens_name=ens_name,
        tx_hash=tx_hash,
        merkle_root=merkle_root,
        nullifier_hash=nullifier_hash,
        source=source,
        registered_at=datetime.now(timezone.utc).isoformat(),
    )


def _normalize_address(address: str) -> str:
    return address.strip()
