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
    _write_rooms(path / "rooms.json", result)
    _write_conversation_memory(path / "conversation_memory.json", result)
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
        f"- Room budget: {summary['speaker_slots']}",
        f"- Debate rooms: {summary.get('room_count', 0)} rooms, {summary.get('room_claims', 0)} room claims, {summary.get('final_claims', 0)} final claims",
        f"- Debate quality: {summary.get('dispute_count', 0)} disputes, {float(summary.get('dispute_rate', 0.0)):.0%} dispute rate, {summary.get('subject_count', 0)} evidence subjects, {summary.get('subject_shift_count', 0)} subject shifts",
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
        "- `debate.md`: room debates and final chamber claims.",
        "- `rooms.json`: structured room membership, representatives, and syntheses.",
        "- `conversation_memory.json`: queryable debate claims, dispute edges, and debater reputation summary.",
        "- `forecasts.csv`: final forecast and bet/pass decision for every predictor.",
        "- `findings.json`: normalized findings used by this run.",
        "- `knowledge_views.json`: filtered predictor views derived from the full graph.",
        "- `world_graph.json`: lightweight round subgraph with match, teams, findings, evidence claims, sources, players, predictions, and debate claims.",
        "- `events.compact.jsonl`: compact machine-readable event stream.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_debate(path: Path, result: RoundResult) -> None:
    lines = [f"# Debate Feed: {result.round_id}", ""]
    if result.rooms:
        lines.extend(["## Room Debates", ""])
        for room in result.rooms:
            lines.extend(
                [
                    f"### {room.room_id}: {room.stance} / {room.evidence_focus}",
                    "",
                    f"- Participants: {len(room.participant_ids)}",
                    f"- Representatives: {', '.join(room.representative_ids) or 'none'}",
                    f"- Room home probability: {_pct(room.synthesis_home_probability)}",
                    f"- Room confidence: {room.synthesis_confidence:.3f}",
                    f"- Synthesis: {room.synthesis}",
                    "",
                ]
            )
            for claim in room.claims:
                _append_claim_lines(lines, claim, heading_level="####")
        lines.extend(["## Final Chamber", ""])
    for claim in result.claims:
        _append_claim_lines(lines, claim, heading_level="##" if not result.rooms else "###")
    path.write_text("\n".join(lines), encoding="utf-8")


