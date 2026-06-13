#!/usr/bin/env python3
"""Build the World Cup tournament knowledge graph."""

from __future__ import annotations

import argparse
from pathlib import Path

from colony_harness.tournament_graph import (
    OPENFOOTBALL_2026_URL,
    build_tournament_graph,
    graph_summary,
    load_openfootball_schedule,
    matches_for_teams,
    write_graph,
    write_summary,
)


DEFAULT_CACHE = Path(__file__).parent / "data" / "openfootball" / "worldcup_2026.json"
DEFAULT_OUT = Path(__file__).parent / "data" / "world_cup_kg.json"
DEFAULT_SUMMARY = Path(__file__).parent / "data" / "world_cup_kg.summary.md"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the World Cup 2026 tournament KG.")
    parser.add_argument("--source-url", default=OPENFOOTBALL_2026_URL, help="OpenFootball JSON source URL.")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE), help="Local cache path for the source JSON.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output path for the tournament KG JSON.")
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY), help="Output path for a readable summary.")
    parser.add_argument("--force-refresh", action="store_true", help="Fetch source JSON even if the cache exists.")
    parser.add_argument("--offline-sample", action="store_true", help="Use a tiny built-in sample instead of fetching.")
    parser.add_argument("--team", action="append", default=[], help="Team to highlight in the summary. Repeatable.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    schedule = load_openfootball_schedule(
        source_url=args.source_url,
        cache_path=args.cache,
        force_refresh=args.force_refresh,
        offline_sample=args.offline_sample,
    )
    graph = build_tournament_graph(schedule)
    focused_matches = matches_for_teams(graph, set(args.team)) if args.team else None

    graph_path = write_graph(args.out, graph)
    summary_path = write_summary(args.summary, graph, focused_matches=focused_matches)
    summary = graph_summary(graph)

    print(f"Built KG: {summary['graph_id']}")
    print(f"Entities: {summary['entities']}")
    print(f"Relationships: {summary['relationships']}")
    print(f"Wrote graph to {graph_path}")
    print(f"Wrote summary to {summary_path}")
    if focused_matches is not None:
        print(f"Focused matches: {len(focused_matches)}")


if __name__ == "__main__":
    main()
