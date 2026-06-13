"""Compact run artifacts for the Colony harness."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from .models import MatchContext, RoundResult


def _pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1%}"


def _safe_name(value: str) -> str:
    cleaned = []
    for char in value.lower():
        if char.isalnum():
            cleaned.append(char)
        elif char in {"-", "_", " "}:
            cleaned.append("_")
    return "".join(cleaned).strip("_") or "run"


def create_run_dir(base_dir: str | Path, round_id: str) -> Path:
    base = Path(base_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{timestamp}_{_safe_name(round_id)}"
    path = base / stem
    suffix = 1
    while path.exists():
        path = base / f"{stem}_{suffix}"
        suffix += 1
    path.mkdir(parents=True, exist_ok=False)
    return path


def write_compact_run_artifacts(
    *,
    run_dir: str | Path,
    match: MatchContext,
    result: RoundResult,
    debug: bool = False,
) -> Path:
    path = Path(run_dir)
    path.mkdir(parents=True, exist_ok=True)

    _write_summary(path / "summary.md", match, result)
    _write_debate(path / "debate.md", result)
    _write_forecasts(path / "forecasts.csv", result)
    _write_findings(path / "findings.json", result)
    _write_knowledge_views(path / "knowledge_views.json", result)
    _write_world_graph(path / "world_graph.json", result)
    _write_compact_events(path / "events.compact.jsonl", result)
    if debug:
        _write_debug_report(path / "debug.md", match, result)
    return path


def _write_summary(path: Path, match: MatchContext, result: RoundResult) -> None:
    summary = result.summary
    lines = [
        f"# Colony Run: {result.round_id}",
        "",
        "## Match",
        "",
        f"- Home: {match.home_team}",
        f"- Away: {match.away_team}",
        f"- Market home probability: {_pct(summary['market_home_probability'])}",
        f"- Debate home probability: {_pct(summary['debate_home_probability'])}",
        "",
        "## Population",
        "",
        f"- Predictors: {summary['population']}",
        f"- Debaters: {summary['speaker_slots']}",
        f"- Findings: {summary['findings']} public={summary['public_findings']} shared={summary['shared_findings']} private={summary['private_findings']}",
        f"- Knowledge views: public={summary['public_views']} shared={summary['shared_views']} private={summary['private_views']}",
        "",
        "## Betting",
        "",
        f"- Home bets: {summary['home_bets']}",
        f"- Away bets: {summary['away_bets']}",
        f"- Passes: {summary['passes']}",
        f"- Total staked: {summary['total_staked']}",
        "",
        "## Files",
        "",
        "- `debate.md`: public debater claims.",
        "- `forecasts.csv`: final forecast and bet/pass decision for every predictor.",
        "- `findings.json`: normalized findings used by this run.",
        "- `knowledge_views.json`: filtered predictor views derived from the full graph.",
        "- `world_graph.json`: lightweight round subgraph for this selected match.",
        "- `events.compact.jsonl`: compact machine-readable event stream.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_debate(path: Path, result: RoundResult) -> None:
    lines = [f"# Debate Feed: {result.round_id}", ""]
    for claim in result.claims:
        tags = ", ".join(claim.evidence_tags) if claim.evidence_tags else "no dominant source"
        lines.extend(
            [
                f"## {claim.speaker_name}",
                "",
                f"- Model: `{claim.model}`",
                f"- Persona: {claim.persona}",
                f"- Knowledge access: {claim.access_tier} ({claim.visible_findings} findings)",
                f"- Claim type: {claim.claim_type}",
                f"- Selection reason: {claim.selection_reason}",
                f"- Evidence tags: {tags}",
                f"- Stated home probability: {_pct(claim.stated_home_probability)}",
                f"- Confidence: {claim.confidence:.3f}",
                "",
                claim.message,
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_forecasts(path: Path, result: RoundResult) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "agent_id",
                "access_tier",
                "visible_findings",
                "home_probability",
                "market_edge",
                "edge_threshold",
                "edge",
                "side",
                "stake",
                "bankroll",
                "decision_reason",
            ],
        )
        writer.writeheader()
        for forecast in result.forecasts:
            writer.writerow(forecast.to_dict())


def _write_findings(path: Path, result: RoundResult) -> None:
    findings = [finding.to_dict() for finding in result.findings]
    path.write_text(json.dumps(findings, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_knowledge_views(path: Path, result: RoundResult) -> None:
    views = [view.to_dict() for view in result.knowledge_views]
    path.write_text(json.dumps(views, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_world_graph(path: Path, result: RoundResult) -> None:
    graph = result.world_graph.to_dict()
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_compact_events(path: Path, result: RoundResult) -> None:
    events = [{"event_type": "round_summary", **result.summary}]
    events.extend({"event_type": "finding", **finding.to_dict()} for finding in result.findings)
    events.extend(
        {
            "event_type": "knowledge_view",
            "agent_id": view.agent_id,
            "access_tier": view.access_tier,
            "visible_finding_ids": [finding.finding_id for finding in view.visible_findings],
            "source_probabilities": {
                "market": view.market_home_probability,
                "stats": view.stats_home_signal,
                "odds": view.odds_home_signal,
                "news": view.news_home_signal,
            },
        }
        for view in result.knowledge_views
    )
    events.append(
        {
            "event_type": "world_graph_summary",
            "graph_id": result.world_graph.graph_id,
            "round_id": result.world_graph.round_id,
            "entities": len(result.world_graph.entities),
            "relationships": len(result.world_graph.relationships),
        }
    )
    events.extend({"event_type": "debate_claim", **claim.to_dict()} for claim in result.claims)
    events.extend({"event_type": "forecast", **forecast.to_dict()} for forecast in result.forecasts)

    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _write_debug_report(path: Path, match: MatchContext, result: RoundResult) -> None:
    forecasts_by_edge = sorted(result.forecasts, key=lambda forecast: abs(forecast.market_edge), reverse=True)
    lines = [
        f"# Debug Report: {result.round_id}",
        "",
        "## Source Findings",
        "",
        f"- Market: {_pct(match.market_home_probability)}",
        f"- Stats: {_pct(match.stats_home_signal)}",
        f"- Odds: {_pct(match.odds_home_signal)}",
        f"- News: {_pct(match.news_home_signal)}",
        "",
        "## Findings",
        "",
    ]
    for finding in result.findings:
        lines.extend(
            [
                f"### {finding.finding_id}",
                "",
                f"- Access: {finding.access_level}",
                f"- Scout: {finding.scout_name}",
                f"- Source type: {finding.source_type}",
                f"- Home probability: {_pct(finding.home_probability)}",
                f"- Home delta: {_pct(finding.home_delta)}",
                f"- Confidence: {finding.confidence:.2f}",
                f"- Cost: {finding.cost}",
                f"- Summary: {finding.summary}",
                "",
            ]
        )
        if finding.evidence_claims:
            lines.append("Evidence claims:")
            for claim in finding.evidence_claims[:8]:
                claim_text = claim.get("claim", "")
                claim_type = claim.get("claim_type", "claim")
                subject = claim.get("subject", "unknown")
                source = claim.get("source_title") or claim.get("source_url") or "source"
                lines.append(f"- `{claim_type}` {subject}: {claim_text} ({source})")
            lines.append("")

    lines.extend(["## Round Subgraph", ""])
    lines.extend(
        [
            f"- Graph id: {result.world_graph.graph_id}",
            f"- Entities: {len(result.world_graph.entities)}",
            f"- Relationships: {len(result.world_graph.relationships)}",
            "",
        ]
    )

    lines.extend(["## Knowledge Views", ""])
    for tier in ("public", "shared", "private"):
        tier_views = [view for view in result.knowledge_views if view.access_tier == tier]
        if not tier_views:
            continue
        avg_findings = sum(len(view.visible_findings) for view in tier_views) / len(tier_views)
        lines.append(f"- {tier}: predictors={len(tier_views)}, avg_visible_findings={avg_findings:.1f}")
    lines.append("")

    lines.extend(["## Debaters", ""])
    for claim in result.claims:
        lines.append(
            f"- {claim.speaker_name}: {claim.persona}, {claim.model}, "
            f"access={claim.access_tier}/{claim.visible_findings}, type={claim.claim_type}, "
            f"p={_pct(claim.stated_home_probability)}, "
            f"confidence={claim.confidence:.3f}, reason={claim.selection_reason}"
        )

    lines.extend(["", "## Top Final Edges", ""])
    for forecast in forecasts_by_edge[:10]:
        lines.append(
            f"- {forecast.agent_id}: access={forecast.access_tier}/{forecast.visible_findings}, "
            f"side={forecast.side}, p={_pct(forecast.home_probability)}, "
            f"market_edge={_pct(forecast.market_edge)}, threshold={_pct(forecast.edge_threshold)}, "
            f"stake={forecast.stake}, reason={forecast.decision_reason}"
        )

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Default logs omit raw LLM prompts/responses and bet commitment reveals.",
            "- Use explicit trace logging later for full research-grade internals.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
