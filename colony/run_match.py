#!/usr/bin/env python3
"""Run one match from the World Cup KG with optional public, X, and CAMEL scouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from colony_harness import ColonyHarness
from colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
from colony_harness.env import load_env_file
from colony_harness.live_scouts import public_match_context_from_tournament_match
from colony_harness.scouts import mock_match_context_from_tournament_match
from colony_harness.voice import TemplateVoiceModel, llm_voice_model_from_env


DEFAULT_KG = Path(__file__).parent / "data" / "world_cup_kg.json"
DEFAULT_LIVE_CACHE = Path(__file__).parent / "data" / "live_scouts"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Colony round from a World Cup KG match.")
    parser.add_argument("--kg", default=str(DEFAULT_KG), help="Path to the built World Cup KG JSON.")
    parser.add_argument("--match-id", default=None, help="Exact KG match entity id.")
    parser.add_argument("--match", default="Brazil vs Morocco", help='Match name, e.g. "Brazil vs Morocco".')
    parser.add_argument(
        "--data-mode",
        choices=["synthetic", "public"],
        default="synthetic",
        help="Use deterministic placeholders or fetch public non-social data.",
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
        "--include-camel",
        action="store_true",
        help="Add the optional CAMEL/deep-research scout to public data mode.",
    )
    parser.add_argument(
        "--include-x",
        action="store_true",
        help="Add the optional X availability scout to public data mode.",
    )
    parser.add_argument("--agents", type=int, default=40, help="Population size.")
    parser.add_argument("--speakers", type=int, default=6, help="Number of public debaters.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed.")
    parser.add_argument("--runs-dir", default="colony/runs", help="Directory for automatic compact run logs.")
    parser.add_argument("--no-run-log", action="store_true", help="Disable automatic compact run logs.")
    parser.add_argument("--debug", action="store_true", help="Write an additional human-readable debug.md report.")
    parser.add_argument(
        "--voice-mode",
        choices=["template", "llm"],
        default="template",
        help="Use deterministic templates or an OpenAI-compatible LLM for debate messages.",
    )
    parser.add_argument("--env", default="colony/.env", help="Optional .env path for LLM settings.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    graph = _load_graph(Path(args.kg))
    match_entity = _select_match(graph, match_id=args.match_id, match_name=args.match)
    if args.data_mode == "public":
        match = public_match_context_from_tournament_match(
            match_entity,
            cache_dir=args.live_cache_dir,
            refresh=args.refresh_data,
            include_x=args.include_x,
            include_camel=args.include_camel,
        )
    else:
        match = mock_match_context_from_tournament_match(match_entity)

    voice_model = llm_voice_model_from_env() if args.voice_mode == "llm" else TemplateVoiceModel()
    harness = ColonyHarness(
        population_size=args.agents,
        speaker_slots=args.speakers,
        seed=args.seed,
        voice_model=voice_model,
    )
    result = harness.run_round(match)

    run_dir = None
    if not args.no_run_log:
        run_dir = create_run_dir(args.runs_dir, result.round_id)
        write_compact_run_artifacts(run_dir=run_dir, match=match, result=result, debug=args.debug)

    attrs = match_entity["attributes"]
    print(f"Colony round: {result.round_id}")
    print(f"KG match id: {match_entity['entity_id']}")
    print(f"Match: {match.home_team} vs {match.away_team}")
    print(f"Schedule: {attrs.get('date')} {attrs.get('time')} | {attrs.get('group')} | {attrs.get('ground')}")
    print(f"Data mode: {args.data_mode}")
    print(f"Optional scouts: x={'enabled' if args.include_x else 'disabled'} camel={'enabled' if args.include_camel else 'disabled'}")
    print(f"Population: {result.summary['population']} predictors")
    print(f"Debaters: {result.summary['speaker_slots']}")
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
    print("\nDebate feed:")
    for claim in result.claims:
        tags = ", ".join(claim.evidence_tags) if claim.evidence_tags else "no dominant source"
        print(f"- [{claim.model} | {claim.access_tier}/{claim.visible_findings} | {claim.claim_type} | {tags}] {claim.message}")
    if run_dir is not None:
        print(f"\nSaved compact run logs to {run_dir}")


def _load_graph(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"KG not found at {path}. Run: python3 colony/build_kg.py --force-refresh")
    return json.loads(path.read_text(encoding="utf-8"))


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