def _append_claim_lines(lines: list[str], claim, *, heading_level: str) -> None:
    tags = ", ".join(claim.evidence_tags) if claim.evidence_tags else "no dominant source"
    role = claim.debate_role or "speaker"
    phase = claim.debate_phase or "final"
    room = claim.room_id or "global"
    lines.extend(
        [
            f"{heading_level} {claim.speaker_name}",
            "",
            f"- Phase: {phase}",
            f"- Room: {room}",
            f"- Debate role: {role}",
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
    if claim.dispute:
        target = claim.dispute.get("target_speaker_name") or claim.dispute.get("target_speaker_id") or "previous claim"
        critique_type = str(claim.dispute.get("critique_type") or "dispute").replace("_", " ")
        excerpt = claim.dispute.get("target_excerpt") or ""
        probability_gap = claim.dispute.get("probability_gap")
        if isinstance(probability_gap, int | float):
            gap_value = 0.0 if abs(probability_gap) < 0.0005 else probability_gap
            gap_text = f"{gap_value:+.1%}"
        else:
            gap_text = "n/a"
        lines.extend(
            [
                "Dispute:",
                "",
                f"- Target: {target}",
                f"- Critique type: {critique_type}",
                f"- Probability gap: {gap_text}",
            ]
        )
        if excerpt:
            lines.append(f"- Target excerpt: \"{excerpt}\"")
        target_subject = claim.dispute.get("target_subject")
        counter_subject = claim.dispute.get("counter_subject")
        if target_subject or counter_subject:
            lines.append(f"- Subject shift: {target_subject or 'n/a'} -> {counter_subject or 'n/a'}")
        lines.append("")
    if claim.diagnostics:
        lines.extend(["Final diagnostics:", ""])
        consensus_label = claim.diagnostics.get("consensus_label")
        main_thread = claim.diagnostics.get("main_evidence_thread")
        minority_report = claim.diagnostics.get("minority_report")
        source_dispute = claim.diagnostics.get("source_dispute") or {}
        room_range = claim.diagnostics.get("room_probability_range")
        if consensus_label:
            lines.append(f"- Consensus: {str(consensus_label).replace('_', ' ')}")
        if main_thread:
            lines.append(f"- Main evidence: {main_thread}")
        if minority_report:
            clean_report = str(minority_report)
            if clean_report.startswith("Minority report:"):
                clean_report = clean_report.split(":", 1)[1].strip()
            lines.append(f"- Minority report: {clean_report}")
        if source_dispute:
            dominant_type = str(source_dispute.get("dominant_type") or "").replace("_", " ")
            critique_counts = source_dispute.get("critique_counts") or {}
            dominant_key = str(source_dispute.get("dominant_type") or "")
            dominant_count = critique_counts.get(dominant_key, 0) if isinstance(critique_counts, dict) else 0
            dispute_count = source_dispute.get("dispute_count") or 0
            target_subject = source_dispute.get("target_subject") or "n/a"
            counter_subject = source_dispute.get("counter_subject") or "n/a"
            lines.append(f"- Source dispute: {dominant_type} ({dominant_count}/{dispute_count} disputes)")
            lines.append(f"- Dispute subject shift: {target_subject} -> {counter_subject}")
        if room_range:
            lines.append(f"- Room range: {room_range}")
        lines.append("")
    if claim.referenced_evidence:
        lines.extend(["Referenced evidence:", ""])
        for evidence in claim.referenced_evidence[:4]:
            subject = evidence.get("subject") or evidence.get("team") or "unknown"
            claim_type = str(evidence.get("claim_type") or "claim").replace("_", " ")
            source = evidence.get("source_title") or evidence.get("scout_name") or "source"
            evidence_text = evidence.get("claim") or ""
            lines.append(f"- `{claim_type}` {subject}: {evidence_text} ({source})")
        lines.append("")


def _write_rooms(path: Path, result: RoundResult) -> None:
    rooms = [room.to_dict() for room in result.rooms]
    path.write_text(json.dumps(rooms, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_conversation_memory(path: Path, result: RoundResult) -> None:
    memory = _conversation_memory(result)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _conversation_memory(result: RoundResult) -> dict:
    room_claims = [claim for room in result.rooms for claim in room.claims]
    all_claims = room_claims + result.claims
    debaters: dict[str, dict] = {}
    claim_nodes = []
    dispute_edges = []
    room_timeline = []

    for room in result.rooms:
        room_timeline.append(
            {
                "room_id": room.room_id,
                "evidence_focus": room.evidence_focus,
                "participant_count": len(room.participant_ids),
                "representative_ids": room.representative_ids,
                "synthesis_home_probability": room.synthesis_home_probability,
                "synthesis_confidence": room.synthesis_confidence,
                "claim_ids": [_claim_memory_id(claim) for claim in room.claims],
            }
        )

    for claim in all_claims:
        claim_id = _claim_memory_id(claim)
        claim_nodes.append(
            {
                "claim_id": claim_id,
                "speaker_id": claim.speaker_id,
                "speaker_name": claim.speaker_name,
                "genome_id": claim.genome_id,
                "room_id": claim.room_id or "global",
                "phase": claim.debate_phase or "final",
                "role": claim.debate_role or "speaker",
                "claim_type": claim.claim_type,
                "direction": claim.direction,
                "stated_home_probability": claim.stated_home_probability,
                "confidence": claim.confidence,
                "message": claim.message,
                "evidence_subjects": _claim_evidence_subjects(claim),
                "dispute": claim.dispute,
                "diagnostics": claim.diagnostics,
            }
        )
        if claim.speaker_id != "colony_synthesis":
            record = debaters.setdefault(claim.speaker_id, _empty_debater_memory(claim))
            _merge_debater_identity(record, claim)
            record["claims"] += 1
            record["rooms"].add(claim.room_id or "global")
            record["roles"].add(claim.debate_role or "speaker")
            record["avg_confidence_sum"] += claim.confidence
            record["avg_probability_sum"] += claim.stated_home_probability
            if claim.dispute:
                record["disputes_made"] += 1
                critique_type = str(claim.dispute.get("critique_type") or "dispute")
                record["critique_counts"][critique_type] = record["critique_counts"].get(critique_type, 0) + 1
                target_id = str(claim.dispute.get("target_speaker_id") or "")
                if target_id:
                    record["targets"].add(target_id)
                    target_record = debaters.setdefault(
                        target_id,
                        _empty_debater_memory_from_id(
                            target_id,
                            str(claim.dispute.get("target_speaker_name") or target_id),
                        ),
                    )
                    target_genome_id = str(claim.dispute.get("target_genome_id") or "")
                    if target_genome_id and not target_record.get("genome_id"):
                        target_record["genome_id"] = target_genome_id
                    target_record["disputes_received"] += 1
                dispute_edges.append(
                    {
                        "source_claim_id": claim_id,
                        "source_speaker_id": claim.speaker_id,
                        "source_genome_id": claim.genome_id,
                        "target_claim_id": claim.dispute.get("target_claim_id"),
                        "target_speaker_id": claim.dispute.get("target_speaker_id"),
                        "target_genome_id": claim.dispute.get("target_genome_id"),
                        "critique_type": critique_type,
                        "probability_gap": claim.dispute.get("probability_gap"),
                        "target_subject": claim.dispute.get("target_subject"),
                        "counter_subject": claim.dispute.get("counter_subject"),
                    }
                )

    return {
        "round_id": result.round_id,
        "summary": {
            "rooms": len(result.rooms),
            "claims": len(claim_nodes),
            "room_claims": len(room_claims),
            "final_claims": len(result.claims),
            "disputes": len(dispute_edges),
            "dispute_rate": result.summary.get("dispute_rate", 0.0),
            "evidence_subjects": result.summary.get("subject_count", 0),
            "critique_types": result.summary.get("critique_type_count", 0),
            "subject_shifts": result.summary.get("subject_shift_count", 0),
            "carried_claims": result.summary.get("carried_claim_count", 0),
        },
        "room_timeline": room_timeline,
        "claims": claim_nodes,
        "disputes": dispute_edges,
        "debaters": [_finalize_debater_memory(record) for record in debaters.values()],
        "final_diagnostics": [claim.diagnostics for claim in result.claims if claim.diagnostics],
    }


def _claim_memory_id(claim) -> str:
    phase = claim.debate_phase or "final"
    room = claim.room_id or "global"
    return f"debate_claim:{claim.round_id}:{phase}:{room}:{claim.speaker_id}"


def _claim_evidence_subjects(claim) -> list[str]:
    subjects: list[str] = []
    for evidence in claim.referenced_evidence:
        subject = str(evidence.get("subject") or evidence.get("team") or evidence.get("player") or "").strip()
        if subject and subject not in subjects:
            subjects.append(subject)
    return subjects[:5]


def _empty_debater_memory(claim) -> dict:
    return {
        "speaker_id": claim.speaker_id,
        "speaker_name": claim.speaker_name,
        "genome_id": claim.genome_id,
        "model": claim.model,
        "persona": claim.persona,
        "access_tier": claim.access_tier,
        "claims": 0,
        "disputes_made": 0,
        "disputes_received": 0,
        "critique_counts": {},
        "targets": set(),
        "rooms": set(),
        "roles": set(),
        "avg_confidence_sum": 0.0,
        "avg_probability_sum": 0.0,
    }


def _merge_debater_identity(record: dict, claim) -> None:
    for key in ("speaker_name", "genome_id", "model", "persona", "access_tier"):
        if not record.get(key):
            record[key] = getattr(claim, key)


def _empty_debater_memory_from_id(speaker_id: str, speaker_name: str) -> dict:
    return {
        "speaker_id": speaker_id,
        "speaker_name": speaker_name,
        "genome_id": "",
        "model": "",
        "persona": "",
        "access_tier": "",
        "claims": 0,
        "disputes_made": 0,
        "disputes_received": 0,
        "critique_counts": {},
        "targets": set(),
        "rooms": set(),
        "roles": set(),
        "avg_confidence_sum": 0.0,
        "avg_probability_sum": 0.0,
    }


def _finalize_debater_memory(record: dict) -> dict:
    claims = int(record["claims"])
    avg_confidence = record["avg_confidence_sum"] / claims if claims else None
    avg_probability = record["avg_probability_sum"] / claims if claims else None
    roles = sorted(record["roles"])
    return {
        "speaker_id": record["speaker_id"],
        "speaker_name": record["speaker_name"],
        "genome_id": record["genome_id"],
        "model": record["model"],
        "persona": record["persona"],
        "access_tier": record["access_tier"],
        "claims": claims,
        "rooms": sorted(record["rooms"]),
        "roles": roles,
        "primary_role": roles[0] if roles else "",
        "disputes_made": record["disputes_made"],
        "disputes_received": record["disputes_received"],
        "critique_counts": dict(sorted(record["critique_counts"].items())),
        "targets": sorted(record["targets"]),
        "avg_confidence": None if avg_confidence is None else round(avg_confidence, 4),
        "avg_stated_home_probability": None if avg_probability is None else round(avg_probability, 4),
        "debate_activity_score": round(
            claims + record["disputes_made"] * 1.5 + record["disputes_received"] * 0.5,
            4,
        ),
    }


def _write_forecasts(path: Path, result: RoundResult) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "agent_id",
                "genome_id",
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
    entity_counts = _entity_type_counts(result)
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
            "entity_counts": entity_counts,
        }
    )
    events.extend({"event_type": "debate_room", **room.to_dict()} for room in result.rooms)
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
    entity_counts = _entity_type_counts(result)
    count_text = ", ".join(f"{entity_type}={count}" for entity_type, count in sorted(entity_counts.items()))
    lines.extend(
        [
            f"- Graph id: {result.world_graph.graph_id}",
            f"- Entities: {len(result.world_graph.entities)}",
            f"- Relationships: {len(result.world_graph.relationships)}",
            f"- Entity types: {count_text}",
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

    summary = result.summary
    lines.extend(
        [
            "## Debate Quality",
            "",
            f"- Disputes: {summary.get('dispute_count', 0)}",
            f"- Dispute rate: {float(summary.get('dispute_rate', 0.0)):.0%}",
            f"- Evidence subjects: {summary.get('subject_count', 0)}",
            f"- Critique types: {summary.get('critique_type_count', 0)}",
            f"- Subject shifts: {summary.get('subject_shift_count', 0)}",
            f"- Carried claims between rooms: {summary.get('carried_claim_count', 0)}",
            "",
        ]
    )

    lines.extend(["## Debate Rooms", ""])
    for room in result.rooms:
        lines.append(
            f"- {room.room_id}: stance={room.stance}, focus={room.evidence_focus}, "
            f"participants={len(room.participant_ids)}, reps={len(room.representative_ids)}, "
            f"p={_pct(room.synthesis_home_probability)}, confidence={room.synthesis_confidence:.3f}"
        )
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


def _entity_type_counts(result: RoundResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity in result.world_graph.entities:
        counts[entity.entity_type] = counts.get(entity.entity_type, 0) + 1
    return counts
