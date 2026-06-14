"""EVM wallet store for Colony agents.

The same EVM address can be used across chains: World Chain for AgentKit
identity and Arc testnet for trading/x402 experiments. Only public addresses
are attached to agents.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import load_env_file


DEFAULT_WALLET_STORE = Path(__file__).resolve().parents[1] / "secrets" / "agent-wallets.local.json"
DEFAULT_DYNAMIC_ENV = Path(__file__).resolve().parents[2] / "dynamic" / ".env"
LOCAL_PROVIDER = "local"
DYNAMIC_PROVIDER = "dynamic"
SUPPORTED_PROVIDERS = {LOCAL_PROVIDER, DYNAMIC_PROVIDER}


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
    chains: dict[str, Any]
    private_key: str = ""
    provider: str = LOCAL_PROVIDER

    @property
    def public_record(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "wallet_address": self.address,
            "chains": self.chains,
            "wallet_provider": self.provider,
        }


class WalletStore:
    """Gitignored JSON wallet registry for agent addresses and signing handles."""

    def __init__(
        self,
        path: str | Path = DEFAULT_WALLET_STORE,
        *,
        provider: str | None = None,
        dynamic_env_path: str | Path | None = None,
    ) -> None:
        self.path = Path(path)
        self.provider = _resolve_provider(provider)
        if self.provider == DYNAMIC_PROVIDER:
            load_env_file(dynamic_env_path or os.environ.get("COLONY_DYNAMIC_ENV") or DEFAULT_DYNAMIC_ENV)
        self._data = self._load()

    def get_or_create(self, agent_id: str) -> AgentWallet:
        wallets = self._data.setdefault("wallets", {})
        if agent_id not in wallets:
            wallet = self._create_wallet(agent_id)
            wallets[agent_id] = {
                "address": wallet["address"],
                "provider": wallet["provider"],
                **({"private_key": wallet["private_key"]} if wallet.get("private_key") else {}),
                **({"dynamic": wallet["dynamic"]} if wallet.get("dynamic") else {}),
                "chains": DEFAULT_CHAIN_CONTEXT,
                "world_agentkit_registered": False,
                "world_human_id": "",
            }
            self.save()
        record = wallets[agent_id]
        provider = str(record.get("provider") or LOCAL_PROVIDER)
        if provider != self.provider:
            raise ValueError(
                f"Wallet {agent_id} in {self.path} uses provider={provider!r}, "
                f"but this run requested provider={self.provider!r}. Use a matching --wallet-provider "
                "or a fresh --wallet-store."
            )
        return AgentWallet(
            agent_id=agent_id,
            address=str(record["address"]),
            private_key=str(record.get("private_key") or ""),
            chains=dict(record.get("chains") or DEFAULT_CHAIN_CONTEXT),
            provider=provider,
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
                "provider": self.provider,
                "warning": _wallet_store_warning(self.provider),
                "wallets": {},
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Wallet store must contain a JSON object: {self.path}")
        data.setdefault("schema_version", 1)
        data.setdefault("provider", self.provider)
        data.setdefault("warning", _wallet_store_warning(str(data.get("provider") or self.provider)))
        data.setdefault("wallets", {})
        return data

    def _create_wallet(self, agent_id: str) -> dict[str, Any]:
        if self.provider == DYNAMIC_PROVIDER:
            return create_dynamic_wallet(agent_id)
        return {
            **create_evm_wallet(),
            "provider": LOCAL_PROVIDER,
        }


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
        try:
            return _create_wallet_with_cast()
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
            return _create_wallet_with_node()


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


def _create_wallet_with_node() -> dict[str, str]:
    arc_dir = Path(__file__).resolve().parents[2] / "arc"
    script = """
import { generatePrivateKey, privateKeyToAccount } from 'viem/accounts';
const privateKey = generatePrivateKey();
const account = privateKeyToAccount(privateKey);
console.log(JSON.stringify({ address: account.address, private_key: privateKey }));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=arc_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    address = payload.get("address")
    private_key = payload.get("private_key") or payload.get("privateKey")
    if not address or not private_key:
        raise ValueError("node wallet output did not include address/private_key")
    return {
        "address": str(address),
        "private_key": str(private_key),
    }


