"""Authenticated Polymarket CLOB client builder.

Thin wrapper around py-clob-client that wires up the wallet + L2 API credentials
from config.py. Requires `pip install -r polymarket/requirements.txt`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config  # noqa: E402


def build_client(cfg: Config, *, with_creds: bool = True):
    """Construct a ready-to-use ClobClient. Raises SystemExit with a clear message
    if required secrets are missing (so callers fail loudly, not cryptically)."""
    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds
    except ImportError as exc:  # noqa: BLE001
        raise SystemExit(
            "py-clob-client is not installed. Run:\n"
            "  pip install -r polymarket/requirements.txt"
        ) from exc

    if not cfg.private_key:
        raise SystemExit("POLYMARKET_PRIVATE_KEY is not set in polymarket/.env")

    kwargs = dict(host=cfg.clob_host, key=cfg.private_key, chain_id=cfg.chain_id)
    if cfg.signature_type != 0:
        if not cfg.funder_address:
            raise SystemExit(
                f"POLYMARKET_SIGNATURE_TYPE={cfg.signature_type} requires "
                "POLYMARKET_FUNDER_ADDRESS (the proxy wallet that holds funds)."
            )
        kwargs["signature_type"] = cfg.signature_type
        kwargs["funder"] = cfg.funder_address

    client = ClobClient(**kwargs)

    if with_creds:
        if cfg.has_api_creds:
            client.set_api_creds(ApiCreds(cfg.api_key, cfg.api_secret, cfg.api_passphrase))
        else:
            # Derive L2 creds from the wallet signature (idempotent).
            client.set_api_creds(client.create_or_derive_api_creds())

    return client
