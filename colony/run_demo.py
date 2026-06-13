#!/usr/bin/env python3
"""Run a local Colony debate harness demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from colony_harness import ColonyHarness
from colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
from colony_harness.console import print_debate_quality, print_final_feed, print_room_debug
from colony_harness.env import load_env_file
from colony_harness.identity import assign_ens_names, write_identity_records
from colony_harness.models import MatchContext
from colony_harness.population import load_population_state, normalize_agent_lineages, save_population_state
from colony_harness.voice import TemplateVoiceModel, llm_voice_model_from_env


DEFAULT_CONFIG = Path(__file__).parent / "config" / "example.colony.json"


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Colony debate harness.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to a colony config JSON file.")
    parser.add_argument("--agents", type=int, default=None, help="Override population size.")
    parser.add_argument(
        "--rooms",
        type=int,
        default=None,
        help="Override maximum number of topic rooms. Preferred name for new runs.",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Deprecated alias for --rooms, kept for older commands.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Override RNG seed.")
    parser.add_argument(
        "--population-state",
        default=None,
        help="Load an existing population state or create/save one at this path.",
    )
    parser.add_argument("--out", default=None, help="Optional JSONL output path.")
    parser.add_argument("--runs-dir", default="colony/runs", help="Directory for automatic compact run logs.")
    parser.add_argument("--no-run-log", action="store_true", help="Disable automatic compact run logs.")
    parser.add_argument("--debug", action="store_true", help="Write an additional human-readable debug.md report.")
    parser.add_argument("--show-roster", action="store_true", help="Print public predictor records.")
    parser.add_argument(
        "--agent-wallets",
        action="store_true",
        help="Create/reuse local EVM wallets for agents and expose only public addresses.",
    )
    parser.add_argument(
        "--wallet-store",
        default="colony/secrets/agent-wallets.local.json",
        help="Gitignored local JSON store for agent private keys.",
    )
    parser.add_argument(
        "--ens-parent",
        default=None,
        help="Parent ENS name for ant identity cards. Defaults to COLONY_ENS_PARENT or colonny.eth.",
    )
    parser.add_argument(
        "--identity-out",
        default=None,
        help="Write generated ENS identity-card records for every ant to this JSON file.",
    )
    parser.add_argument(
        "--verified-root",
        action="append",
        default=[],
        help="Mark a lineage root as World ID verified by agent_id or wallet address. Can be repeated.",
    )
    parser.add_argument(
        "--world-human-id",
        default="",
        help="Optional pseudonymous World ID identifier to attach to verified roots.",
    )
    parser.add_argument(
        "--profile-base-url",
        default="https://colony.app/ants",
        help="Base URL used in ENS profile and agent-context records.",
    )
    parser.add_argument(
        "--voice-mode",
        choices=["template", "llm"],
        default="template",
        help="Use deterministic templates or an OpenAI-compatible LLM for debate messages.",
    )
    parser.add_argument("--env", default="colony/.env", help="Optional .env path for LLM settings.")
    parser.add_argument(
        "--test-voice",
        action="store_true",
        help="Test the configured LLM voice once and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    config = load_config(Path(args.config))
    population = config.get("population", {})

    if args.voice_mode == "llm":
        voice_model = llm_voice_model_from_env()
    else:
        voice_model = TemplateVoiceModel()

    if args.test_voice:
        from colony_harness.genes import random_genome

        import random

        test_match = MatchContext.from_dict(config)
        test_genome = random_genome(random.Random(7))
        try:
            message = voice_model.render_claim(
                agent_name="ant-test",
                genome=test_genome,
                match=test_match,
                probability=0.53,
                direction="home",
            )
        except Exception as exc:
            print(f"Voice test failed: {exc}")
            raise SystemExit(1) from exc
        print(message)
        return

    configured_agents = int(population.get("agents", 40))
    room_budget = _resolve_room_budget(
        rooms=args.rooms,
        speakers=args.speakers,
        default=int(population.get("speaker_slots", 6)),
    )
    loaded_agents = _load_population_if_present(args.population_state, expected_agents=args.agents)
    harness = ColonyHarness(
        population_size=args.agents or configured_agents,
        speaker_slots=room_budget,
        seed=args.seed if args.seed is not None else int(population.get("seed", 42)),
        voice_model=voice_model,
        create_agent_wallets=args.agent_wallets,
        wallet_store_path=args.wallet_store if args.agent_wallets else None,
        agents=loaded_agents,
    )
    _apply_verified_roots(args, harness)
    ens_parent = _resolve_ens_parent(args)
    assign_ens_names(harness.agents, ens_parent=ens_parent)

    match = MatchContext.from_dict(config)
    result = harness.run_round(match)
    saved_population_path = _save_population_if_requested(args.population_state, harness, note=f"after {result.round_id}")
    identity_path = _write_identity_if_requested(args, harness)
    run_dir = None
    if not args.no_run_log:
        run_dir = create_run_dir(args.runs_dir, result.round_id)
        write_compact_run_artifacts(run_dir=run_dir, match=match, result=result, debug=args.debug)

    print(f"Colony round: {result.round_id}")
    print(f"Match: {match.home_team} vs {match.away_team}")
    print(f"Population: {result.summary['population']} predictors")
    if args.population_state:
        status = "loaded" if loaded_agents is not None else "created"
        print(f"Population state: {status} {saved_population_path or args.population_state}")
    if identity_path is not None:
        print(f"ENS identity records: {identity_path}")
    print(
        "Debate structure: "
        f"room_budget={result.summary['speaker_slots']} "
        f"rooms={result.summary['room_count']} "
        f"room_claims={result.summary['room_claims']} "
        f"final_claims={result.summary['final_claims']}"
    )
    print_debate_quality(result)
    print(
        "Findings: "
        f"public={result.summary['public_findings']} "
        f"shared={result.summary['shared_findings']} "
        f"private={result.summary['private_findings']}"
    )
    print(
        "Knowledge views: "
        f"public={result.summary['public_views']} "
        f"shared={result.summary['shared_views']} "
        f"private={result.summary['private_views']}"
    )
    print(f"Market home probability: {result.summary['market_home_probability']:.1%}")
    print(f"Debate home probability: {result.summary['debate_home_probability']:.1%}")
    print(
        "Bets: "
        f"home={result.summary['home_bets']} "
        f"away={result.summary['away_bets']} "
        f"pass={result.summary['passes']} "
        f"total_staked={result.summary['total_staked']}"
    )

    if args.debug:
        print_room_debug(result)
    print_final_feed(result)

    if args.show_roster:
        print("\nPublic roster:")
        for record in harness.public_roster():
            print(json.dumps(record, sort_keys=True))

    if args.out:
        harness.write_jsonl(result, args.out)
        print(f"\nWrote JSONL events to {args.out}")

    if run_dir is not None:
        print(f"\nSaved compact run logs to {run_dir}")


def _load_population_if_present(path: str | None, *, expected_agents: int | None) -> list | None:
    if not path:
        return None
    state_path = Path(path)
    if not state_path.exists():
        return None
    agents = load_population_state(state_path)
    if expected_agents is not None and expected_agents != len(agents):
        raise SystemExit(
            f"Population state contains {len(agents)} agents, but --agents requested {expected_agents}. "
            "Omit --agents or use a matching value."
        )
    return agents


def _resolve_room_budget(*, rooms: int | None, speakers: int | None, default: int) -> int:
    if rooms is not None and speakers is not None and rooms != speakers:
        raise SystemExit("--rooms and --speakers were both provided with different values. Use --rooms.")
    value = rooms if rooms is not None else speakers
    if value is None:
        value = default
    if value < 1:
        raise SystemExit("--rooms must be positive")
    return value


def _save_population_if_requested(path: str | None, harness: ColonyHarness, *, note: str) -> Path | None:
    if not path:
        return None
    return save_population_state(path, harness.agents, seed=harness.seed, note=note)


def _write_identity_if_requested(args: argparse.Namespace, harness: ColonyHarness) -> Path | None:
    if not args.identity_out:
        return None
    return write_identity_records(
        args.identity_out,
        harness.agents,
        ens_parent=_resolve_ens_parent(args),
        profile_base_url=args.profile_base_url,
    )


def _resolve_ens_parent(args: argparse.Namespace) -> str:
    return args.ens_parent or os.environ.get("COLONY_ENS_PARENT") or "colonny.eth"


def _apply_verified_roots(args: argparse.Namespace, harness: ColonyHarness) -> None:
    if not args.verified_root:
        return
    for wanted in args.verified_root:
        normalized = wanted.lower()
        agent = next(
            (
                candidate
                for candidate in harness.agents
                if candidate.agent_id.lower() == normalized
                or (candidate.wallet_address and candidate.wallet_address.lower() == normalized)
            ),
            None,
        )
        if agent is None:
            raise SystemExit(f"--verified-root did not match any agent_id or wallet address: {wanted}")
        agent.verified_lineage = True
        if args.world_human_id:
            agent.world_human_id = args.world_human_id
    normalize_agent_lineages(harness.agents)


if __name__ == "__main__":
    main()
