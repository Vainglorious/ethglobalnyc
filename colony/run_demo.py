#!/usr/bin/env python3
"""Run a local Colony debate harness demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from colony_harness import ColonyHarness
from colony_harness.artifacts import create_run_dir, write_compact_run_artifacts
from colony_harness.env import load_env_file
from colony_harness.models import MatchContext
from colony_harness.voice import TemplateVoiceModel, llm_voice_model_from_env


DEFAULT_CONFIG = Path(__file__).parent / "config" / "example.colony.json"


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Colony debate harness.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to a colony config JSON file.")
    parser.add_argument("--agents", type=int, default=None, help="Override population size.")
    parser.add_argument("--speakers", type=int, default=None, help="Override number of public debaters.")
    parser.add_argument("--seed", type=int, default=None, help="Override RNG seed.")
    parser.add_argument("--out", default=None, help="Optional JSONL output path.")
    parser.add_argument("--runs-dir", default="colony/runs", help="Directory for automatic compact run logs.")
    parser.add_argument("--no-run-log", action="store_true", help="Disable automatic compact run logs.")
    parser.add_argument("--debug", action="store_true", help="Write an additional human-readable debug.md report.")
    parser.add_argument("--show-roster", action="store_true", help="Print public predictor records.")
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

    harness = ColonyHarness(
        population_size=args.agents or int(population.get("agents", 40)),
        speaker_slots=args.speakers or int(population.get("speaker_slots", 6)),
        seed=args.seed if args.seed is not None else int(population.get("seed", 42)),
        voice_model=voice_model,
    )

    match = MatchContext.from_dict(config)
    result = harness.run_round(match)
    run_dir = None
    if not args.no_run_log:
        run_dir = create_run_dir(args.runs_dir, result.round_id)
        write_compact_run_artifacts(run_dir=run_dir, match=match, result=result, debug=args.debug)

    print(f"Colony round: {result.round_id}")
    print(f"Match: {match.home_team} vs {match.away_team}")
    print(f"Population: {result.summary['population']} predictors")
    print(
        "Debate structure: "
        f"rooms={result.summary['room_count']} "
        f"room_claims={result.summary['room_claims']} "
        f"final_claims={result.summary['final_claims']}"
    )
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

    if args.show_roster:
        print("\nPublic roster:")
        for record in harness.public_roster():
            print(json.dumps(record, sort_keys=True))

    if args.out:
        harness.write_jsonl(result, args.out)
        print(f"\nWrote JSONL events to {args.out}")

    if run_dir is not None:
        print(f"\nSaved compact run logs to {run_dir}")


if __name__ == "__main__":
    main()