def create_dynamic_wallet(agent_id: str) -> dict[str, Any]:
    """Create a Dynamic V3 WaaS EVM wallet and return metadata, not a raw key."""

    base = (os.environ.get("DYNAMIC_API_BASE") or "https://app.dynamicauth.com/api/v0").rstrip("/")
    environment_id = os.environ.get("DYNAMIC_ENVIRONMENT_ID")
    api_key = os.environ.get("DYNAMIC_API_KEY")
    if not environment_id or not api_key:
        raise RuntimeError(
            "Dynamic wallet provider requires DYNAMIC_ENVIRONMENT_ID and DYNAMIC_API_KEY "
            "in the environment, colony/.env, or dynamic/.env."
        )

    identifier = _dynamic_identifier(agent_id)
    request = urllib.request.Request(
        f"{base}/environments/{environment_id}/waas/create",
        data=json.dumps({"identifier": identifier, "type": "email", "chains": ["EVM"]}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "colony-harness/0.1",
        },
        method="POST",
    )
    payload = _open_dynamic_wallet_request(request, agent_id=agent_id)

    credential = _extract_dynamic_evm_credential(payload)
    if not credential:
        raise RuntimeError(f"Dynamic wallet creation did not return an EVM credential for {agent_id}: {payload}")

    address = credential.get("address")
    if not address:
        raise RuntimeError(f"Dynamic wallet creation did not return an address for {agent_id}: {payload}")

    return {
        "provider": DYNAMIC_PROVIDER,
        "address": str(address),
        "dynamic": {
            "identifier": identifier,
            "environment_id": environment_id,
            "user_id": payload.get("user", {}).get("id"),
            "verified_credential_id": credential.get("id"),
            "chain": credential.get("chain"),
            "wallet_properties": credential.get("wallet_properties") or {},
        },
    }


def _resolve_provider(provider: str | None) -> str:
    value = (provider or os.environ.get("COLONY_WALLET_PROVIDER") or LOCAL_PROVIDER).strip().lower()
    if value not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported wallet provider {value!r}; expected one of {sorted(SUPPORTED_PROVIDERS)}")
    return value


def _wallet_store_warning(provider: str) -> str:
    if provider == DYNAMIC_PROVIDER:
        return "Dynamic V3 WaaS/MPC wallet metadata. No raw private keys are stored here."
    return "Local throwaway/testnet private keys. Do not commit or use for real funds."


def _dynamic_identifier(agent_id: str) -> str:
    prefix = os.environ.get("COLONY_DYNAMIC_WALLET_IDENTIFIER_PREFIX") or "colony-ant"
    domain = os.environ.get("COLONY_DYNAMIC_WALLET_IDENTIFIER_DOMAIN") or "colony.test"
    nonce = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}"
    return f"{prefix}-{agent_id}-{nonce}@{domain}"


def _dynamic_timeout() -> float:
    try:
        return float(os.environ.get("COLONY_DYNAMIC_WALLET_TIMEOUT_SECONDS") or "30")
    except ValueError:
        return 30.0


def _dynamic_retries() -> int:
    try:
        return max(0, int(os.environ.get("COLONY_DYNAMIC_WALLET_RETRIES") or "4"))
    except ValueError:
        return 4


def _dynamic_retry_delay() -> float:
    try:
        return max(0.0, float(os.environ.get("COLONY_DYNAMIC_WALLET_RETRY_DELAY_SECONDS") or "2"))
    except ValueError:
        return 2.0


def _open_dynamic_wallet_request(request: urllib.request.Request, *, agent_id: str) -> dict[str, Any]:
    attempts = _dynamic_retries() + 1
    delay = _dynamic_retry_delay()
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=_dynamic_timeout()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code} {body}"
            if exc.code < 500 or attempt >= attempts:
                raise RuntimeError(f"Dynamic wallet creation failed for {agent_id}: {last_error}") from exc
        except urllib.error.URLError as exc:
            last_error = str(exc.reason)
            if attempt >= attempts:
                raise RuntimeError(f"Dynamic wallet creation failed for {agent_id}: {last_error}") from exc
        if delay:
            time.sleep(delay * attempt)
    raise RuntimeError(f"Dynamic wallet creation failed for {agent_id}: {last_error}")


def _extract_dynamic_evm_credential(payload: dict[str, Any]) -> dict[str, Any] | None:
    credentials = payload.get("user", {}).get("verifiedCredentials") or []
    if not isinstance(credentials, list):
        return None
    for credential in credentials:
        if isinstance(credential, dict) and credential.get("chain") == "eip155":
            return credential
    for credential in credentials:
        if isinstance(credential, dict) and credential.get("address"):
            return credential
    return None
