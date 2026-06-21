#!/usr/bin/env python3
"""Manage Supabase colonies and persistent ant rosters."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness.ant_records import generate_ant_rows, next_agent_index  # noqa: E402
from colony_harness.colony_config import (  # noqa: E402
    ALLOWED_ANT_COUNTS,
    ALLOWED_PRESETS,
    ALLOWED_RISK_PROFILES,
    CONFIG_SCHEMA_VERSION,
    MODEL_SPECIES,
    describe_colony_config,
    normalize_colony_config,
)
from colony_harness.supabase_client import (  # noqa: E402
    SupabaseRequestError,
    delete_colony,
    delete_colony_ants,
    fetch_colony,
    fetch_colony_ants,
    load_supabase_settings,
    update_ant_status,
    upsert_colony,
    upsert_colony_ants,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage Supabase-backed Colony product data.")
    parser.add_argument("--env", default=str(COLONY_DIR / ".env"), help="Path to colony/.env.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create-colony", help="Create or update a user colony row.")
    _add_colony_args(create)
    create.add_argument("--with-ants", action="store_true", help="Also create the initial ant roster.")
    create.add_argument("--seed", type=int, default=42, help="RNG seed for --with-ants.")

    remove = subparsers.add_parser("remove-colony", help="Delete a colony and cascade-delete its ants.")
    remove.add_argument("--pubkey", required=True)
    remove.add_argument("--yes", action="store_true", help="Required confirmation for deletion.")

    add_ants = subparsers.add_parser("add-ants", help="Add missing ants to a colony roster.")
    add_ants.add_argument("--pubkey", required=True)
    add_ants.add_argument(
        "--target-count",
        type=int,
        choices=sorted(ALLOWED_ANT_COUNTS),
        default=None,
        help="Ensure the roster reaches this total. Defaults to colonies.config.ant_count.",
    )
    add_ants.add_argument("--count", type=int, default=None, help="Add this many new ants after the current max id.")
    add_ants.add_argument("--seed", type=int, default=42, help="RNG seed used to generate deterministic ants.")
    add_ants.add_argument("--replace", action="store_true", help="Delete existing ants first, then recreate the roster.")

    list_ants = subparsers.add_parser("list-ants", help="List ant rows for one colony.")
    list_ants.add_argument("--pubkey", required=True)
    list_ants.add_argument("--status", choices=["alive", "dead", "inactive", "retired", "all"], default="all")
    list_ants.add_argument("--json", action="store_true", help="Print full JSON rows.")
    list_ants.add_argument("--limit", type=int, default=None)

    set_status = subparsers.add_parser("set-ant-status", help="Update one ant status.")
    set_status.add_argument("--pubkey", required=True)
    set_status.add_argument("--agent-id", required=True)
    set_status.add_argument("--status", choices=["alive", "dead", "inactive", "retired"], required=True)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        settings = load_supabase_settings(args.env)
        if args.command == "create-colony":
            _create_colony(settings, args)
        elif args.command == "remove-colony":
            _remove_colony(settings, args)
        elif args.command == "add-ants":
            _add_ants(settings, args)
        elif args.command == "list-ants":
            _list_ants(settings, args)
        elif args.command == "set-ant-status":
            _set_ant_status(settings, args)
    except SupabaseRequestError as exc:
        raise SystemExit(str(exc)) from exc


def _create_colony(settings: Any, args: argparse.Namespace) -> None:
    pubkey = _clean_pubkey(args.pubkey)
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
    response = upsert_colony(settings, row)
    print("Colony upserted.")
    print(f"Colony config: {describe_colony_config(colony_config)}")
    print(json.dumps(response, ensure_ascii=False, indent=2, sort_keys=True))
    if args.with_ants:
        _ensure_ant_roster(settings, pubkey=pubkey, colony_config=colony_config, target_count=colony_config["ant_count"], seed=args.seed)


def _remove_colony(settings: Any, args: argparse.Namespace) -> None:
    pubkey = _clean_pubkey(args.pubkey)
    if not args.yes:
        raise SystemExit("Refusing to delete without --yes")
    deleted = delete_colony(settings, pubkey)
    print(f"Deleted colonies: {len(deleted)}")
    print(json.dumps(deleted, ensure_ascii=False, indent=2, sort_keys=True))


def _add_ants(settings: Any, args: argparse.Namespace) -> None:
    pubkey = _clean_pubkey(args.pubkey)
    colony = fetch_colony(settings, pubkey, select="pubkey,name,config")
    if colony is None:
        raise SystemExit(f"No colony found for pubkey: {pubkey}")
    colony_config = normalize_colony_config(colony.get("config") if isinstance(colony.get("config"), dict) else {})
    existing = [] if args.replace else fetch_colony_ants(settings, pubkey, status="all", select="agent_id")
    if args.replace:
        deleted = delete_colony_ants(settings, pubkey)
        print(f"Deleted existing ants: {len(deleted)}")

    if args.count is not None and args.count < 1:
        raise SystemExit("--count must be positive")
    if args.count is not None and args.target_count is not None:
        raise SystemExit("Use either --count or --target-count, not both")

    if args.count is not None:
        start_index = next_agent_index(existing)
        target_count = start_index + args.count
        max_count = max(ALLOWED_ANT_COUNTS)
        if target_count > max_count:
            raise SystemExit(f"Refusing to create {target_count} ants; max supported roster size is {max_count}.")
        min_agent_index = start_index
    else:
        target_count = args.target_count or int(colony_config["ant_count"])
        min_agent_index = 0

    _ensure_ant_roster(
        settings,
        pubkey=pubkey,
        colony_config=colony_config,
        target_count=target_count,
        seed=args.seed,
        existing_rows=existing,
        min_agent_index=min_agent_index,
    )


def _ensure_ant_roster(
    settings: Any,
    *,
    pubkey: str,
    colony_config: dict[str, Any],
    target_count: int,
    seed: int,
    existing_rows: list[dict[str, Any]] | None = None,
    min_agent_index: int = 0,
) -> None:
    existing = existing_rows if existing_rows is not None else fetch_colony_ants(settings, pubkey, status="all", select="agent_id")
    existing_ids = {str(row.get("agent_id") or "") for row in existing}
    rows = generate_ant_rows(
        pubkey=pubkey,
        colony_config=colony_config,
        population_size=target_count,
        seed=seed,
        status="alive",
    )
    rows_to_write = [
        row
        for row in rows
        if row["agent_id"] not in existing_ids and _agent_index(row["agent_id"]) >= min_agent_index
    ]
    if not rows_to_write:
        print(f"Ant roster already has {len(existing_ids)} ants; no rows written.")
        return
    written = upsert_colony_ants(settings, rows_to_write)
    print(f"Ant rows upserted: {len(written)}")
    print(f"Target roster size: {target_count}")
    print(_ant_summary(written))


def _list_ants(settings: Any, args: argparse.Namespace) -> None:
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be positive")
    rows = fetch_colony_ants(settings, args.pubkey, status=args.status, limit=args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"Ants: {len(rows)}")
    for row in rows:
        interests = row.get("datafeed_interests") if isinstance(row.get("datafeed_interests"), list) else []
        parent = row.get("parent_agent_id") or "-"
        print(
            f"{row.get('agent_id')} "
            f"status={row.get('status')} "
            f"model={row.get('model')} "
            f"persona={row.get('persona')} "
            f"risk={row.get('risk_profile')} "
            f"parent={parent} "
            f"datafeeds={','.join(str(item) for item in interests)}"
        )


def _set_ant_status(settings: Any, args: argparse.Namespace) -> None:
    rows = update_ant_status(settings, pubkey=args.pubkey, agent_id=args.agent_id, status=args.status)
    print(f"Updated ants: {len(rows)}")
    print(json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True))


def _add_colony_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pubkey", required=True, help="Wallet public key that owns the colony.")
    parser.add_argument("--name", default=None, help="Human-readable colony name.")
    parser.add_argument("--ant-count", type=int, choices=sorted(ALLOWED_ANT_COUNTS), default=50)
    parser.add_argument("--preset", choices=sorted(ALLOWED_PRESETS), default="market")
    parser.add_argument("--risk-profile", choices=sorted(ALLOWED_RISK_PROFILES), default=None)
    parser.add_argument("--model-preference", choices=sorted(MODEL_SPECIES), default=None)
    parser.add_argument("--personality-mix", default=None, help="Comma-separated personas.")
    parser.add_argument("--kg-focus", default=None, help="Comma-separated KG focus tags.")
    parser.add_argument("--source-weights", default=None, help="JSON object or comma key=value pairs.")
    parser.add_argument("--angle", type=float, default=0.0, help="Frontend placement angle.")
    parser.add_argument("--dist", type=float, default=120.0, help="Frontend placement distance.")
    parser.add_argument("--accent", default="0xB07E1C", help="Frontend accent color as integer or 0xRRGGBB.")
    parser.add_argument("--visibility", choices=["public", "private", "unlisted"], default="public")


def _build_colony_config(args: argparse.Namespace) -> dict[str, Any]:
    raw: dict[str, Any] = {"preset": args.preset, "ant_count": args.ant_count}
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


def _agent_index(agent_id: str) -> int:
    match = re.fullmatch(r"ant_(\d+)", str(agent_id))
    if not match:
        return 0
    return int(match.group(1))


def _ant_summary(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No ant rows."
    models: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for row in rows:
        models[str(row.get("model") or "")] = models.get(str(row.get("model") or ""), 0) + 1
        statuses[str(row.get("status") or "")] = statuses.get(str(row.get("status") or ""), 0) + 1
    model_text = " ".join(f"{key}={value}" for key, value in sorted(models.items()))
    status_text = " ".join(f"{key}={value}" for key, value in sorted(statuses.items()))
    return f"Statuses: {status_text}\nModels: {model_text}"


def _parse_int(value: str) -> int:
    try:
        return int(str(value).strip(), 0)
    except ValueError as exc:
        raise SystemExit(f"Invalid integer value: {value}") from exc


def _default_name(pubkey: str) -> str:
    if len(pubkey) <= 12:
        return f"Colony {pubkey}"
    return f"Colony {pubkey[:4]}...{pubkey[-4:]}"


def _clean_pubkey(pubkey: str) -> str:
    cleaned = pubkey.strip()
    if not cleaned:
        raise SystemExit("--pubkey is required")
    return cleaned


if __name__ == "__main__":
    main()
