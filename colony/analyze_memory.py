"""Analyze Colony conversation memory artifacts.

This script is intentionally lightweight: it reads compact
`conversation_memory.json` files from run directories and produces a small
debug report that helps decide which debater behaviors are useful enough to
feed into later reputation or genome evolution.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_RUNS_DIR = Path("colony/runs")


@dataclass
class ArchetypeStats:
    key: str
    runs: set[str] = field(default_factory=set)
    debaters: int = 0
    claims: int = 0
    disputes_made: int = 0
    disputes_received: int = 0
    rooms: int = 0
    confidence_sum: float = 0.0
    confidence_count: int = 0
    critique_counts: Counter[str] = field(default_factory=Counter)

    def add(self, run_id: str, debater: dict[str, Any]) -> None:
        self.runs.add(run_id)
        self.debaters += 1
        self.claims += int(debater.get("claims") or 0)
        self.disputes_made += int(debater.get("disputes_made") or 0)
        self.disputes_received += int(debater.get("disputes_received") or 0)
        self.rooms += len(debater.get("rooms") or [])
        confidence = debater.get("avg_confidence")
        if isinstance(confidence, int | float):
            self.confidence_sum += float(confidence)
            self.confidence_count += 1
        self.critique_counts.update(debater.get("critique_counts") or {})

    @property
    def avg_confidence(self) -> float | None:
        if not self.confidence_count:
            return None
        return self.confidence_sum / self.confidence_count

    @property
    def usefulness_score(self) -> float:
        source_quality = self.critique_counts.get("source_quality", 0)
        counter_evidence = self.critique_counts.get("counter_evidence", 0)
        impact_size = self.critique_counts.get("impact_size", 0)
        directional = (
            self.critique_counts.get("underpriced_home", 0)
            + self.critique_counts.get("overpriced_home", 0)
        )
        confidence = self.avg_confidence or 0.0
        return round(
            self.claims * 0.6
            + self.disputes_made * 1.2
            + source_quality * 1.4
            + counter_evidence * 1.2
            + impact_size * 0.8
            + directional * 0.7
            + self.rooms * 0.25
            + confidence,
            4,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "runs": len(self.runs),
            "debaters": self.debaters,
            "claims": self.claims,
            "disputes_made": self.disputes_made,
            "disputes_received": self.disputes_received,
            "rooms": self.rooms,
            "avg_confidence": None if self.avg_confidence is None else round(self.avg_confidence, 4),
            "critique_counts": dict(sorted(self.critique_counts.items())),
            "usefulness_score": self.usefulness_score,
        }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_memory_files(runs_dir: Path, latest: int | None) -> list[Path]:
    files = sorted(
        runs_dir.glob("*/conversation_memory.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if latest is not None:
        files = files[:latest]
    return list(reversed(files))


def _archetype_key(debater: dict[str, Any]) -> str:
    persona = str(debater.get("persona") or "unknown-persona")
    model = str(debater.get("model") or "unknown-model")
    access = str(debater.get("access_tier") or "unknown-access")
    return f"{persona} | {model} | {access}"


def _genome_key(debater: dict[str, Any]) -> str:
    return str(debater.get("genome_id") or "")


def analyze_memory_files(memory_files: list[Path]) -> dict[str, Any]:
    archetypes: dict[str, ArchetypeStats] = {}
    genomes: dict[str, ArchetypeStats] = {}
    top_debater_rows: list[dict[str, Any]] = []
    critique_counts: Counter[str] = Counter()
    evidence_threads: Counter[str] = Counter()
    source_disputes: Counter[str] = Counter()
    totals = Counter()
    quality_sums = Counter()
    quality_counts = Counter()

    for memory_file in memory_files:
        memory = _read_json(memory_file)
        run_id = str(memory.get("round_id") or memory_file.parent.name)
        summary = memory.get("summary") or {}
        totals["runs"] += 1
        totals["rooms"] += int(summary.get("rooms") or 0)
        totals["claims"] += int(summary.get("claims") or 0)
        totals["disputes"] += int(summary.get("disputes") or 0)
        totals["room_claims"] += int(summary.get("room_claims") or 0)
        _collect_quality_metrics(
            summary=summary,
            memory=memory,
            quality_sums=quality_sums,
            quality_counts=quality_counts,
        )

        for edge in memory.get("disputes") or []:
            critique_counts[str(edge.get("critique_type") or "unknown")] += 1

        for diagnostic in memory.get("final_diagnostics") or []:
            thread = str(diagnostic.get("main_evidence_thread") or "").strip()
            if thread:
                evidence_threads[thread] += 1
            source_dispute = diagnostic.get("source_dispute") or {}
            dominant = str(source_dispute.get("dominant_type") or "").strip()
            if dominant:
                source_disputes[dominant] += 1

        for debater in memory.get("debaters") or []:
            key = _archetype_key(debater)
            archetypes.setdefault(key, ArchetypeStats(key)).add(run_id, debater)
            genome_key = _genome_key(debater)
            if genome_key:
                genomes.setdefault(genome_key, ArchetypeStats(genome_key)).add(run_id, debater)
            top_debater_rows.append(
                {
                    "run": memory_file.parent.name,
                    "speaker_id": debater.get("speaker_id"),
                    "speaker_name": debater.get("speaker_name"),
                    "genome_id": genome_key,
                    "archetype": key,
                    "primary_role": debater.get("primary_role"),
                    "claims": debater.get("claims") or 0,
                    "disputes_made": debater.get("disputes_made") or 0,
                    "disputes_received": debater.get("disputes_received") or 0,
                    "critique_counts": debater.get("critique_counts") or {},
                    "debate_activity_score": debater.get("debate_activity_score") or 0,
                }
            )

    archetype_rows = sorted(
        (stats.to_dict() for stats in archetypes.values()),
        key=lambda item: (item["usefulness_score"], item["runs"], item["claims"]),
        reverse=True,
    )
    genome_rows = sorted(
        (stats.to_dict() for stats in genomes.values()),
        key=lambda item: (item["usefulness_score"], item["runs"], item["claims"]),
        reverse=True,
    )
    top_debater_rows.sort(
        key=lambda item: (
            float(item["debate_activity_score"]),
            int(item["disputes_made"]),
            int(item["claims"]),
        ),
        reverse=True,
    )

    return {
        "summary": dict(totals),
        "debate_quality": _finalize_quality_metrics(quality_sums, quality_counts),
        "critique_counts": dict(critique_counts.most_common()),
        "source_disputes": dict(source_disputes.most_common()),
        "evidence_threads": dict(evidence_threads.most_common()),
        "genomes": genome_rows,
        "archetypes": archetype_rows,
        "top_debaters": top_debater_rows,
        "memory_files": [str(path) for path in memory_files],
    }


def _collect_quality_metrics(
    *,
    summary: dict[str, Any],
    memory: dict[str, Any],
    quality_sums: Counter,
    quality_counts: Counter,
) -> None:
    disputes = int(summary.get("disputes") or 0)
    room_claims = int(summary.get("room_claims") or 0)
    dispute_rate = summary.get("dispute_rate")
    if not isinstance(dispute_rate, int | float) and room_claims:
        dispute_rate = disputes / room_claims
    if isinstance(dispute_rate, int | float):
        quality_sums["dispute_rate"] += float(dispute_rate)
        quality_counts["dispute_rate"] += 1

    metric_sources = {
        "evidence_subjects": _evidence_subject_count(memory),
        "critique_types": len({str(edge.get("critique_type") or "") for edge in memory.get("disputes") or [] if edge.get("critique_type")}),
        "subject_shifts": _subject_shift_count(memory),
        "carried_claims": summary.get("carried_claims"),
    }
    for key, fallback in metric_sources.items():
        value = summary.get(key)
        if not isinstance(value, int | float):
            value = fallback
        if isinstance(value, int | float):
            quality_sums[key] += float(value)
            quality_counts[key] += 1


def _evidence_subject_count(memory: dict[str, Any]) -> int:
    subjects: set[str] = set()
    for claim in memory.get("claims") or []:
        for subject in claim.get("evidence_subjects") or []:
            clean_subject = str(subject).strip().lower()
            if clean_subject:
                subjects.add(clean_subject)
    return len(subjects)


def _subject_shift_count(memory: dict[str, Any]) -> int:
    shifts = 0
    for edge in memory.get("disputes") or []:
        target = str(edge.get("target_subject") or "").strip().lower()
        counter = str(edge.get("counter_subject") or "").strip().lower()
        if target and counter and target != counter:
            shifts += 1
    return shifts


def _finalize_quality_metrics(quality_sums: Counter, quality_counts: Counter) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for key in sorted(quality_sums):
        count = int(quality_counts.get(key) or 0)
        value = float(quality_sums[key])
        rows[key] = {
            "total": round(value, 4),
            "avg_per_run": None if not count else round(value / count, 4),
            "runs_with_metric": count,
        }
    return rows


def _format_count_map(values: dict[str, int], *, limit: int = 8) -> list[str]:
    if not values:
        return ["- none"]
    rows = []
    for label, count in list(values.items())[:limit]:
        rows.append(f"- {label}: {count}")
    return rows


def _md_cell(value: Any) -> str:
    text = str(value if value not in {None, ""} else "unknown")
    return text.replace("|", "\\|")


def render_markdown_report(
    analysis: dict[str, Any],
    *,
    genome_limit: int,
    archetype_limit: int,
    debater_limit: int,
) -> str:
    summary = analysis["summary"]
    lines = [
        "# Colony Conversation Memory Report",
        "",
        "## Scope",
        "",
        f"- Runs analyzed: {summary.get('runs', 0)}",
        f"- Rooms: {summary.get('rooms', 0)}",
        f"- Claims: {summary.get('claims', 0)}",
        f"- Disputes: {summary.get('disputes', 0)}",
        "",
        "## Debate Quality",
        "",
        *_format_quality_metrics(analysis.get("debate_quality") or {}),
        "",
        "## Critique Mix",
        "",
        *_format_count_map(analysis["critique_counts"]),
        "",
        "## Final Diagnostic Themes",
        "",
        "Source disputes:",
        "",
        *_format_count_map(analysis["source_disputes"]),
        "",
        "Evidence threads:",
        "",
        *_format_count_map(analysis["evidence_threads"], limit=5),
        "",
        "## Top Genomes",
        "",
        "| Score | Genome | Runs | Claims | Made | Received | Main critiques |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    if analysis["genomes"]:
        for row in analysis["genomes"][:genome_limit]:
            critiques = ", ".join(f"{key}={value}" for key, value in row["critique_counts"].items()) or "none"
            lines.append(
                f"| {row['usefulness_score']:.2f} | `{_md_cell(row['key'])}` | {row['runs']} | "
                f"{row['claims']} | {row['disputes_made']} | {row['disputes_received']} | {critiques} |"
            )
    else:
        lines.append("| n/a | no genome_id fields found in analyzed memories | 0 | 0 | 0 | 0 | none |")

    lines.extend(
        [
        "",
        "## Top Archetypes",
        "",
        "| Score | Archetype | Runs | Claims | Made | Received | Main critiques |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in analysis["archetypes"][:archetype_limit]:
        critiques = ", ".join(f"{key}={value}" for key, value in row["critique_counts"].items()) or "none"
        lines.append(
            f"| {row['usefulness_score']:.2f} | {_md_cell(row['key'])} | {row['runs']} | "
            f"{row['claims']} | {row['disputes_made']} | {row['disputes_received']} | {critiques} |"
        )

    lines.extend(
        [
            "",
            "## Top Single-Run Debaters",
            "",
            "| Activity | Speaker | Role | Archetype | Claims | Made | Received | Run |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in analysis["top_debaters"][:debater_limit]:
        lines.append(
            f"| {float(row['debate_activity_score']):.2f} | {_md_cell(row['speaker_name'])} | "
            f"{_md_cell(row['primary_role'])} | {_md_cell(row['archetype'])}<br>`{_md_cell(row.get('genome_id'))}` | {row['claims']} | "
            f"{row['disputes_made']} | {row['disputes_received']} | `{_md_cell(row['run'])}` |"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Scores are debugging heuristics, not settlement or truth labels.",
            "- `speaker_id` is run-local; use `genome_id` for stable genome identity and archetypes for broader behavior patterns.",
            "- Useful challenge behavior currently means source-quality checks, counter-evidence, and explicit impact-size disputes.",
        ]
    )
    return "\n".join(lines) + "\n"


def _format_quality_metrics(values: dict[str, Any]) -> list[str]:
    if not values:
        return ["- no quality metrics found"]
    labels = {
        "dispute_rate": "Average dispute rate",
        "evidence_subjects": "Average evidence subjects",
        "critique_types": "Average critique-type variety",
        "subject_shifts": "Average subject shifts",
        "carried_claims": "Average carried claims",
    }
    rows = []
    for key in ("dispute_rate", "evidence_subjects", "critique_types", "subject_shifts", "carried_claims"):
        metric = values.get(key)
        if not isinstance(metric, dict):
            continue
        avg = metric.get("avg_per_run")
        runs = metric.get("runs_with_metric")
        if avg is None:
            continue
        if key == "dispute_rate":
            rendered = f"{float(avg):.0%}"
        else:
            rendered = f"{float(avg):.2f}"
        rows.append(f"- {labels[key]}: {rendered} across {runs} runs")
    return rows or ["- no quality metrics found"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--latest", type=int, default=20, help="number of latest run memories to analyze")
    parser.add_argument("--out", type=Path, default=None, help="write markdown report to this path")
    parser.add_argument("--json-out", type=Path, default=None, help="write machine-readable analysis JSON")
    parser.add_argument("--genomes", type=int, default=10, help="number of genomes to show")
    parser.add_argument("--archetypes", type=int, default=10, help="number of archetypes to show")
    parser.add_argument("--debaters", type=int, default=10, help="number of single-run debaters to show")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    memory_files = _find_memory_files(args.runs_dir, args.latest)
    if not memory_files:
        raise SystemExit(f"No conversation_memory.json files found under {args.runs_dir}")

    analysis = analyze_memory_files(memory_files)
    report = render_markdown_report(
        analysis,
        genome_limit=args.genomes,
        archetype_limit=args.archetypes,
        debater_limit=args.debaters,
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
    else:
        print(report, end="")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(analysis, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
