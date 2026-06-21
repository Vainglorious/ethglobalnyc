#!/usr/bin/env python3
"""Run a local Colony debate harness round."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from colony_harness import ColonyHarness
from colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
from colony_harness.colony_config import ant_count_from_config, describe_colony_config, load_colony_config
from colony_harness.console import print_debate_quality, print_final_feed, print_room_debug
from colony_harness.env import load_env_file
from colony_harness.identity import assign_ens_names, write_identity_records
from colony_harness.models import MatchContext
from colony_harness.population import load_population_state, normalize_agent_lineages, save_population_state
from colony_harness.voice import TemplateVoiceModel, llm_voice_model_from_env
from colony_harness.world import DEFAULT_WORLD_VERIFICATION_STORE, apply_world_verifications


DEFAULT_CONFIG = Path(__file__).parent / "config" / "example.colony.json"


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Colony debate harness.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to a colony config JSON file.")
    parser.add_argument(
        "--colony-config",
        default=None,
        help="Path to a user colony config JSON file, typically from Supabase colonies.config.",
    )
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
    parser.add_argument("--match", default=None, help="Override match label, for example 'Brazil vs Morocco'.")
    parser.add_argument("--match-id", default=None, help="Override round/match id written into run artifacts.")
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
        help="Create/reuse EVM wallets for agents and expose only public addresses.",
    )
    parser.add_argument(
        "--wallet-provider",
        choices=["local", "dynamic"],
        default=None,
        help="Wallet backend for --agent-wallets. Defaults to COLONY_WALLET_PROVIDER or local.",
    )
    parser.add_argument(
        "--wallet-store",
        default="colony/secrets/agent-wallets.local.json",
        help="Gitignored JSON store for agent wallet records.",
    )
    parser.add_argument(
        "--dynamic-env",
        default=None,
        help="Optional Dynamic .env path for --wallet-provider dynamic. Defaults to COLONY_DYNAMIC_ENV or dynamic/.env.",
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
        "--deployment-id",
        default=None,
        help="Deployment/run id written into ENS identity records. Defaults to COLONY_DEPLOYMENT_ID.",
    )
    parser.add_argument(
        "--world-agent",
        action="append",
        default=[],
        help="Require this ant to have a Worldcoin AgentKit receipt and premium World access. Can be repeated.",
    )
    parser.add_argument(
        "--verified-root",
        action="append",
        default=[],
        help="Deprecated alias for --world-agent.",
    )
    parser.add_argument(
        "--world-verified-root",
        action="append",
        default=[],
        help="Deprecated alias for --world-agent.",
    )
    parser.add_argument(
        "--world-verifications",
        default=None,
        help="Gitignored local Worldcoin AgentKit receipt store.",
    )
    parser.add_argument(
        "--allow-manual-world-agent",
        action="store_true",
        help="Local testing escape hatch: allow --world-agent without a stored AgentKit receipt.",
    )
    parser.add_argument(
        "--allow-manual-verified-root",
        action="store_true",
        help="Deprecated alias for --allow-manual-world-agent.",
    )
    parser.add_argument(
        "--world-human-id",
        default="",
        help="Optional pseudonymous World ID identifier to attach to verified World agents.",
    )
    parser.add_argument(
        "--profile-base-url",
        default=None,
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


def _parse_match_label(label: str) -> tuple[str, str]:
    normalized = " ".join(label.replace(" v ", " vs ").split())
    marker = " vs "
    if marker in normalized:
        home, away = normalized.split(marker, 1)
        return home.strip() or "Home", away.strip() or "Away"
    return normalized.strip() or "Home", "Away"


def _apply_match_override(config: dict, *, match: str | None, match_id: str | None) -> dict:
    if not match and not match_id:
        return config
    updated = json.loads(json.dumps(config))
    updated_match = dict(updated.get("match") or {})
    if match:
        home, away = _parse_match_label(match)
        updated_match["home_team"] = home
        updated_match["away_team"] = away
    if match_id:
        updated["round_id"] = match_id
    updated["match"] = updated_match
    return updated


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    colony_config = load_colony_config(args.colony_config)
    config = _apply_match_override(
        load_config(Path(args.config)),
        match=args.match,
        match_id=args.match_id,
    )
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
    population_size = args.agents or ant_count_from_config(colony_config, configured_agents)
    room_budget = _resolve_room_budget(
        rooms=args.rooms,
        speakers=args.speakers,
        default=int(population.get("speaker_slots", 6)),
    )
    expected_agents = population_size if colony_config is not None or args.agents is not None else None
    loaded_agents = _load_population_if_present(args.population_state, expected_agents=expected_agents)
    harness = ColonyHarness(
        population_size=population_size,
        speaker_slots=room_budget,
        seed=args.seed if args.seed is not None else int(population.get("seed", 42)),
        voice_model=voice_model,
        create_agent_wallets=args.agent_wallets,
        wallet_store_path=args.wallet_store if args.agent_wallets else None,
        wallet_provider=args.wallet_provider,
        dynamic_env_path=args.dynamic_env,
        agents=loaded_agents,
        colony_config=colony_config,
    )
    _apply_world_agents(args, harness)
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
    if colony_config is not None:
        note = " (loaded population state genomes preserved)" if loaded_agents is not None else ""
        print(f"Colony config: {describe_colony_config(colony_config)}{note}")
    print(f"Population: {result.summary['population']} predictors")
    if args.population_state:
        status = "loaded" if loaded_agents is not None else "created"
        print(f"Population state: {status} {saved_population_path or args.population_state}")
    if identity_path is not None:
        print(f"ENS identity records: {identity_path}")
    print(_identity_summary(harness))
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
    print(f"Risk profiles: {_risk_profile_summary(result.summary.get('risk_profiles', {}))}")
    print(f"Market anchor: {_lean_label(result.summary['market_home_probability'])}")
    print(f"Debate lean: {_lean_label(result.summary['debate_home_probability'])}")
    print(
        "Bets: "
        f"home={result.summary['home_bets']} "
        f"draw={result.summary.get('draw_bets', 0)} "
        f"away={result.summary['away_bets']} "
        f"participation={result.summary.get('participating_bets', 0)}/{result.summary['population']} "
        f"total_staked={result.summary['total_staked']}"
    )
    decision = result.collective_decision
    print(
        "Decision: "
        f"{decision.prediction['sentence']} "
        f"bet={decision.recommendation['side']} "
        f"value={decision.prediction['value']}"
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
        profile_base_url=_resolve_profile_base_url(args),
        deployment_id=_resolve_deployment_id(args),
    )


def _resolve_ens_parent(args: argparse.Namespace) -> str:
    return args.ens_parent or os.environ.get("COLONY_ENS_PARENT") or "colonny.eth"


def _resolve_profile_base_url(args: argparse.Namespace) -> str:
    return args.profile_base_url or os.environ.get("COLONY_PROFILE_BASE_URL") or "https://colony.app/ants"


def _resolve_deployment_id(args: argparse.Namespace) -> str:
    return args.deployment_id or os.environ.get("COLONY_DEPLOYMENT_ID") or ""


def _identity_summary(harness: ColonyHarness) -> str:
    wallets = sum(1 for agent in harness.agents if agent.wallet_address)
    ens_names = sum(1 for agent in harness.agents if agent.ens_name)
    world_verified = sum(1 for agent in harness.agents if agent.world_verified)
    return f"Agent identities: wallets={wallets} ens={ens_names} world_verified={world_verified}"


def _apply_world_agents(args: argparse.Namespace, harness: ColonyHarness) -> None:
    required_agents = list(args.world_agent or []) + list(args.verified_root or []) + list(args.world_verified_root or [])
    try:
        apply_world_verifications(
            harness.agents,
            store_path=_resolve_world_verifications(args),
            required_agents=required_agents,
            allow_manual=bool(args.allow_manual_world_agent or args.allow_manual_verified_root),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.world_human_id:
        for agent in harness.agents:
            if agent.world_verified and not agent.world_human_id:
                agent.world_human_id = args.world_human_id
    normalize_agent_lineages(harness.agents)


def _resolve_world_verifications(args: argparse.Namespace) -> str:
    return args.world_verifications or os.environ.get("COLONY_WORLD_VERIFICATIONS") or str(DEFAULT_WORLD_VERIFICATION_STORE)


def _lean_label(value: float | None) -> str:
    if value is None:
        return "unclear"
    if value >= 0.515:
        return "leans_home"
    if value <= 0.485:
        return "leans_away"
    return "contested"


def _risk_profile_summary(profiles: dict) -> str:
    if not profiles:
        return "n/a"
    return " ".join(f"{key}={profiles.get(key, 0)}" for key in ("secure", "balanced", "risky"))


if __name__ == "__main__":
    main()
