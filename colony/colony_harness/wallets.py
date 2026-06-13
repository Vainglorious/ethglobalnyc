"""Local EVM wallet store for Colony agents.

The same EVM address can be used across chains: World Chain for AgentKit
identity and Arc testnet for trading/x402 experiments. Private keys stay in the
local wallet store and only public addresses are attached to agents.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_WALLET_STORE = Path(__file__).resolve().parents[1] / "secrets" / "agent-wallets.local.json"


DEFAULT_CHAIN_CONTEXT = {
    "world_agentkit": {
        "chain": "World Chain mainnet",
        "chain_id": 480,
        "purpose": "Worldcoin AgentKit human verification",
    },
    "arc_testnet": {
        "chain": "Arc testnet",
        "chain_id": None,
        "purpose": "test trades and x402 settlement",
    },
}


@dataclass(frozen=True)
class AgentWallet:
    agent_id: str
    address: str
    private_key: str
    chains: dict[str, Any]

    @property
    def public_record(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "wallet_address": self.address,
            "chains": self.chains,
        }


class WalletStore:
    """Gitignored JSON keystore for throwaway/testnet agent wallets."""

    def __init__(self, path: str | Path = DEFAULT_WALLET_STORE) -> None:
        self.path = Path(path)
        self._data = self._load()

    def get_or_create(self, agent_id: str) -> AgentWallet:
        wallets = self._data.setdefault("wallets", {})
        if agent_id not in wallets:
            wallet = create_evm_wallet()
            wallets[agent_id] = {
                "address": wallet["address"],
                "private_key": wallet["private_key"],
                "chains": DEFAULT_CHAIN_CONTEXT,
                "world_agentkit_registered": False,
                "world_human_id": "",
            }
            self.save()
        record = wallets[agent_id]
        return AgentWallet(
            agent_id=agent_id,
            address=str(record["address"]),
            private_key=str(record["private_key"]),
            chains=dict(record.get("chains") or DEFAULT_CHAIN_CONTEXT),
        )

    def public_address(self, agent_id: str) -> str:
        wallets = self._data.get("wallets", {})
        if agent_id not in wallets:
            return ""
        return str(wallets[agent_id].get("address") or "")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._data, indent=2, sort_keys=True)
        self.path.write_text(payload + "\n", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _load(self) -> dict:
        if not self.path.exists():
            return {
                "schema_version": 1,
                "warning": "Local throwaway/testnet private keys. Do not commit or use for real funds.",
                "wallets": {},
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Wallet store must contain a JSON object: {self.path}")
        data.setdefault("schema_version", 1)
        data.setdefault("warning", "Local throwaway/testnet private keys. Do not commit or use for real funds.")
        data.setdefault("wallets", {})
        return data


def create_evm_wallet() -> dict[str, str]:
    """Create an EVM keypair with eth-account, falling back to Foundry cast."""

    try:
        from eth_account import Account

        account = Account.create(secrets.token_hex(32))
        return {
            "address": account.address,
            "private_key": account.key.hex(),
        }
    except ImportError:
        return _create_wallet_with_cast()


def _create_wallet_with_cast() -> dict[str, str]:
    result = subprocess.run(
        ["cast", "wallet", "new", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    address = payload.get("address") or payload.get("Address")
    private_key = payload.get("private_key") or payload.get("privateKey") or payload.get("Private key")
    if not address or not private_key:
        raise ValueError("cast wallet output did not include address/private_key")
    return {
        "address": str(address),
        "private_key": str(private_key),
    }
