#!/usr/bin/env python3
"""Create or update a user colony row in Supabase."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness.colony_config import (  # noqa: E402
    ALLOWED_ANT_COUNTS,
    ALLOWED_PRESETS,
    ALLOWED_RISK_PROFILES,
    CONFIG_SCHEMA_VERSION,
    MODEL_SPECIES,
    describe_colony_config,
    normalize_colony_config,
)
from colony_harness.env import load_env_file  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a Supabase-backed user colony.")
    parser.add_argument("--env", default=str(COLONY_DIR / ".env"), help="Path to colony/.env.")
    parser.add_argument("--pubkey", required=True, help="Wallet public key that owns the colony.")
    parser.add_argument("--name", default=None, help="Human-readable colony name.")
    parser.add_argument("--ant-count", type=int, choices=sorted(ALLOWED_ANT_COUNTS), default=50)
    parser.add_argument("--preset", choices=sorted(ALLOWED_PRESETS), default="market")
    parser.add_argument("--risk-profile", choices=sorted(ALLOWED_RISK_PROFILES), default=None)
    parser.add_argument("--model-preference", choices=sorted(MODEL_SPECIES), default=None)
    parser.add_argument(
        "--personality-mix",
        default=None,
        help="Comma-separated personas, for example 'market contrarian,crowd watcher'.",
    )
    parser.add_argument(
        "--kg-focus",
        default=None,
        help="Comma-separated KG focus tags, for example 'odds,market_context,sentiment'.",
    )
    parser.add_argument(
        "--source-weights",
        default=None,
        help="JSON object or comma pairs, for example 'stats=0.16,odds=0.52,news=0.12,debate=0.20'.",
    )
    parser.add_argument("--angle", type=float, default=0.0, help="Frontend placement angle.")
    parser.add_argument("--dist", type=float, default=120.0, help="Frontend placement distance.")
    parser.add_argument("--accent", default="0xB07E1C", help="Frontend accent color as integer or 0xRRGGBB.")
    parser.add_argument("--visibility", choices=["public", "private", "unlisted"], default="public")
    parser.add_argument("--dry-run", action="store_true", help="Print the row without writing to Supabase.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pubkey = args.pubkey.strip()
    if not pubkey:
        raise SystemExit("--pubkey is required")

    colony_config = _build_colony_config(args)
    row = {
        "pubkey": pubkey,
        "angle": args.angle,
        "dist": args.dist,
        "accent": _parse_int(args.accent),
        "name": args.name or _default_name(pubkey),
        "config": colony_config,
        "visibility": args.visibility,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
    }

    if args.dry_run:
        print(json.dumps(row, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"Colony config: {describe_colony_config(colony_config)}")
        return

    url, key = _supabase_settings(args.env)
    response = _upsert_colony(url, key, row)
    print("Supabase colony upserted.")
    print(f"Colony config: {describe_colony_config(colony_config)}")
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))


def _build_colony_config(args: argparse.Namespace) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "preset": args.preset,
        "ant_count": args.ant_count,
    }
    if args.risk_profile:
        raw["risk_profile"] = args.risk_profile
    if args.model_preference:
        raw["model_preference"] = args.model_preference
    if args.personality_mix:
        raw["personality_mix"] = args.personality_mix
    if args.kg_focus:
        raw["kg_focus"] = args.kg_focus
    if args.source_weights:
        raw["source_weights"] = _parse_source_weights(args.source_weights)
    return normalize_colony_config(raw)


def _parse_source_weights(value: str) -> dict[str, float]:
    text = value.strip()
    if text.startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise SystemExit("--source-weights JSON must be an object")
        return {str(key): float(raw) for key, raw in payload.items()}

    weights: dict[str, float] = {}
    for part in text.split(","):
        item = part.strip()
        if not item:
            continue
        if "=" not in item:
            raise SystemExit("--source-weights must use key=value comma pairs")
        key, raw = item.split("=", 1)
        weights[key.strip()] = float(raw.strip())
    return weights


def _parse_int(value: str) -> int:
    try:
        return int(str(value).strip(), 0)
    except ValueError as exc:
        raise SystemExit(f"Invalid integer value: {value}") from exc


def _default_name(pubkey: str) -> str:
    if len(pubkey) <= 12:
        return f"Colony {pubkey}"
    return f"Colony {pubkey[:4]}...{pubkey[-4:]}"


def _supabase_settings(env_path: str) -> tuple[str, str]:
    load_env_file(env_path)
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    )
    if not url:
        raise SystemExit("Missing SUPABASE_URL in colony/.env")
    if not key:
        raise SystemExit("Missing SUPABASE_PUBLISHABLE_KEY in colony/.env")
    return url.rstrip("/"), key


def _upsert_colony(url: str, key: str, row: dict[str, Any]) -> Any:
    endpoint = f"{url}/rest/v1/colonies?on_conflict=pubkey"
    body = json.dumps(row, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - user-configured Supabase URL.
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Supabase upsert failed with HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Supabase upsert failed: {exc}") from exc
    return json.loads(payload) if payload.strip() else []


if __name__ == "__main__":
    main()
