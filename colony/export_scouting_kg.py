#!/usr/bin/env python3
"""Validate and export a scouting KG ingestion bundle from a run directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from colony_harness.kg_ingestion import KGIngestionError, load_scouting_kg_bundle


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a scouting run and export KG ingestion entrypoints.")
    parser.add_argument("run_dir", help="Run directory containing kg_manifest.json and world_graph.json.")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail unless both kg_load_ready and scouting_complete are true.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for the ingestion bundle JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        bundle = load_scouting_kg_bundle(args.run_dir, require_complete=args.require_complete)
    except KGIngestionError as exc:
        raise SystemExit(f"KG ingestion validation failed: {exc}") from exc

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"Wrote scouting KG ingestion bundle to {out_path}")

    validation = bundle["validation"]
    readiness = bundle["readiness"]
    print(f"KG status: {validation['status']}")
    print(f"KG load ready: {validation['kg_load_ready']}")
    print(f"Scouting complete: {validation['scouting_complete']}")
    print(f"Entities: {validation['entity_count']}")
    print(f"Relationships: {validation['relationship_count']}")
    print(f"Entrypoints: {', '.join(validation['entrypoint_entity_types'])}")
    if readiness.get("scouting_backlog_count"):
        print(f"Scouting backlog: {readiness['scouting_backlog_count']}")


if __name__ == "__main__":
    main()
