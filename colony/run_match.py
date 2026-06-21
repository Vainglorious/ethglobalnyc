#!/usr/bin/env python3
"""Run one match from the World Cup KG with optional public, X, and CAMEL scouts."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from colony_harness import ColonyHarness
from colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
from colony_harness.colony_config import ant_count_from_config, describe_colony_config, load_colony_config
from colony_harness.console import print_debate_quality, print_final_feed, print_room_debug
from colony_harness.env import load_env_file
from colony_harness.identity import assign_ens_names, write_identity_records
from colony_harness.live_scouts import public_match_context_from_tournament_match
from colony_harness.models import Finding
from colony_harness.population import load_population_state, normalize_agent_lineages, save_population_state
from colony_harness.scouts import (
    mock_match_context_from_tournament_match,
    openfootball_match_context_from_tournament_match,
)
from colony_harness.tournament_graph import build_tournament_graph, load_openfootball_schedule
from colony_harness.voice import TemplateVoiceModel, llm_voice_model_from_env
from colony_harness.world import DEFAULT_WORLD_VERIFICATION_STORE, apply_world_verifications


DEFAULT_KG = Path(__file__).parent / "data" / "world_cup_kg.json"
DEFAULT_LIVE_CACHE = Path(__file__).parent / "data" / "live_scouts"
DEFAULT_OPENFOOTBALL_CACHE = Path(__file__).parent / "data" / "openfootball" / "worldcup_2026.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Colony round from a World Cup KG match.")
    parser.add_argument("--kg", default=str(DEFAULT_KG), help="Path to the built World Cup KG JSON.")
    parser.add_argument("--match-id", default=None, help="Exact KG match entity id.")
    parser.add_argument("--match", default="Brazil vs Morocco", help='Match name, e.g. "Brazil vs Morocco".')
    parser.add_argument(
        "--data-mode",
        choices=["synthetic", "public", "openfootball"],
        default="synthetic",
        help="Use deterministic synthetic fixtures, public non-social data, or one fast OpenFootball fixture scout.",
    )
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Refetch public data instead of using the local scout cache.",
    )
    parser.add_argument(
        "--live-cache-dir",
        default=str(DEFAULT_LIVE_CACHE),
        help="Cache directory for public-data scout fetches.",
    )
    parser.add_argument(
        "--openfootball-cache",
        default=str(DEFAULT_OPENFOOTBALL_CACHE),
        help="Cache path for the raw openfootball/worldcup.json schedule.",
    )
    parser.add_argument(
        "--include-camel",
        action="store_true",
        help="Add the optional CAMEL/deep-research scout to public data mode.",
    )
    parser.add_argument(
        "--include-x",
        action="store_true",
        help="Add the optional X availability scout to public data mode.",
    )
    parser.add_argument(
        "--include-telegram",
        action="store_true",
        help="Add the optional Telegram social/news scout to public data mode.",
    )
    parser.add_argument(
        "--include-polygun",
        action="store_true",
        help="Add the optional read-only PolyGun match-market snapshot scout to public data mode.",
    )
    parser.add_argument(
        "--include-deepseek-scout",
        action="store_true",
        help="Add the optional DeepSeek/OpenRouter structured scouting agent to public data mode.",
    )
    parser.add_argument(
        "--scout-focus",
        action="append",
        default=[],
        metavar="TEAM:CLAIM_TYPE",
        help="Add a focused public re-scout target such as 'Morocco:match_history'. Can be repeated.",
    )
    parser.add_argument(
        "--rescout-from-audit",
        default=None,
        help="Read scouting_audit.json and add focused public re-scout targets from its scouting_backlog.",
    )
    parser.add_argument("--agents", type=int, default=None, help="Population size.")
    parser.add_argument(
        "--colony-config",
        default=None,
        help="Path to a user colony config JSON file, typically from Supabase colonies.config.",
    )
    parser.add_argument(
        "--rooms",
        type=int,
        default=None,
        help="Maximum number of topic rooms. Preferred name for new runs.",
    )
    parser.add_argument(
        "--speakers",
        type=int,
        default=None,
        help="Deprecated alias for --rooms, kept for older commands.",
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed.")
    parser.add_argument(
        "--population-state",
        default=None,
        help="Load an existing population state or create/save one at this path.",
    )
    parser.add_argument("--runs-dir", default="colony/runs", help="Directory for automatic compact run logs.")
    parser.add_argument("--no-run-log", action="store_true", help="Disable automatic compact run logs.")
    parser.add_argument("--debug", action="store_true", help="Write an additional human-readable debug.md report.")
    parser.add_argument(
        "--market-home-probability",
        type=float,
        default=None,
        help="Override the binary home-vs-away market anchor used by the debate model.",
    )
    parser.add_argument(
        "--market-side-probabilities-json",
        default="",
        help='Optional raw 1X2 market probabilities JSON, e.g. {"home":0.15,"draw":0.23,"away":0.62}.',
    )
    parser.add_argument("--market-source", default="", help="Human-readable source label for market override.")
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
    return parser.parse_args()


def _clamp_probability(value: float) -> float:
    return max(0.01, min(0.99, float(value)))


def _parse_market_side_probabilities(raw: str) -> dict[str, float]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--market-side-probabilities-json is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--market-side-probabilities-json must be a JSON object")
    probabilities: dict[str, float] = {}
    for side in ("home", "draw", "away"):
        if side not in payload or payload[side] is None:
            continue
        try:
            probabilities[side] = _clamp_probability(float(payload[side]))
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"Market probability for {side} must be numeric") from exc
    return probabilities


def _market_override_home_anchor(args: argparse.Namespace, side_probabilities: dict[str, float]) -> float | None:
    if args.market_home_probability is not None:
        return _clamp_probability(float(args.market_home_probability))
    home = side_probabilities.get("home")
    away = side_probabilities.get("away")
    if home is None or away is None:
        return None
    denominator = home + away
    if denominator <= 0:
        return None
    return _clamp_probability(home / denominator)


def _apply_market_override(match, args: argparse.Namespace):
    side_probabilities = _parse_market_side_probabilities(args.market_side_probabilities_json)
    anchor = _market_override_home_anchor(args, side_probabilities)
    if anchor is None:
        return match

    source = args.market_source or "market override"
    summary = (
        f"{source} sets binary market anchor for {match.home_team} vs {match.away_team} "
        f"to {anchor:.3f}."
    )
    if side_probabilities:
        labels = {
            "home": match.home_team,
            "draw": "Draw",
            "away": match.away_team,
        }
        market_line = ", ".join(
            f"{labels[side]}={side_probabilities[side]:.3f}"
            for side in ("home", "draw", "away")
            if side in side_probabilities
        )
        summary = f"{summary} Raw 1X2 market: {market_line}."

    metrics = {
        "binary_home_probability": anchor,
        "source": source,
    }
    for side in ("home", "draw", "away"):
        if side in side_probabilities:
            metrics[f"market_{side}_probability"] = side_probabilities[side]

    finding = Finding(
        finding_id=f"{match.round_id}:market_anchor_override",
        scout_name="market_anchor_override",
        access_level="public",
        source_type="market",
        finding_name="market_anchor_override",
        home_probability=anchor,
        home_delta=round(anchor - match.market_home_probability, 4),
        confidence=0.9,
        cost=0.0,
        citations=[],
        summary=summary,
        evidence_claims=[
            {
                "claim": summary,
                "claim_type": "market_anchor",
                "confidence": 0.9,
                "extraction_method": "kg_polymarket_override",
                "impact": "market_anchor",
                "metrics": metrics,
                "source_kind": "market_snapshot",
                "source_quality": "strong",
                "source_title": source,
                "subject": f"{match.home_team} vs {match.away_team}",
                "team": "",
            }
        ],
    )
    return replace(
        match,
        market_home_probability=anchor,
        odds_home_signal=anchor,
        findings=[finding, *list(match.findings)],
    )


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    colony_config = load_colony_config(args.colony_config)
    graph = _load_openfootball_graph(args) if args.data_mode == "openfootball" else _load_graph(Path(args.kg))
    match_entity = _select_match(graph, match_id=args.match_id, match_name=args.match)
    if args.data_mode == "public":
        rescout_targets = _rescout_targets_from_args(args)
        match = public_match_context_from_tournament_match(
            match_entity,
            cache_dir=args.live_cache_dir,
            refresh=args.refresh_data,
            include_x=args.include_x,
            include_camel=args.include_camel,
            include_telegram=args.include_telegram,
            include_polygun=args.include_polygun,
            include_deepseek_scout=args.include_deepseek_scout,
            rescout_targets=rescout_targets,
        )
    elif args.data_mode == "openfootball":
        rescout_targets = []
        match = openfootball_match_context_from_tournament_match(match_entity)
    else:
        rescout_targets = []
        match = mock_match_context_from_tournament_match(match_entity)

    match = _apply_market_override(match, args)
    voice_model = llm_voice_model_from_env() if args.voice_mode == "llm" else TemplateVoiceModel()
    room_budget = _resolve_room_budget(rooms=args.rooms, speakers=args.speakers, default=6)
    population_size = args.agents or ant_count_from_config(colony_config, 40)
    expected_agents = population_size if colony_config is not None or args.agents is not None else None
    loaded_agents = _load_population_if_present(args.population_state, expected_agents=expected_agents)
    harness = ColonyHarness(
        population_size=population_size,
        speaker_slots=room_budget,
        seed=args.seed,
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
    result = harness.run_round(match)
    saved_population_path = _save_population_if_requested(args.population_state, harness, note=f"after {result.round_id}")
    identity_path = _write_identity_if_requested(args, harness)

    run_dir = None
    if not args.no_run_log:
        run_dir = create_run_dir(args.runs_dir, result.round_id)
        write_compact_run_artifacts(run_dir=run_dir, match=match, result=result, debug=args.debug)

    attrs = match_entity["attributes"]
    print(f"Colony round: {result.round_id}")
    print(f"KG match id: {match_entity['entity_id']}")
    print(f"Match: {match.home_team} vs {match.away_team}")
    print(f"Schedule: {attrs.get('date')} {attrs.get('time')} | {attrs.get('group')} | {attrs.get('ground')}")
    if args.market_home_probability is not None or args.market_side_probabilities_json:
        side_probabilities = _parse_market_side_probabilities(args.market_side_probabilities_json)
        side_labels = {
            "home": match.home_team,
            "draw": "Draw",
            "away": match.away_team,
        }
        raw_market = " | ".join(
            f"{side_labels[side]}={side_probabilities[side]:.1%}"
            for side in ("home", "draw", "away")
            if side in side_probabilities
        )
        raw_suffix = f" | 1X2 {raw_market}" if raw_market else ""
        print(
            "Market override: "
            f"{args.market_source or 'market override'} | "
            f"{match.home_team} vs {match.away_team} anchor={match.market_home_probability:.1%}"
            f"{raw_suffix}"
        )

    print(f"Data mode: {args.data_mode}")
    if args.data_mode == "openfootball":
        print(f"OpenFootball scout: cache={args.openfootball_cache} refresh={'yes' if args.refresh_data else 'no'}")
    else:
        print(
            "Optional scouts: "
            f"x={'enabled' if args.include_x else 'disabled'} "
            f"camel={'enabled' if args.include_camel else 'disabled'} "
            f"telegram={'enabled' if args.include_telegram else 'disabled'} "
            f"polygun={'enabled' if args.include_polygun else 'disabled'} "
            f"deepseek={'enabled' if args.include_deepseek_scout else 'disabled'}"
        )
    if rescout_targets:
        print(
            "Focused re-scout targets: "
            + ", ".join(f"{target.get('team')}:{target.get('claim_type')}" for target in rescout_targets)
        )
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


def _rescout_targets_from_args(args: argparse.Namespace) -> list[dict]:
    targets: list[dict] = []
    if args.rescout_from_audit:
        audit_path = Path(args.rescout_from_audit)
        if not audit_path.exists():
            raise SystemExit(f"Scouting audit not found: {audit_path}")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        for item in audit.get("scouting_backlog", {}).get("items", []):
            if item.get("status") not in {"needs_rescout", "needs_fresh_rescout"}:
                continue
            team = str(item.get("team") or "").strip()
            claim_type = str(item.get("claim_type") or "").strip()
            if team and claim_type:
                targets.append(
                    {
                        "team": team,
                        "claim_type": claim_type,
                        "source": str(audit_path),
                        "target_entity_id": str(item.get("target_entity_id") or ""),
                        "status": str(item.get("status") or ""),
                        "quality_status": str(item.get("quality_status") or ""),
                        "quality_reasons": list(item.get("quality_reasons") or []),
                    }
                )
    for spec in args.scout_focus or []:
        if ":" in spec:
            team, claim_type = spec.split(":", 1)
        elif "=" in spec:
            team, claim_type = spec.split("=", 1)
        else:
            raise SystemExit("--scout-focus must be shaped as TEAM:CLAIM_TYPE")
        team = team.strip()
        claim_type = claim_type.strip()
        if not team or not claim_type:
            raise SystemExit("--scout-focus must include both team and claim type")
        targets.append({"team": team, "claim_type": claim_type, "source": "cli"})

    deduped: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        key = (str(target.get("team") or "").casefold(), str(target.get("claim_type") or "").casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


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


def _load_graph(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"KG not found at {path}. Run: python3 colony/build_kg.py --force-refresh")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_openfootball_graph(args: argparse.Namespace) -> dict:
    schedule = load_openfootball_schedule(
        cache_path=Path(args.openfootball_cache),
        force_refresh=args.refresh_data,
    )
    return build_tournament_graph(schedule).to_dict()


def _select_match(graph: dict, *, match_id: str | None, match_name: str) -> dict:
    matches = [entity for entity in graph["entities"] if entity["entity_type"] == "match"]
    if match_id is not None:
        for match in matches:
            if match["entity_id"] == match_id:
                return match
        raise SystemExit(f"Match id not found: {match_id}")

    wanted = " ".join(match_name.lower().replace("-", " ").split())
    for match in matches:
        name = " ".join(str(match["name"]).lower().replace("-", " ").split())
        if name == wanted:
            return match
    raise SystemExit(f"Match not found: {match_name}")


if __name__ == "__main__":
    main()
