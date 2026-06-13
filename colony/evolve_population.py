#!/usr/bin/env python3
"""Evolve a Colony population state from recent conversation memory."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from analyze_memory import analyze_memory_files
from colony_harness.agent import AntAgent
from colony_harness.genes import mutate_genome
from colony_harness.population import agent_to_state, load_population_state


DEFAULT_RUNS_DIR = Path("colony/runs")


def _find_memory_files(runs_dir: Path, latest: int | None) -> list[Path]:
    files = sorted(
        runs_dir.glob("*/conversation_memory.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if latest is not None:
        files = files[:latest]
    return list(reversed(files))


def _genome_scores(analysis: dict[str, Any]) -> dict[str, float]:
    return {
        str(row["key"]): float(row["usefulness_score"])
        for row in analysis.get("genomes") or []
        if row.get("key")
    }


def _agent_fitness(agent: AntAgent, genome_scores: dict[str, float]) -> float:
    memory_score = genome_scores.get(agent.genome_id, 0.0)
    bankroll_score = max(agent.bankroll, 0.0) / 100.0
    accuracy_score = agent.accuracy
    return round(memory_score * 1.8 + bankroll_score * 0.4 + accuracy_score * 0.8, 6)


def evolve_population(
    agents: list[AntAgent],
    *,
    genome_scores: dict[str, float],
    survival_rate: float,
    mutation_rate: float,
    seed: int,
) -> tuple[list[AntAgent], dict[str, Any]]:
    if not 0.0 < survival_rate <= 1.0:
        raise ValueError("survival_rate must be in (0, 1]")
    if not 0.0 <= mutation_rate <= 1.0:
        raise ValueError("mutation_rate must be in [0, 1]")

    rng = random.Random(seed)
    ranked = sorted(
        agents,
        key=lambda agent: (_agent_fitness(agent, genome_scores), agent.accuracy, agent.bankroll),
        reverse=True,
    )
    survivor_count = max(1, min(len(agents), round(len(agents) * survival_rate)))
    survivors = ranked[:survivor_count]
    survivor_ids = {agent.agent_id for agent in survivors}
    survivor_cycle = list(survivors)
    children_by_slot: dict[str, tuple[AntAgent, AntAgent]] = {}

    child_index = 0
    for slot in agents:
        if slot.agent_id in survivor_ids:
            continue
        parent = survivor_cycle[child_index % len(survivor_cycle)]
        child_genome = mutate_genome(parent.genome, rng, mutation_rate=mutation_rate)
        children_by_slot[slot.agent_id] = (
            parent,
            AntAgent(
                agent_id=slot.agent_id,
                name=slot.name,
                generation=max(slot.generation, parent.generation + 1),
                genome=child_genome,
                bankroll=slot.bankroll,
                accuracy=parent.accuracy,
                wallet_address=slot.wallet_address,
                parent_agent_id=parent.agent_id,
                lineage_id=parent.lineage_id or f"lineage_{parent.lineage_root_agent_id or parent.agent_id}",
                lineage_root_agent_id=parent.lineage_root_agent_id or parent.agent_id,
                verified_lineage=parent.verified_lineage,
                world_human_id=parent.world_human_id,
                evolution_role="child",
                parent_genome_id=parent.genome_id,
                previous_genome_id=slot.genome_id,
            ),
        )
        child_index += 1

    next_agents = []
    transitions = []
    for agent in agents:
        if agent.agent_id in children_by_slot:
            parent, child = children_by_slot[agent.agent_id]
            next_agents.append(child)
            transitions.append(
                {
                    "agent_id": agent.agent_id,
                    "role": "child",
                    "previous_genome_id": agent.genome_id,
                    "parent_agent_id": parent.agent_id,
                    "parent_genome_id": parent.genome_id,
                    "genome_id": child.genome_id,
                    "fitness": _agent_fitness(agent, genome_scores),
                    "parent_fitness": _agent_fitness(parent, genome_scores),
                }
            )
        else:
            agent.evolution_role = "survivor"
            agent.parent_genome_id = ""
            agent.previous_genome_id = ""
            next_agents.append(agent)
            transitions.append(
                {
                    "agent_id": agent.agent_id,
                    "role": "survivor",
                    "genome_id": agent.genome_id,
                    "fitness": _agent_fitness(agent, genome_scores),
                }
            )

    summary = {
        "population_size": len(next_agents),
        "survivors": len(survivors),
        "children": len(children_by_slot),
        "survival_rate": survival_rate,
        "mutation_rate": mutation_rate,
        "seed": seed,
        "top_genomes": [
            {
                "agent_id": agent.agent_id,
                "genome_id": agent.genome_id,
                "fitness": _agent_fitness(agent, genome_scores),
                "memory_score": genome_scores.get(agent.genome_id, 0.0),
            }
            for agent in ranked[: min(10, len(ranked))]
        ],
        "transitions": transitions,
    }
    return next_agents, summary


def _population_payload(agents: list[AntAgent], *, seed: int, summary: dict[str, Any]) -> dict[str, Any]:
    agents_payload = []
    for agent in agents:
        row = agent_to_state(agent)
        agents_payload.append(row)
    return {
        "schema_version": 1,
        "seed": seed,
        "note": "evolved population state",
        "population_size": len(agents),
        "evolution": summary,
        "agents": agents_payload,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population-state", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--latest", type=int, default=20)
    parser.add_argument("--survival-rate", type=float, default=0.55)
    parser.add_argument("--mutation-rate", type=float, default=0.18)
    parser.add_argument("--seed", type=int, default=500)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    agents = load_population_state(args.population_state)
    memory_files = _find_memory_files(args.runs_dir, args.latest)
    if not memory_files:
        raise SystemExit(f"No conversation_memory.json files found under {args.runs_dir}")
    analysis = analyze_memory_files(memory_files)
    next_agents, summary = evolve_population(
        agents,
        genome_scores=_genome_scores(analysis),
        survival_rate=args.survival_rate,
        mutation_rate=args.mutation_rate,
        seed=args.seed,
    )
    payload = _population_payload(next_agents, seed=args.seed, summary=summary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        "Evolved population: "
        f"survivors={summary['survivors']} children={summary['children']} "
        f"out={args.out}"
    )


if __name__ == "__main__":
    main()
