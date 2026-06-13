"""Configuration loader for the Polymarket integration.

Loads `.env` (base) and optionally `.env.test` (overrides) without any third-party
dependency, mirroring colony_harness/env.py. Also points Python at certifi's CA
bundle when available, because python.org Python on macOS otherwise fails TLS
verification (CERTIFICATE_VERIFY_FAILED) without touching system files.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_env_file(path: Path, *, override: bool) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


def ensure_tls_certs() -> None:
    """Set SSL_CERT_FILE from certifi if unset, so urllib/requests can verify TLS."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except Exception:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


def load_dotenv(*, test: bool = False) -> None:
    _load_env_file(HERE / ".env", override=False)
    if test:
        _load_env_file(HERE / ".env.test", override=True)
    ensure_tls_certs()


def _s(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _f(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _b(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    # network
    clob_host: str
    gamma_host: str
    chain_id: int
    rpc_url: str
    # wallet / auth
    private_key: str
    funder_address: str
    signature_type: int
    api_key: str
    api_secret: str
    api_passphrase: str
    # test-trade knobs
    test_token_id: str
    test_side: str
    test_price: float
    test_size: float
    max_test_usdc: float
    dry_run: bool

    @property
    def has_api_creds(self) -> bool:
        return bool(self.api_key and self.api_secret and self.api_passphrase)


def get_config(*, test: bool = False) -> Config:
    load_dotenv(test=test)
    return Config(
        clob_host=_s("POLYMARKET_CLOB_HOST", "https://clob.polymarket.com").rstrip("/"),
        gamma_host=_s("POLYMARKET_GAMMA_HOST", "https://gamma-api.polymarket.com").rstrip("/"),
        chain_id=int(_s("POLYGON_CHAIN_ID", "137") or "137"),
        rpc_url=_s("POLYGON_RPC_URL", "https://polygon-rpc.com"),
        private_key=_s("POLYMARKET_PRIVATE_KEY"),
        funder_address=_s("POLYMARKET_FUNDER_ADDRESS"),
        signature_type=int(_s("POLYMARKET_SIGNATURE_TYPE", "0") or "0"),
        api_key=_s("POLYMARKET_API_KEY"),
        api_secret=_s("POLYMARKET_API_SECRET"),
        api_passphrase=_s("POLYMARKET_API_PASSPHRASE"),
        test_token_id=_s("PM_TEST_TOKEN_ID"),
        test_side=_s("PM_TEST_SIDE", "BUY").upper(),
        test_price=_f("PM_TEST_PRICE", 0.5),
        test_size=_f("PM_TEST_SIZE", 5.0),
        max_test_usdc=_f("PM_MAX_TEST_USDC", 2.0),
        dry_run=_b("PM_DRY_RUN", True),
    )
