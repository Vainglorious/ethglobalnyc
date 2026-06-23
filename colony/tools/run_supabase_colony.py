#!/usr/bin/env python3
"""Fetch a user's colony from Supabase and run the local pipeline from it."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


COLONY_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = COLONY_DIR.parent
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from colony_harness.ant_records import supabase_row_to_agent  # noqa: E402
from colony_harness.colony_config import describe_colony_config, normalize_colony_config  # noqa: E402
from colony_harness.population import population_to_state  # noqa: E402
from colony_harness.supabase_client import (  # noqa: E402
    SupabaseRequestError,
    fetch_colony,
    fetch_colony_ants,
    load_supabase_settings,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the backend pipeline from a Supabase colony row.")
    parser.add_argument("--env", default=str(COLONY_DIR / ".env"), help="Path to colony/.env.")
    parser.add_argument("--pubkey", required=True, help="Wallet public key that owns the colony.")
    parser.add_argument("--match", default="Brazil vs Morocco", help='Match name, e.g. "Brazil vs Morocco".')
    parser.add_argument("--match-id", default=None, help="Exact KG match entity id.")
    parser.add_argument(
        "--prematch-snapshot-id",
        default=None,
        help="Forward a Supabase prematch snapshot id to run_match.py.",
    )
    parser.add_argument(
        "--data-mode",
        choices=["synthetic", "public", "openfootball"],
        default="synthetic",
        help="Data mode passed to run_match.py.",
    )
    parser.add_argument("--rooms", type=int, default=None, help="Room budget passed to run_match.py.")
    parser.add_argument("--agents", type=int, default=None, help="Temporary override for smoke tests.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed passed to run_match.py.")
    parser.add_argument("--runs-dir", default=str(COLONY_DIR / "runs"), help="Directory for run artifacts.")
    parser.add_argument("--population-state", default=None, help="Optional persistent ant roster JSON.")
    parser.add_argument("--refresh-data", action="store_true", help="Refetch public scout data instead of using cache.")
    parser.add_argument("--live-cache-dir", default=None, help="Cache directory for public-data scout fetches.")
    parser.add_argument("--openfootball-cache", default=None, help="Cache path for openfootball/worldcup.json.")
    parser.add_argument("--include-camel", action="store_true", help="Forward CAMEL/deep-research scout.")
    parser.add_argument("--include-x", action="store_true", help="Forward X availability scout.")
    parser.add_argument("--include-telegram", action="store_true", help="Forward Telegram social/news scout.")
    parser.add_argument("--include-polygun", action="store_true", help="Forward PolyGun market snapshot scout.")
    parser.add_argument("--include-deepseek-scout", action="store_true", help="Forward DeepSeek/OpenRouter scout.")
    parser.add_argument(
        "--scout-focus",
        action="append",
        default=[],
        help="Focused public re-scout target TEAM:CLAIM_TYPE. Can be repeated.",
    )
    parser.add_argument("--rescout-from-audit", default=None, help="Read scouting_audit.json and re-scout its backlog.")
    parser.add_argument("--voice-mode", choices=["template", "llm"], default="template")
    parser.add_argument(
        "--market-home-probability",
        type=float,
        default=None,
        help="Override the binary home-vs-away market anchor used by run_match.py.",
    )
    parser.add_argument(
        "--market-side-probabilities-json",
        default="",
        help='Optional raw 1X2 market probabilities JSON, e.g. {"home":0.15,"draw":0.23,"away":0.62}.',
    )
    parser.add_argument("--market-source", default="", help="Human-readable source label for market override.")
    parser.add_argument("--no-run-log", action="store_true", help="Disable run artifact creation.")
    parser.add_argument(
        "--no-memory-writes",
        action="store_true",
        help="Forward read-only memory mode to run_match.py.",
    )
    parser.add_argument("--debug", action="store_true", help="Write debug artifacts and room logs.")
    parser.add_argument("--dry-run", action="store_true", help="Print the command without executing it.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.agents is not None and args.agents < 1:
        raise SystemExit("--agents must be positive")
    if args.prematch_snapshot_id and args.data_mode == "synthetic":
        args.data_mode = "openfootball"
    try:
        settings = load_supabase_settings(args.env)
        row = fetch_colony(settings, args.pubkey, select="pubkey,name,config")
        if row is None:
            raise SystemExit(f"No colony found for pubkey: {args.pubkey}")
        ant_rows = [] if args.population_state else fetch_colony_ants(settings, args.pubkey, status="alive")
    except SupabaseRequestError as exc:
        raise SystemExit(str(exc)) from exc

    colony_config = normalize_colony_config(row.get("config") if isinstance(row.get("config"), dict) else {})

    print(f"Loaded colony: {row.get('name') or args.pubkey}", flush=True)
    print(f"Owner: {row.get('pubkey')}", flush=True)
    print(f"Colony config: {describe_colony_config(colony_config)}", flush=True)
    if args.population_state:
        print(f"Ant roster: using explicit population state {args.population_state}", flush=True)
    elif ant_rows:
        print(f"Ant roster: {len(ant_rows)} alive ants loaded from Supabase", flush=True)
    else:
        print("Ant roster: no persisted alive ants found, generating from colony config", flush=True)

    temp_paths: list[str] = []
    with tempfile.NamedTemporaryFile("w", suffix=".colony.json", delete=False, encoding="utf-8") as handle:
        json.dump(colony_config, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        colony_config_path = handle.name
        temp_paths.append(colony_config_path)

    population_state_path = args.population_state
    agent_count = args.agents
    if ant_rows and not args.population_state:
        selected_rows = ant_rows[: args.agents] if args.agents is not None else ant_rows
        agents = [supabase_row_to_agent(row) for row in selected_rows]
        with tempfile.NamedTemporaryFile("w", suffix=".population.json", delete=False, encoding="utf-8") as handle:
            payload = population_to_state(
                agents,
                seed=args.seed,
                note=f"supabase colony {args.pubkey}",
            )
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            population_state_path = handle.name
            temp_paths.append(population_state_path)
            agent_count = len(agents)

    command = _run_match_command(
        args,
        colony_config_path,
        population_state_path=population_state_path,
        agent_count=agent_count,
    )
    print("Pipeline command:", flush=True)
    print(shlex.join(command), flush=True)

    if args.dry_run:
        _cleanup(temp_paths)
        return

    try:
        subprocess.run(command, cwd=ROOT_DIR, check=True)
    finally:
        _cleanup(temp_paths)


def _run_match_command(
    args: argparse.Namespace,
    colony_config_path: str,
    *,
    population_state_path: str | None,
    agent_count: int | None,
) -> list[str]:
    command = [
        sys.executable,
        str(COLONY_DIR / "run_match.py"),
        "--env",
        args.env,
        "--colony-config",
        colony_config_path,
        "--match",
        args.match,
        "--data-mode",
        args.data_mode,
        "--voice-mode",
        args.voice_mode,
        "--seed",
        str(args.seed),
        "--runs-dir",
        args.runs_dir,
    ]
    if args.match_id:
        command.extend(["--match-id", args.match_id])
    if args.prematch_snapshot_id:
        command.extend(["--prematch-snapshot-id", args.prematch_snapshot_id])
    if args.rooms is not None:
        command.extend(["--rooms", str(args.rooms)])
    if args.refresh_data:
        command.append("--refresh-data")
    if args.live_cache_dir:
        command.extend(["--live-cache-dir", args.live_cache_dir])
    if args.openfootball_cache:
        command.extend(["--openfootball-cache", args.openfootball_cache])
    if args.include_camel:
        command.append("--include-camel")
    if args.include_x:
        command.append("--include-x")
    if args.include_telegram:
        command.append("--include-telegram")
    if args.include_polygun:
        command.append("--include-polygun")
    if args.include_deepseek_scout:
        command.append("--include-deepseek-scout")
    for focus in args.scout_focus:
        command.extend(["--scout-focus", focus])
    if args.rescout_from_audit:
        command.extend(["--rescout-from-audit", args.rescout_from_audit])
    if args.market_home_probability is not None:
        command.extend(["--market-home-probability", str(args.market_home_probability)])
    if args.market_side_probabilities_json:
        command.extend(["--market-side-probabilities-json", args.market_side_probabilities_json])
    if args.market_source:
        command.extend(["--market-source", args.market_source])
    if agent_count is not None:
        command.extend(["--agents", str(agent_count)])
    if population_state_path:
        command.extend(["--population-state", population_state_path])
    if args.no_run_log:
        command.append("--no-run-log")
    if args.no_memory_writes:
        command.append("--no-memory-writes")
    if args.debug:
        command.append("--debug")
    return command


def _cleanup(paths: list[str]) -> None:
    for path in paths:
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
