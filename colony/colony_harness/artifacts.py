"""Compact run artifacts for the Colony harness."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .models import MatchContext, RoundResult
from .scouting_taxonomy import (
    SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES,
    SCOUTING_REQUIRED_CLAIM_TYPES,
    SCOUTING_RESCOUT_RECIPES,
    scouting_topic_quality,
)
from .world_graph import KG_SCHEMA_VERSION, _evidence_rejection_reasons

KG_FORBIDDEN_CLAIM_TYPES = {"team_history"}


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
    _write_social_feed(path / "social_feed.md", result)
    _write_social_actions(path / "social_feed.json", result)
    _write_social_actions_jsonl(path / "actions.jsonl", result)
    _write_social_profiles(path / "social_profiles.json", result)
    _write_social_space(path / "social_space.json", result)
    _write_social_activity_config(path / "social_activity_config.json", result)
    _write_rooms(path / "rooms.json", result)
    _write_participants(path / "participants.json", result)
    _write_debate_trace(path / "debate_trace.json", result)
    _write_conversation_memory(path / "conversation_memory.json", result)
    _write_forecasts(path / "forecasts.csv", result)
    _write_collective_decision(path / "decision.json", result)
    _write_compact_collective_decision(path / "decision.compact.json", result)
    _write_vote_trace(path / "vote_trace.json", result)
    _write_findings(path / "findings.json", result)
    _write_scouting_audit(path / "scouting_audit.json", result)
    _write_kg_summary(path / "kg_summary.json", result)
    _write_knowledge_views(path / "knowledge_views.json", result)
    _write_world_graph(path / "world_graph.json", result)
    _write_kg_manifest(path / "kg_manifest.json", result)
    _write_compact_events(path / "events.compact.jsonl", result)
    _write_run_report(path / "run_report.md", match, result)
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
        f"- Market anchor: {_room_lean(summary['market_home_probability'])}",
        f"- Debate lean: {_room_lean(summary['debate_home_probability'])}",
        "",
        "## Population",
        "",
        f"- Predictors: {summary['population']}",
        f"- Room budget: {summary['speaker_slots']}",
        f"- Debate rooms: {summary.get('room_count', 0)} rooms, {summary.get('room_claims', 0)} room claims, {summary.get('final_claims', 0)} final claims",
        f"- Social actions: {len(result.social_actions)} grounded posts/replies/reactions/prediction cards",
        f"- Debate quality: {summary.get('dispute_count', 0)} disputes, {summary.get('subject_count', 0)} evidence subjects, {summary.get('subject_shift_count', 0)} subject shifts",
        f"- Findings: {summary['findings']} public={summary['public_findings']} shared={summary['shared_findings']} private={summary['private_findings']}",
        f"- Knowledge views: public={summary['public_views']} shared={summary['shared_views']} private={summary['private_views']}",
        f"- Risk profiles: {_risk_profile_summary(summary.get('risk_profiles', {}))}",
        "",
        "## Probability Lean Distribution",
        "",
        f"- {match.home_team}/home predictions: {summary.get('prediction_home', 0)}",
        f"- Draw predictions: {summary.get('prediction_draw', 0)}",
        f"- {match.away_team}/away predictions: {summary.get('prediction_away', 0)}",
        "",
        "## Forecast Vote Distribution",
        "",
        f"- Home bets: {summary['home_bets']}",
        f"- Draw bets: {summary.get('draw_bets', 0)}",
        f"- Away bets: {summary['away_bets']}",
        "",
        "## Betting",
        "",
        f"- Market type: {summary.get('market_type', 'three_way')}",
        f"- Settlement status: {summary.get('settlement_status', 'pending')}",
        f"- Home bets: {summary['home_bets']}",
        f"- Draw bets: {summary.get('draw_bets', 0)}",
        f"- Away bets: {summary['away_bets']}",
        f"- Participation: {summary.get('participating_bets', summary['home_bets'] + summary['away_bets'])}/{summary['population']}",
        f"- Total staked: {summary['total_staked']}",
        f"- Economy receipts: {summary.get('payment_receipts', 0)} payments, {summary.get('balance_updates', 0)} balance updates",
        f"- Treasury: {summary.get('treasury_balance', 0.0)} USDC",
        "",
        "## Collective Decision",
        "",
        f"- Prediction: {result.collective_decision.prediction['sentence']}",
        f"- Recommendation: {summary.get('decision_side', 'n/a')} ({summary.get('decision_winner', 'n/a')})",
        f"- Value: {result.collective_decision.prediction.get('value', 'n/a')}",
        f"- Confidence: {result.collective_decision.prediction.get('confidence', 'n/a')}",
        f"- Score call: {result.collective_decision.score_projection['most_likely_score']['label']}",
        "",
        "## Files",
        "",
        "- `debate.md`: room debates and final chamber claims.",
        "- `social_feed.md`: MiroFish-style social interaction feed grounded in evidence.",
        "- `social_feed.json`: structured social actions with evidence cards.",
        "- `actions.jsonl`: replayable social action stream.",
        "- `social_profiles.json`: per-ant persona, risk, stance, activity, influence, and timing profile.",
        "- `social_space.json`: room/action graph describing the simulated social space.",
        "- `social_activity_config.json`: OASIS-inspired activation, feed ranking, and action-space config.",
        "- `rooms.json`: structured room membership, representatives, and syntheses.",
        "- `participants.json`: every participating ant with vote, room, debate, social, and model metadata.",
        "- `debate_trace.json`: compact replay of room debates, disputes, evidence references, and final chamber.",
        "- `conversation_memory.json`: queryable debate claims, dispute edges, and debater reputation summary.",
        "- `forecasts.csv`: final group-stage outcome pick for every predictor.",
        "- `vote_trace.json`: colony vote breakdown, per-ant votes, and per-ant prediction records.",
        "- `decision.compact.json`: compact colony-level bet decision for execution review.",
        "- `decision.json`: full structured decision with every weighted agent vote.",
        "- `findings.json`: normalized findings used by this run.",
        "- `scouting_audit.json`: scout coverage, claim types, source quality, and source provenance summary.",
        "- `kg_summary.json`: compact KG coverage, source, readiness, and backlog summary.",
        "- `knowledge_views.json`: filtered predictor views derived from the full graph.",
        "- `world_graph.json`: lightweight round subgraph with match, teams, findings, evidence claims, sources, players, predictions, and debate claims.",
        "- `kg_manifest.json`: KG schema version, ingestion entrypoints, counts, and integrity status.",
        "- `events.compact.jsonl`: compact machine-readable event stream.",
        "- `run_report.md`: human-readable post-run audit across KG, debate, participants, and vote.",
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
                    f"- Room lean: {_room_lean(room.synthesis_home_probability)}",
                    f"- Room conviction: {_conviction_label(room.synthesis_confidence)}",
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
            f"- Stance: {_claim_stance(claim)}",
            f"- Conviction: {_conviction_label(claim.confidence)}",
            "",
            claim.message,
            "",
        ]
    )
    if claim.dispute:
        target = claim.dispute.get("target_speaker_name") or claim.dispute.get("target_speaker_id") or "previous claim"
        critique_type = _display_critique_type(claim.dispute)
        critique_summary = claim.dispute.get("critique_summary") or ""
        excerpt = claim.dispute.get("target_excerpt") or ""
        probability_gap = claim.dispute.get("probability_gap")
        if isinstance(probability_gap, int | float):
            gap_text = _disagreement_label(float(probability_gap))
        else:
            gap_text = "n/a"
        lines.extend(
            [
                "Dispute:",
                "",
                f"- Target: {target}",
                f"- Critique: {critique_type}",
                f"- Disagreement size: {gap_text}",
            ]
        )
        if critique_summary:
            lines.append(f"- Meaning: {critique_summary}")
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
            lines.append("- Room spread: present")
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


def _write_social_feed(path: Path, result: RoundResult) -> None:
    lines = [f"# Social Feed: {result.round_id}", ""]
    current_room = ""
    for action in result.social_actions:
        if action.room_id != current_room:
            current_room = action.room_id
            lines.extend([f"## {current_room}", ""])
        target = f" -> {action.target_actor_id}" if action.target_actor_id else ""
        lines.extend(
            [
                f"### {action.actor_name} [{action.action_type}/{action.role}]{target}",
                "",
                f"- Topic: {action.topic}",
                f"- Stance: {action.stance}",
                f"- Tags: {_display_tags(action.tags)}",
                f"- Env action: {action.metadata.get('oasis_action', 'n/a')} at h={action.metadata.get('simulated_hour', 'n/a')}, rank={action.metadata.get('recommendation_score', 'n/a')}",
                "",
                action.text,
                "",
            ]
        )
        if action.grounded_elements:
            lines.extend(["Grounded elements:", ""])
            for element in action.grounded_elements:
                source = element.get("source") or "source"
                subject = element.get("subject") or "match"
                claim_type = str(element.get("claim_type") or "claim").replace("_", " ")
                claim_text = element.get("claim") or ""
                lines.append(f"- `{claim_type}` {subject}: {claim_text} ({source})")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_social_actions(path: Path, result: RoundResult) -> None:
    actions = [action.to_dict() for action in result.social_actions]
    path.write_text(json.dumps(actions, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_social_actions_jsonl(path: Path, result: RoundResult) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for action in result.social_actions:
            event = {"event_type": "social_action", **action.to_dict()}
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _write_social_profiles(path: Path, result: RoundResult) -> None:
    profiles = [
        {
            "agent_id": forecast.agent_id,
            "username": forecast.agent_id.replace("_", "-"),
            "wallet_address": forecast.wallet_address,
            "ens_name": forecast.ens_name,
            "persona": forecast.persona,
            "risk_profile": forecast.risk_profile,
            "social_stance": forecast.social_stance,
            "activity_level": forecast.activity_level,
            "influence_weight": forecast.influence_weight,
            "response_delay": forecast.response_delay,
            "active_windows": forecast.active_windows.split(",") if forecast.active_windows else [],
            "access_tier": forecast.access_tier,
            "visible_findings": forecast.visible_findings,
            "pick": forecast.side,
            "stake": forecast.stake,
        }
        for forecast in result.forecasts
    ]
    path.write_text(json.dumps(profiles, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_social_space(path: Path, result: RoundResult) -> None:
    forecast_by_agent = {forecast.agent_id: forecast for forecast in result.forecasts}
    action_counts = Counter(action.action_type for action in result.social_actions)
    stance_counts = Counter(action.stance for action in result.social_actions)
    profile_counts = {
        "risk_profile": dict(Counter(forecast.risk_profile for forecast in result.forecasts)),
        "persona": dict(Counter(forecast.persona for forecast in result.forecasts)),
        "social_stance": dict(Counter(forecast.social_stance for forecast in result.forecasts)),
        "activity_level": dict(Counter(forecast.activity_level for forecast in result.forecasts)),
        "influence_weight": dict(Counter(forecast.influence_weight for forecast in result.forecasts)),
    }
    rooms = []
    for room in result.rooms:
        room_actions = [action for action in result.social_actions if action.room_id == room.room_id]
        rooms.append(
            {
                "room_id": room.room_id,
                "topic": room.evidence_focus,
                "participants": len(room.participant_ids),
                "representatives": room.representative_ids,
                "participant_profiles": {
                    "risk_profile": dict(
                        Counter(
                            forecast_by_agent[agent_id].risk_profile
                            for agent_id in room.participant_ids
                            if agent_id in forecast_by_agent
                        )
                    ),
                    "activity_level": dict(
                        Counter(
                            forecast_by_agent[agent_id].activity_level
                            for agent_id in room.participant_ids
                            if agent_id in forecast_by_agent
                        )
                    ),
                },
                "action_counts": dict(Counter(action.action_type for action in room_actions)),
                "stance_counts": dict(Counter(action.stance for action in room_actions)),
                "room_lean": _room_lean(room.synthesis_home_probability),
                "conviction": _conviction_label(room.synthesis_confidence),
            }
        )
    edges = [
        {
            "source": action.actor_id,
            "target": action.target_actor_id,
            "action_type": action.action_type,
            "oasis_action": action.metadata.get("oasis_action", ""),
            "simulated_hour": action.metadata.get("simulated_hour"),
            "recommendation_score": action.metadata.get("recommendation_score"),
            "room_id": action.room_id,
            "topic": action.topic,
        }
        for action in result.social_actions
        if action.target_actor_id
    ]
    payload = {
        "round_id": result.round_id,
        "model": "mirofish_inspired_social_space",
        "spaces": ["debate_rooms", "final_chamber", "prediction_cards"],
        "profile_counts": profile_counts,
        "action_counts": dict(action_counts),
        "stance_counts": dict(stance_counts),
        "rooms": rooms,
        "interaction_edges": edges,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_social_activity_config(path: Path, result: RoundResult) -> None:
    actions = result.social_actions
    payload = {
        "round_id": result.round_id,
        "inspiration": "OASIS-style social simulation: selective activation, ranked feed targets, and platform-like action space.",
        "time_config": {
            "total_simulated_hours": 4,
            "minutes_per_round": 27,
            "peak_windows": ["pre_match", "market_move_window", "lineup_window", "last_call"],
        },
        "activation_policy": {
            "inputs": ["activity_level", "influence_weight", "response_delay", "active_windows", "risk_profile"],
            "logged_active_actions": len([action for action in actions if action.phase == "room"]),
            "mandatory_final_picks": len([action for action in actions if action.action_type == "prediction_card"]),
            "activation_reasons": dict(Counter(str(action.metadata.get("activation_reason") or "") for action in actions)),
        },
        "feed_algorithm": {
            "name": "hot_score_plus_alignment",
            "signals": ["target_hot_score", "recommendation_score", "stance_alignment", "influence_weight", "recency"],
            "max_recommendation_score": max(
                (float(action.metadata.get("recommendation_score") or 0.0) for action in actions),
                default=0.0,
            ),
        },
        "action_space": {
            "CREATE_POST": ["post", "synthesis", "prediction_card"],
            "CREATE_COMMENT": ["reply", "audit", "challenge", "comment_challenge", "comment_support"],
            "LIKE_POST": ["like", "endorse"],
            "QUOTE_POST": ["quote_reply"],
            "REPOST": ["share"],
            "FOLLOW": ["follow"],
            "READ_POST": ["view", "watch"],
        },
        "action_counts": dict(Counter(action.action_type for action in actions)),
        "oasis_action_counts": dict(Counter(str(action.metadata.get("oasis_action") or "") for action in actions)),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _room_lean(value: float | None) -> str:
    if value is None:
        return "unclear"
    if value >= 0.515:
        return "leans home"
    if value <= 0.485:
        return "leans away"
    return "contested"


def _display_tags(tags: list[str]) -> str:
    if not tags:
        return "none"
    return ", ".join(_display_tag(tag) for tag in tags)


def _display_tag(tag: str) -> str:
    labels = {
        "home_probability_too_low": "previous claim too low on home side",
        "home_probability_too_high": "previous claim too high on home side",
        "underpriced_home": "previous claim too low on home side",
        "overpriced_home": "previous claim too high on home side",
        "counter_evidence": "counter-evidence matters",
        "impact_size": "impact size disputed",
        "source_quality": "source quality disputed",
    }
    return labels.get(tag, tag.replace("_", " "))


def _claim_stance(claim) -> str:
    if claim.direction == "home":
        return "leans home"
    if claim.direction == "away":
        return "leans away"
    return "neutral"


def _conviction_label(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 0.72:
        return "high"
    if value >= 0.45:
        return "medium"
    return "low"


def _disagreement_label(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 0.04:
        size = "large"
    elif magnitude >= 0.015:
        size = "moderate"
    else:
        size = "small"
    direction = "toward home" if value > 0 else "toward away" if value < 0 else "flat"
    return f"{size}, {direction}"


def _display_critique_type(dispute: dict) -> str:
    return str(
        dispute.get("critique_label")
        or dispute.get("critique_summary")
        or str(dispute.get("critique_type") or "dispute").replace("_", " ")
    )


def _risk_profile_summary(profiles: dict) -> str:
    if not profiles:
        return "n/a"
    ordered = ["secure", "balanced", "risky"]
    parts = [f"{label}={profiles.get(label, 0)}" for label in ordered if profiles.get(label, 0)]
    extras = [f"{key}={value}" for key, value in sorted(profiles.items()) if key not in ordered]
    return ", ".join(parts + extras) if parts or extras else "n/a"


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
                "wallet_address",
                "ens_name",
                "genome_id",
                "model",
                "access_tier",
                "visible_findings",
                "persona",
                "datafeed_interests",
                "source_weights",
                "risk_profile",
                "social_stance",
                "activity_level",
                "influence_weight",
                "response_delay",
                "active_windows",
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


def _write_participants(path: Path, result: RoundResult) -> None:
    room_ids_by_agent: dict[str, set[str]] = defaultdict(set)
    representative_rooms_by_agent: dict[str, set[str]] = defaultdict(set)
    room_claim_counts: Counter[str] = Counter()
    final_claim_counts: Counter[str] = Counter()
    dispute_made_counts: Counter[str] = Counter()
    dispute_received_counts: Counter[str] = Counter()
    model_by_agent: dict[str, str] = {}
    evidence_subjects_by_agent: dict[str, set[str]] = defaultdict(set)
    claim_types_by_agent: dict[str, Counter[str]] = defaultdict(Counter)

    for room in result.rooms:
        for agent_id in room.participant_ids:
            room_ids_by_agent[agent_id].add(room.room_id)
        for agent_id in room.representative_ids:
            representative_rooms_by_agent[agent_id].add(room.room_id)
        for claim in room.claims:
            if claim.speaker_id == "colony_synthesis":
                continue
            room_claim_counts[claim.speaker_id] += 1
            model_by_agent[claim.speaker_id] = claim.model
            claim_types_by_agent[claim.speaker_id][claim.claim_type] += 1
            for subject in _claim_evidence_subjects(claim):
                evidence_subjects_by_agent[claim.speaker_id].add(subject)
            if claim.dispute:
                dispute_made_counts[claim.speaker_id] += 1
                target_id = str(claim.dispute.get("target_speaker_id") or "")
                if target_id:
                    dispute_received_counts[target_id] += 1

    for claim in result.claims:
        if claim.speaker_id == "colony_synthesis":
            continue
        final_claim_counts[claim.speaker_id] += 1
        model_by_agent[claim.speaker_id] = claim.model
        claim_types_by_agent[claim.speaker_id][claim.claim_type] += 1
        for subject in _claim_evidence_subjects(claim):
            evidence_subjects_by_agent[claim.speaker_id].add(subject)
        if claim.dispute:
            dispute_made_counts[claim.speaker_id] += 1
            target_id = str(claim.dispute.get("target_speaker_id") or "")
            if target_id:
                dispute_received_counts[target_id] += 1

    action_counts_by_agent: dict[str, Counter[str]] = defaultdict(Counter)
    targeted_by_counts: Counter[str] = Counter()
    for action in result.social_actions:
        action_counts_by_agent[action.actor_id][action.action_type] += 1
        if action.target_actor_id:
            targeted_by_counts[action.target_actor_id] += 1

    views_by_agent = {view.agent_id: view for view in result.knowledge_views}
    votes_by_agent = {
        str(item.get("agent_id") or ""): item for item in result.collective_decision.agent_votes
    }
    predictions_by_agent = {
        str(item.get("agent_id") or ""): item for item in result.collective_decision.agent_predictions
    }

    participants = []
    for forecast in result.forecasts:
        view = views_by_agent.get(forecast.agent_id)
        vote = votes_by_agent.get(forecast.agent_id, {})
        prediction = predictions_by_agent.get(forecast.agent_id, {})
        participants.append(
            {
                "agent_id": forecast.agent_id,
                "wallet_address": forecast.wallet_address,
                "ens_name": forecast.ens_name,
                "genome_id": forecast.genome_id,
                "model": forecast.model or model_by_agent.get(forecast.agent_id, ""),
                "persona": forecast.persona,
                "risk_profile": forecast.risk_profile,
                "status": "alive_for_run",
                "access_tier": forecast.access_tier,
                "visible_findings": forecast.visible_findings,
                "visible_finding_ids": [] if view is None else [finding.finding_id for finding in view.visible_findings],
                "datafeed_focus": _forecast_datafeed_focus(forecast),
                "social_profile": {
                    "stance": forecast.social_stance,
                    "activity_level": forecast.activity_level,
                    "influence_weight": forecast.influence_weight,
                    "response_delay": forecast.response_delay,
                    "active_windows": _split_windows(forecast.active_windows),
                    "actions": dict(sorted(action_counts_by_agent[forecast.agent_id].items())),
                    "targeted_by_actions": targeted_by_counts.get(forecast.agent_id, 0),
                },
                "debate": {
                    "rooms": sorted(room_ids_by_agent[forecast.agent_id]),
                    "representative_rooms": sorted(representative_rooms_by_agent[forecast.agent_id]),
                    "room_claims": room_claim_counts.get(forecast.agent_id, 0),
                    "final_claims": final_claim_counts.get(forecast.agent_id, 0),
                    "disputes_made": dispute_made_counts.get(forecast.agent_id, 0),
                    "disputes_received": dispute_received_counts.get(forecast.agent_id, 0),
                    "claim_types": dict(sorted(claim_types_by_agent[forecast.agent_id].items())),
                    "evidence_subjects": sorted(evidence_subjects_by_agent[forecast.agent_id])[:12],
                },
                "forecast": forecast.to_dict(),
                "vote": vote,
                "prediction": prediction.get("prediction", {}),
            }
        )

    payload = {
        "round_id": result.round_id,
        "participant_count": len(participants),
        "model_counts": dict(Counter(item["model"] for item in participants if item["model"])),
        "risk_profile_counts": dict(Counter(item["risk_profile"] for item in participants)),
        "access_tier_counts": dict(Counter(item["access_tier"] for item in participants)),
        "participants": participants,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_debate_trace(path: Path, result: RoundResult) -> None:
    room_claims = [claim for room in result.rooms for claim in room.claims]
    all_claims = room_claims + result.claims
    payload = {
        "round_id": result.round_id,
        "summary": {
            "rooms": len(result.rooms),
            "room_claims": len(room_claims),
            "final_claims": len(result.claims),
            "disputes": sum(1 for claim in all_claims if claim.dispute),
            "evidence_subjects": result.summary.get("subject_count", 0),
            "subject_shifts": result.summary.get("subject_shift_count", 0),
            "carried_claims": result.summary.get("carried_claim_count", 0),
        },
        "rooms": [
            {
                "room_id": room.room_id,
                "stance": room.stance,
                "evidence_focus": room.evidence_focus,
                "participant_ids": room.participant_ids,
                "representative_ids": room.representative_ids,
                "synthesis": {
                    "home_probability": room.synthesis_home_probability,
                    "confidence": room.synthesis_confidence,
                    "text": room.synthesis,
                },
                "claims": [_trace_claim(claim) for claim in room.claims],
            }
            for room in result.rooms
        ],
        "final_chamber": [_trace_claim(claim) for claim in result.claims],
        "dispute_edges": [_trace_dispute(claim) for claim in all_claims if claim.dispute],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_vote_trace(path: Path, result: RoundResult) -> None:
    decision = result.collective_decision
    payload = {
        "round_id": result.round_id,
        "note": (
            "raw_forecast_sides are actual bet/pick votes; raw_prediction_winners are probability-implied "
            "match winners from each ant's post-debate probability."
        ),
        "method": decision.method,
        "final_prediction": decision.prediction,
        "recommendation": decision.recommendation,
        "vote_breakdown": decision.vote_breakdown,
        "top_supporters": decision.top_supporters,
        "agent_votes": decision.agent_votes,
        "agent_predictions": decision.agent_predictions,
        "forecasts": [forecast.to_dict() for forecast in result.forecasts],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_kg_summary(path: Path, result: RoundResult) -> None:
    all_claims = [claim for finding in result.findings for claim in finding.evidence_claims]
    entity_counts = Counter(entity.entity_type for entity in result.world_graph.entities)
    relationship_counts = Counter(relationship.relation_type for relationship in result.world_graph.relationships)
    source_domains = sorted({str(claim.get("source_domain") or "") for claim in all_claims if claim.get("source_domain")})
    coverage = _scouting_coverage_audit(all_claims)
    team_coverage = _team_scouting_coverage_audit(result)
    backlog = _scouting_backlog_audit(team_coverage)
    integrity = _kg_integrity_audit(result)
    readiness = _kg_readiness_audit(
        result,
        coverage=coverage,
        team_coverage=team_coverage,
        scouting_backlog=backlog,
        integrity=integrity,
    )
    payload = {
        "round_id": result.round_id,
        "schema_version": KG_SCHEMA_VERSION,
        "graph": {
            "graph_id": result.world_graph.graph_id,
            "entity_count": len(result.world_graph.entities),
            "relationship_count": len(result.world_graph.relationships),
            "entity_counts": dict(sorted(entity_counts.items())),
            "relationship_counts": dict(sorted(relationship_counts.items())),
        },
        "evidence": {
            "finding_count": len(result.findings),
            "evidence_claim_count": len(all_claims),
            "claim_types": dict(_counter(claim.get("claim_type") for claim in all_claims)),
            "claim_impacts": dict(_counter(claim.get("impact") for claim in all_claims)),
            "metric_claim_count": sum(1 for claim in all_claims if claim.get("metrics")),
        },
        "sources": {
            "source_types": dict(Counter(finding.source_type for finding in result.findings)),
            "access_levels": dict(Counter(finding.access_level for finding in result.findings)),
            "source_domains": source_domains,
            "source_quality": dict(_counter(claim.get("source_quality") for claim in all_claims)),
            "source_kind": dict(_counter(claim.get("source_kind") for claim in all_claims)),
        },
        "knowledge_views": {
            "count": len(result.knowledge_views),
            "access_tiers": dict(Counter(view.access_tier for view in result.knowledge_views)),
            "avg_visible_findings": _average_visible_findings(result),
        },
        "coverage": {
            "required_claim_type_coverage": coverage.get("required_claim_type_coverage"),
            "present_required_claim_types": coverage.get("present_required_claim_types"),
            "missing_required_claim_types": coverage.get("missing_required_claim_types"),
            "teams_with_missing_required_claims": team_coverage.get("teams_with_missing_required_claims"),
        },
        "backlog": {
            "item_count": backlog.get("item_count", 0),
            "items": list(backlog.get("items") or [])[:20],
        },
        "readiness": readiness,
        "integrity": {
            "passes": integrity.get("passes"),
            "orphan_relationship_count": integrity.get("orphan_relationship_count"),
            "duplicate_evidence_claim_group_count": integrity.get("duplicate_evidence_claim_group_count"),
            "summarizes_evidence_claim_missing_target_count": integrity.get(
                "summarizes_evidence_claim_missing_target_count"
            ),
        },
        "admission": _kg_admission_audit(result),
        "findings": [_scout_audit_row(finding) for finding in result.findings],
        "files": {
            "world_graph": "world_graph.json",
            "kg_manifest": "kg_manifest.json",
            "scouting_audit": "scouting_audit.json",
            "knowledge_views": "knowledge_views.json",
            "findings": "findings.json",
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_run_report(path: Path, match: MatchContext, result: RoundResult) -> None:
    summary = result.summary
    vote_breakdown = result.collective_decision.vote_breakdown
    entity_counts = Counter(entity.entity_type for entity in result.world_graph.entities)
    all_claims = [claim for finding in result.findings for claim in finding.evidence_claims]
    coverage = _scouting_coverage_audit(all_claims)
    team_coverage = _team_scouting_coverage_audit(result)
    backlog = _scouting_backlog_audit(team_coverage)
    integrity = _kg_integrity_audit(result)
    readiness = _kg_readiness_audit(
        result,
        coverage=coverage,
        team_coverage=team_coverage,
        scouting_backlog=backlog,
        integrity=integrity,
    )
    lines = [
        f"# Run Report: {result.round_id}",
        "",
        "## Match",
        "",
        f"- Fixture: {match.home_team} vs {match.away_team}",
        f"- Schedule: {match.match_date} {match.match_time}".strip(),
        f"- Venue: {match.venue_name or 'n/a'}",
        "",
        "## Health",
        "",
        f"- Participants: {len(result.forecasts)} ants",
        f"- KG readiness: {readiness.get('status')} (integrity_passes={integrity.get('passes')})",
        f"- Debate: {len(result.rooms)} rooms, {summary.get('room_claims', 0)} room claims, {summary.get('final_claims', 0)} final claims",
        f"- Disputes: {summary.get('dispute_count', 0)} disputes, {summary.get('subject_shift_count', 0)} subject shifts",
        f"- Vote participation: {summary.get('participating_bets', 0)}/{summary.get('population', 0)}",
        "",
        "## KG",
        "",
        f"- Findings: {len(result.findings)}",
        f"- Evidence claims: {len(all_claims)}",
        f"- Entity counts: {_counter_text(entity_counts)}",
        f"- Required coverage: {coverage.get('required_claim_type_coverage')}",
        f"- Missing required claim types: {', '.join(coverage.get('missing_required_claim_types') or []) or 'none'}",
        f"- Scouting backlog: {backlog.get('item_count', 0)} items",
        "",
        "## Participants",
        "",
        f"- Models: {_counter_text(Counter(forecast.model for forecast in result.forecasts if forecast.model))}",
        f"- Risk profiles: {_counter_text(Counter(forecast.risk_profile for forecast in result.forecasts))}",
        f"- Access tiers: {_counter_text(Counter(forecast.access_tier for forecast in result.forecasts))}",
        "",
        "## Debate",
        "",
    ]
    for room in result.rooms:
        lines.append(
            f"- {room.room_id}: {len(room.participant_ids)} ants, reps={len(room.representative_ids)}, "
            f"focus={room.evidence_focus}, lean={_room_lean(room.synthesis_home_probability)}, "
            f"claims={len(room.claims)}"
        )

    lines.extend(
        [
            "",
            "## Vote",
            "",
            f"- Final recommendation: {result.collective_decision.recommendation.get('side')} ({result.collective_decision.recommendation.get('winner')})",
            f"- Confidence: {result.collective_decision.prediction.get('confidence')}",
            f"- Forecast vote distribution: {_counter_text(vote_breakdown.get('raw_forecast_sides') or {})}",
            f"- Probability lean distribution: {_counter_text(vote_breakdown.get('raw_prediction_winners') or {})}",
            f"- Weighted support: {_counter_text(vote_breakdown.get('weighted_side_support') or {})}",
            "",
            "## Main Files",
            "",
            "- `run_report.md`: this audit.",
            "- `kg_summary.json`: compact KG/source/readiness summary.",
            "- `participants.json`: per-ant identity, rooms, debate activity, vote, and model.",
            "- `debate_trace.json`: structured room and final chamber replay.",
            "- `vote_trace.json`: complete weighted vote and prediction trace.",
            "- `world_graph.json` / `kg_manifest.json`: graph payload and load manifest.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _split_windows(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _forecast_datafeed_focus(forecast) -> list[str]:
    interests = list(getattr(forecast, "datafeed_interests", []) or [])
    if interests:
        return interests
    weights = getattr(forecast, "source_weights", {}) or {}
    if isinstance(weights, dict):
        ranked = sorted(weights.items(), key=lambda item: float(item[1] or 0.0), reverse=True)
        return [str(label) for label, value in ranked if float(value or 0.0) >= 0.18]
    return []


def _trace_claim(claim) -> dict:
    return {
        "claim_id": _claim_memory_id(claim),
        "speaker_id": claim.speaker_id,
        "speaker_name": claim.speaker_name,
        "genome_id": claim.genome_id,
        "model": claim.model,
        "persona": claim.persona,
        "phase": claim.debate_phase or "final",
        "room_id": claim.room_id or "global",
        "role": claim.debate_role or "speaker",
        "access_tier": claim.access_tier,
        "visible_findings": claim.visible_findings,
        "claim_type": claim.claim_type,
        "selection_reason": claim.selection_reason,
        "direction": claim.direction,
        "stated_home_probability": claim.stated_home_probability,
        "confidence": claim.confidence,
        "evidence_tags": claim.evidence_tags,
        "evidence_subjects": _claim_evidence_subjects(claim),
        "referenced_evidence": [_compact_evidence(evidence) for evidence in claim.referenced_evidence],
        "dispute": claim.dispute,
        "diagnostics": claim.diagnostics,
        "message": claim.message,
    }


def _trace_dispute(claim) -> dict:
    dispute = dict(claim.dispute)
    return {
        "source_claim_id": _claim_memory_id(claim),
        "source_speaker_id": claim.speaker_id,
        "source_speaker_name": claim.speaker_name,
        "source_genome_id": claim.genome_id,
        "target_claim_id": dispute.get("target_claim_id"),
        "target_speaker_id": dispute.get("target_speaker_id"),
        "target_speaker_name": dispute.get("target_speaker_name"),
        "target_genome_id": dispute.get("target_genome_id"),
        "critique_type": dispute.get("critique_type"),
        "critique_label": dispute.get("critique_label"),
        "critique_summary": dispute.get("critique_summary"),
        "probability_gap": dispute.get("probability_gap"),
        "target_subject": dispute.get("target_subject"),
        "counter_subject": dispute.get("counter_subject"),
        "target_source_quality": dispute.get("target_source_quality"),
        "target_excerpt": dispute.get("target_excerpt"),
    }


def _compact_evidence(evidence: dict) -> dict:
    return {
        "finding_id": evidence.get("finding_id"),
        "scout_name": evidence.get("scout_name"),
        "source_type": evidence.get("source_type"),
        "access_level": evidence.get("access_level"),
        "claim_type": evidence.get("claim_type"),
        "impact": evidence.get("impact"),
        "subject": evidence.get("subject") or evidence.get("team") or evidence.get("player"),
        "team": evidence.get("team"),
        "player": evidence.get("player"),
        "source_title": evidence.get("source_title"),
        "source_url": evidence.get("source_url"),
        "source_domain": evidence.get("source_domain"),
        "source_kind": evidence.get("source_kind"),
        "source_quality": evidence.get("source_quality"),
        "source_recency_bucket": evidence.get("source_recency_bucket"),
        "metrics": evidence.get("metrics") or {},
        "claim": _short_field(evidence.get("claim"), limit=320),
    }


def _short_field(value: object, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    clipped = text[: limit - 3].rstrip(" .")
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip(" .")
    return f"{clipped}..."


def _average_visible_findings(result: RoundResult) -> float:
    if not result.knowledge_views:
        return 0.0
    return round(
        sum(len(view.visible_findings) for view in result.knowledge_views) / len(result.knowledge_views),
        4,
    )


def _counter_text(values) -> str:
    if not values:
        return "none"
    items = values.items() if hasattr(values, "items") else Counter(values).items()
    return ", ".join(f"{key}={value}" for key, value in sorted(items, key=lambda item: str(item[0])))


def _write_collective_decision(path: Path, result: RoundResult) -> None:
    payload = result.collective_decision.to_dict()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_compact_collective_decision(path: Path, result: RoundResult) -> None:
    decision = result.collective_decision
    payload = {
        "round_id": decision.round_id,
        "match": {
            "home_team": decision.match.get("home_team", ""),
            "away_team": decision.match.get("away_team", ""),
        },
        "method": _compact_method(decision.method),
        "match_call": decision.match_call,
        "prediction": decision.prediction,
        "recommendation": decision.recommendation,
        "score_projection": _compact_score_projection(decision.score_projection),
        "vote_breakdown": _compact_vote_breakdown(decision.vote_breakdown),
        "top_supporters": [_compact_supporter(item) for item in decision.top_supporters],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compact_supporter(item: dict) -> dict:
    return {
        "agent_id": item.get("agent_id", ""),
        "wallet_address": item.get("wallet_address", ""),
        "ens_name": item.get("ens_name", ""),
        "genome_id": item.get("genome_id", ""),
        "persona": item.get("persona", ""),
        "access_tier": item.get("access_tier", ""),
        "risk_profile": item.get("risk_profile", ""),
        "world_verified": item.get("world_verified", False),
        "prediction": item.get("prediction", {}),
        "forecast_side": item.get("forecast_side", ""),
        "value": _edge_value_label(float(item.get("edge") or 0.0)),
        "weight": item.get("weight", 0.0),
        "reason": _compact_reason(str(item.get("decision_reason") or "")),
    }


def _compact_method(method: dict) -> dict:
    return {
        "name": method.get("name", ""),
        "description": method.get("description", ""),
        "access_multipliers": method.get("access_multipliers", {}),
        "world_verified_multiplier": method.get("world_verified_multiplier", 1.0),
        "verified_lineage_multiplier": method.get("verified_lineage_multiplier", 1.0),
    }


def _compact_score_projection(score_projection: dict) -> dict:
    return {
        "home_team": score_projection.get("home_team", ""),
        "away_team": score_projection.get("away_team", ""),
        "most_likely_score": score_projection.get("most_likely_score", {}),
        "note": "Goal estimates are lightweight and should be treated as a score call, not a full goal model.",
    }


def _compact_vote_breakdown(vote_breakdown: dict) -> dict:
    return {
        "ants": vote_breakdown.get("ants", 0),
        "raw_forecast_sides": vote_breakdown.get("raw_forecast_sides", {}),
        "raw_prediction_winners": vote_breakdown.get("raw_prediction_winners", {}),
        "raw_scorelines": vote_breakdown.get("raw_scorelines", {}),
        "raw_total_goals": vote_breakdown.get("raw_total_goals", {}),
        "weighted_side_support": vote_breakdown.get("weighted_side_support", {}),
        "support_margin": vote_breakdown.get("support_margin", 0.0),
    }


def _compact_reason(reason: str) -> str:
    if "top weights" in reason:
        sources = reason.split("top weights", 1)[1].strip()
        labels = []
        for part in sources.split(","):
            label = part.strip().split("=", 1)[0].strip()
            if label:
                labels.append(label)
        if labels:
            return f"Value signal supported by {', '.join(labels[:2])} inputs."
    if "below threshold" in reason:
        return "No clean value signal after the debate adjustment."
    if "clears threshold" in reason:
        return "Value signal survived the debate adjustment."
    return reason


def _edge_value_label(edge: float) -> str:
    value = abs(edge)
    if value >= 0.055:
        return "strong"
    if value >= 0.025:
        return "medium"
    if value > 0:
        return "thin"
    return "none"


def _write_findings(path: Path, result: RoundResult) -> None:
    findings = [finding.to_dict() for finding in result.findings]
    path.write_text(json.dumps(findings, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_scouting_audit(path: Path, result: RoundResult) -> None:
    all_claims = [claim for finding in result.findings for claim in finding.evidence_claims]
    source_urls = {str(claim.get("source_url") or "") for claim in all_claims if claim.get("source_url")}
    source_domains = {str(claim.get("source_domain") or "") for claim in all_claims if claim.get("source_domain")}
    coverage = _scouting_coverage_audit(all_claims)
    team_coverage = _team_scouting_coverage_audit(result)
    scouting_backlog = _scouting_backlog_audit(team_coverage)
    kg_integrity = _kg_integrity_audit(result)
    kg_admission = _kg_admission_audit(result)
    audit = {
        "round_id": result.round_id,
        "finding_count": len(result.findings),
        "evidence_claim_count": len(all_claims),
        "unique_source_count": len(source_urls),
        "unique_source_domain_count": len(source_domains),
        "claim_types": dict(_counter(claim.get("claim_type") for claim in all_claims)),
        "claim_impacts": dict(_counter(claim.get("impact") for claim in all_claims)),
        "metric_claim_count": sum(1 for claim in all_claims if claim.get("metrics")),
        "metric_keys": dict(_counter(key for claim in all_claims for key in (claim.get("metrics") or {}).keys())),
        "source_quality": dict(_counter(claim.get("source_quality") for claim in all_claims)),
        "source_kind": dict(_counter(claim.get("source_kind") for claim in all_claims)),
        "source_recency": dict(_counter(claim.get("source_recency_bucket") for claim in all_claims)),
        "coverage": coverage,
        "team_coverage": team_coverage,
        "scouting_backlog": scouting_backlog,
        "access_levels": dict(_counter(finding.access_level for finding in result.findings)),
        "source_types": dict(_counter(finding.source_type for finding in result.findings)),
        "kg_admission": kg_admission,
        "kg_contribution": _kg_contribution_audit(result),
        "kg_integrity": kg_integrity,
        "kg_readiness": _kg_readiness_audit(
            result,
            coverage=coverage,
            team_coverage=team_coverage,
            scouting_backlog=scouting_backlog,
            integrity=kg_integrity,
        ),
        "findings": [_scout_audit_row(finding) for finding in result.findings],
    }
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _kg_integrity_audit(result: RoundResult) -> dict:
    entity_ids = {entity.entity_id for entity in result.world_graph.entities}
    entity_ids_by_type = {
        entity_type: {entity.entity_id for entity in result.world_graph.entities if entity.entity_type == entity_type}
        for entity_type in {
            "evidence_claim",
            "team_match_profile",
            "player_match_profile",
            "source_domain_profile",
            "scout_match_profile",
        }
    }
    orphan_relationships = [
        {
            "source_id": relationship.source_id,
            "relation_type": relationship.relation_type,
            "target_id": relationship.target_id,
            "missing": [
                side
                for side, entity_id in (("source", relationship.source_id), ("target", relationship.target_id))
                if entity_id not in entity_ids
            ],
        }
        for relationship in result.world_graph.relationships
        if relationship.source_id not in entity_ids or relationship.target_id not in entity_ids
    ]
    lineage_relationships = [
        relationship
        for relationship in result.world_graph.relationships
        if relationship.relation_type == "summarizes_evidence_claim"
    ]
    lineage_missing_targets = [
        relationship.target_id
        for relationship in lineage_relationships
        if relationship.target_id not in entity_ids_by_type["evidence_claim"]
    ]
    profile_rows = []
    for entity_type in ("team_match_profile", "player_match_profile", "source_domain_profile", "scout_match_profile"):
        profiles = [entity for entity in result.world_graph.entities if entity.entity_type == entity_type]
        missing_claim_ids = [
            entity.entity_id
            for entity in profiles
            if int(entity.attributes.get("claim_count") or 0) > 0 and not entity.attributes.get("evidence_claim_ids")
        ]
        profile_rows.append(
            {
                "entity_type": entity_type,
                "count": len(profiles),
                "with_evidence_claim_ids": sum(1 for entity in profiles if entity.attributes.get("evidence_claim_ids")),
                "missing_evidence_claim_ids": missing_claim_ids[:20],
            }
        )
    passes = not orphan_relationships and not lineage_missing_targets and all(
        not row["missing_evidence_claim_ids"] for row in profile_rows
    )
    duplicate_claim_groups = _duplicate_evidence_claim_groups(result)
    return {
        "passes": passes,
        "entity_count": len(result.world_graph.entities),
        "relationship_count": len(result.world_graph.relationships),
        "orphan_relationship_count": len(orphan_relationships),
        "orphan_relationships": orphan_relationships[:20],
        "summarizes_evidence_claim_count": len(lineage_relationships),
        "summarizes_evidence_claim_missing_target_count": len(lineage_missing_targets),
        "summarizes_evidence_claim_missing_targets": sorted(set(lineage_missing_targets))[:20],
        "profile_lineage": profile_rows,
        "duplicate_evidence_claim_group_count": len(duplicate_claim_groups),
        "duplicate_evidence_claim_count": sum(group["count"] for group in duplicate_claim_groups),
        "duplicate_evidence_claim_groups": duplicate_claim_groups[:20],
    }


def _duplicate_evidence_claim_groups(result: RoundResult) -> list[dict]:
    grouped: dict[tuple[str, str, str, str, str], list[object]] = {}
    for entity in result.world_graph.entities:
        if entity.entity_type != "evidence_claim":
            continue
        key = _evidence_claim_duplicate_key(entity.attributes)
        if key is None:
            continue
        grouped.setdefault(key, []).append(entity)

    rows = []
    for key, entities in grouped.items():
        if len(entities) < 2:
            continue
        first = entities[0]
        attrs = first.attributes
        rows.append(
            {
                "claim_type": key[0],
                "team": key[1],
                "subject": key[2],
                "source": key[3],
                "claim": str(attrs.get("claim") or "")[:220],
                "count": len(entities),
                "evidence_claim_ids": sorted(str(entity.entity_id) for entity in entities)[:20],
                "finding_ids": sorted(
                    {
                        str(entity.attributes.get("finding_id"))
                        for entity in entities
                        if entity.attributes.get("finding_id")
                    }
                ),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["count"]), row["claim_type"], row["team"], row["subject"]))


def _evidence_claim_duplicate_key(attrs: dict) -> tuple[str, str, str, str, str] | None:
    claim_type = _normalize_duplicate_text(attrs.get("claim_type"))
    claim = _normalize_duplicate_text(attrs.get("claim"))
    if not claim_type or not claim:
        return None
    team = _normalize_duplicate_text(attrs.get("team"))
    subject = _normalize_duplicate_text(attrs.get("player") or attrs.get("subject"))
    source = _normalize_duplicate_text(attrs.get("source_url") or attrs.get("source_title"))
    return (claim_type, team, subject, source, claim)


def _normalize_duplicate_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower()
    if text in {"none", "unknown", "null"}:
        return ""
    return re.sub(r"\s+", " ", text)


def _kg_readiness_audit(
    result: RoundResult,
    *,
    coverage: dict | None = None,
    team_coverage: dict | None = None,
    scouting_backlog: dict | None = None,
    integrity: dict | None = None,
) -> dict:
    graph_claims = [
        entity.attributes
        for entity in result.world_graph.entities
        if entity.entity_type == "evidence_claim"
    ]
    coverage = coverage or _scouting_coverage_audit(
        [claim for finding in getattr(result, "findings", []) for claim in finding.evidence_claims] or graph_claims
    )
    team_coverage = team_coverage or _team_scouting_coverage_audit(result)
    scouting_backlog = scouting_backlog or _scouting_backlog_audit(team_coverage)
    integrity = integrity or _kg_integrity_audit(result)
    entity_counts = Counter(entity.entity_type for entity in result.world_graph.entities)
    graph_claim_types = Counter(
        str(entity.attributes.get("claim_type") or "")
        for entity in result.world_graph.entities
        if entity.entity_type == "evidence_claim" and entity.attributes.get("claim_type")
    )
    forbidden_claim_counts = {
        claim_type: graph_claim_types.get(claim_type, 0)
        for claim_type in sorted(KG_FORBIDDEN_CLAIM_TYPES)
        if graph_claim_types.get(claim_type, 0)
    }
    required_entity_types = [
        "match",
        "team",
        "finding",
        "evidence_claim",
        "scouting_topic",
        "team_scouting_topic",
        "team_match_profile",
        "source_domain_profile",
    ]
    missing_entity_types = [
        entity_type for entity_type in required_entity_types if entity_counts.get(entity_type, 0) <= 0
    ]
    blocking_reasons = []
    if not integrity.get("passes"):
        blocking_reasons.append("kg_integrity_failed")
    if missing_entity_types:
        blocking_reasons.append("missing_required_entity_types")
    if forbidden_claim_counts:
        blocking_reasons.append("forbidden_claim_types_present")

    missing_required_claim_types = list(coverage.get("missing_required_claim_types") or [])
    backlog_count = int(scouting_backlog.get("item_count") or 0)
    freshness_backlog_count = sum(
        1 for item in scouting_backlog.get("items", []) if str(item.get("status") or "") == "needs_fresh_rescout"
    )
    kg_load_ready = not blocking_reasons
    scouting_complete = kg_load_ready and not missing_required_claim_types and backlog_count == 0
    status = (
        "ready_complete"
        if scouting_complete
        else ("load_ready_with_scouting_backlog" if kg_load_ready else "blocked_for_kg_load")
    )
    return {
        "status": status,
        "kg_load_ready": kg_load_ready,
        "scouting_complete": scouting_complete,
        "blocking_reasons": blocking_reasons,
        "required_entity_types": required_entity_types,
        "missing_required_entity_types": missing_entity_types,
        "forbidden_claim_types": sorted(KG_FORBIDDEN_CLAIM_TYPES),
        "forbidden_claim_counts": forbidden_claim_counts,
        "required_claim_type_coverage": coverage.get("required_claim_type_coverage"),
        "missing_required_claim_types": missing_required_claim_types,
        "teams_with_missing_required_claims": list(team_coverage.get("teams_with_missing_required_claims") or []),
        "scouting_backlog_count": backlog_count,
        "freshness_backlog_count": freshness_backlog_count,
        "kg_integrity_passes": bool(integrity.get("passes")),
        "lineage_relation_count": int(integrity.get("summarizes_evidence_claim_count") or 0),
    }


def _kg_admission_audit(result: RoundResult) -> dict:
    raw_claim_count = 0
    admitted_claim_count = 0
    rejected_rows = []
    reason_counts: Counter[str] = Counter()
    rejected_by_claim_type: Counter[str] = Counter()
    rejected_by_scout: Counter[str] = Counter()

    for finding in getattr(result, "findings", []):
        for claim in finding.evidence_claims:
            raw_claim_count += 1
            reasons = _evidence_rejection_reasons(claim)
            if not reasons:
                admitted_claim_count += 1
                continue
            reason_counts.update(reasons)
            claim_type = str(claim.get("claim_type") or "missing")
            scout_name = str(finding.scout_name or "unknown")
            rejected_by_claim_type[claim_type] += 1
            rejected_by_scout[scout_name] += 1
            rejected_rows.append(
                {
                    "finding_id": finding.finding_id,
                    "scout_name": scout_name,
                    "claim_type": claim_type,
                    "team": str(claim.get("team") or ""),
                    "subject": str(claim.get("player") or claim.get("subject") or ""),
                    "source": str(claim.get("source_url") or claim.get("source_title") or ""),
                    "reasons": reasons,
                    "claim": str(claim.get("claim") or "")[:220],
                }
            )

    rejected_claim_count = len(rejected_rows)
    return {
        "raw_claim_count": raw_claim_count,
        "admitted_claim_count": admitted_claim_count,
        "rejected_claim_count": rejected_claim_count,
        "admission_rate": None if raw_claim_count == 0 else round(admitted_claim_count / raw_claim_count, 4),
        "rejection_reasons": dict(sorted(reason_counts.items())),
        "rejected_by_claim_type": dict(sorted(rejected_by_claim_type.items())),
        "rejected_by_scout": dict(sorted(rejected_by_scout.items())),
        "rejected_claims": rejected_rows[:20],
        "policy": {
            "requires": [
                "claim_type",
                "claim",
                "source_url_or_title",
                "non_weak_source",
                "non_weak_search_aggregate",
                "known_impact",
            ],
            "write_policy": "Rejected claims are not materialized as evidence_claim nodes; re-scout instead of filling placeholders.",
        },
    }


def _kg_contribution_audit(result: RoundResult) -> dict:
    entity_counts = Counter(entity.entity_type for entity in result.world_graph.entities)
    relationship_counts = Counter(relationship.relation_type for relationship in result.world_graph.relationships)
    names_by_type = {
        entity_type: sorted(
            entity.name
            for entity in result.world_graph.entities
            if entity.entity_type == entity_type and entity.name
        )
        for entity_type in (
            "scout",
            "claim_type",
            "claim_impact",
            "claim_quality",
            "scouting_topic",
            "team_scouting_topic",
            "team_match_profile",
            "scouting_gap",
            "player_match_profile",
            "source_domain",
            "source_domain_profile",
            "scout_match_profile",
            "source_kind",
            "source_quality",
            "source_recency",
        )
    }
    return {
        "entity_counts": dict(entity_counts),
        "relationship_counts": dict(relationship_counts),
        "scouts": names_by_type["scout"],
        "claim_types": names_by_type["claim_type"],
        "claim_impacts": names_by_type["claim_impact"],
        "claim_qualities": names_by_type["claim_quality"],
        "scouting_topics": names_by_type["scouting_topic"],
        "team_scouting_topics": names_by_type["team_scouting_topic"],
        "team_match_profiles": names_by_type["team_match_profile"],
        "scouting_gaps": names_by_type["scouting_gap"],
        "player_match_profiles": names_by_type["player_match_profile"],
        "source_domains": names_by_type["source_domain"],
        "source_domain_profiles": names_by_type["source_domain_profile"],
        "scout_match_profiles": names_by_type["scout_match_profile"],
        "source_kinds": names_by_type["source_kind"],
        "source_qualities": names_by_type["source_quality"],
        "source_recencies": names_by_type["source_recency"],
    }


def _scout_audit_row(finding) -> dict:
    claims = list(finding.evidence_claims)
    source_urls = {str(claim.get("source_url") or "") for claim in claims if claim.get("source_url")}
    source_domains = sorted({str(claim.get("source_domain") or "") for claim in claims if claim.get("source_domain")})
    return {
        "finding_id": finding.finding_id,
        "scout_name": finding.scout_name,
        "access_level": finding.access_level,
        "source_type": finding.source_type,
        "finding_name": finding.finding_name,
        "confidence": finding.confidence,
        "home_probability": finding.home_probability,
        "evidence_claim_count": len(claims),
        "unique_source_count": len(source_urls),
        "source_domains": source_domains[:12],
        "claim_types": dict(_counter(claim.get("claim_type") for claim in claims)),
        "claim_impacts": dict(_counter(claim.get("impact") for claim in claims)),
        "metric_claim_count": sum(1 for claim in claims if claim.get("metrics")),
        "metric_keys": dict(_counter(key for claim in claims for key in (claim.get("metrics") or {}).keys())),
        "source_quality": dict(_counter(claim.get("source_quality") for claim in claims)),
        "source_kind": dict(_counter(claim.get("source_kind") for claim in claims)),
        "source_recency": dict(_counter(claim.get("source_recency_bucket") for claim in claims)),
        "has_metric_claims": any(claim.get("metrics") for claim in claims),
        "has_strong_or_official_sources": any(
            claim.get("source_quality") == "strong"
            or claim.get("source_kind") in {"official", "stats", "news", "reference"}
            for claim in claims
        ),
    }


def _scouting_coverage_audit(claims: list[dict]) -> dict:
    claim_rows_by_type: dict[str, list[dict]] = {}
    for claim in claims:
        claim_type = str(claim.get("claim_type") or "")
        if claim_type:
            claim_rows_by_type.setdefault(claim_type, []).append(claim)
    quality_by_type = {
        claim_type: _claim_type_quality_from_claims(claim_type, claim_rows_by_type.get(claim_type, []))
        for claim_type in SCOUTING_REQUIRED_CLAIM_TYPES
    }
    missing_types = [
        claim_type
        for claim_type in SCOUTING_REQUIRED_CLAIM_TYPES
        if quality_by_type[claim_type]["coverage_status"] != "covered"
    ]
    source_domains = {str(claim.get("source_domain") or "") for claim in claims if claim.get("source_domain")}
    strong_or_official_claims = [
        claim
        for claim in claims
        if claim.get("source_quality") == "strong"
        or claim.get("source_kind") in {"official", "stats", "news", "reference"}
    ]
    dated_claims = [claim for claim in claims if claim.get("source_published_date")]
    return {
        "required_claim_types": list(SCOUTING_REQUIRED_CLAIM_TYPES),
        "present_required_claim_types": [
            claim_type
            for claim_type in SCOUTING_REQUIRED_CLAIM_TYPES
            if quality_by_type[claim_type]["coverage_status"] == "covered"
        ],
        "missing_required_claim_types": missing_types,
        "required_claim_type_quality": quality_by_type,
        "required_claim_type_coverage": round(
            (len(SCOUTING_REQUIRED_CLAIM_TYPES) - len(missing_types)) / len(SCOUTING_REQUIRED_CLAIM_TYPES),
            4,
        ),
        "unique_source_domains": len(source_domains),
        "strong_or_official_claim_count": len(strong_or_official_claims),
        "weak_claim_count": sum(1 for claim in claims if claim.get("source_quality") == "weak"),
        "claims_with_metrics": sum(1 for claim in claims if claim.get("metrics")),
        "dated_claim_count": len(dated_claims),
        "recent_30d_claim_count": sum(
            1 for claim in claims if claim.get("source_recency_bucket") in {"last_7_days", "last_30_days"}
        ),
    }


def _claim_type_quality_from_claims(claim_type: str, claims: list[dict]) -> dict:
    quality_counts: Counter[str] = Counter()
    for claim in claims:
        metrics = claim.get("metrics") if isinstance(claim.get("metrics"), dict) else {}
        if metrics:
            quality_counts["metric_backed"] += 1
        if claim.get("source_url"):
            quality_counts["source_locked"] += 1
        if claim.get("player"):
            quality_counts["player_specific"] += 1
        if metrics.get("availability_status"):
            quality_counts["availability_status"] += 1
        if metrics.get("historical_result_signal") == "explicit_score":
            quality_counts["explicit_score"] += 1
        if metrics.get("historical_record_signal"):
            quality_counts["h2h_record"] += 1
        if claim_type == "recent_form" and any(
            key in metrics
            for key in (
                "recent_sample_matches",
                "recent_wins",
                "recent_draws",
                "recent_losses",
                "unbeaten_matches",
                "winning_streak_matches",
            )
        ):
            quality_counts["recent_results_window"] += 1
        if claim_type == "player_form" and any(
            key in metrics
            for key in ("goals", "assists", "goal_contributions", "appearances", "minutes", "starts", "xg", "xa")
        ):
            quality_counts["season_output"] += 1
        if metrics.get("formation"):
            quality_counts["formation_signal"] += 1
        if metrics.get("lineup_signal"):
            quality_counts["lineup_signal"] += 1
    status, reasons = scouting_topic_quality(
        claim_type,
        claim_count=len(claims),
        metric_claim_count=sum(1 for claim in claims if claim.get("metrics")),
        player_count=len({str(claim.get("player") or "") for claim in claims if claim.get("player")}),
        recent_30d_claim_count=sum(
            1 for claim in claims if claim.get("source_recency_bucket") in {"last_7_days", "last_30_days"}
        ),
        strong_or_official_claim_count=sum(
            1
            for claim in claims
            if claim.get("source_quality") == "strong"
            or claim.get("source_kind") in {"official", "stats", "news", "reference"}
        ),
        claim_quality_counts=dict(quality_counts),
    )
    return {
        "coverage_status": "covered" if status == "usable" else status,
        "quality_status": status,
        "quality_reasons": reasons,
        "claim_count": len(claims),
        "metric_claim_count": sum(1 for claim in claims if claim.get("metrics")),
    }


def _team_scouting_coverage_audit(result: RoundResult) -> dict:
    rows: dict[str, dict] = {}
    for entity in result.world_graph.entities:
        if entity.entity_type != "team_scouting_topic":
            continue
        attrs = entity.attributes
        team = str(attrs.get("team") or "")
        claim_type = str(attrs.get("claim_type") or "")
        if not team or not claim_type:
            continue
        row = rows.setdefault(
            team,
            {
                "team": team,
                "side": str(attrs.get("side") or ""),
                "required_claim_types": list(SCOUTING_REQUIRED_CLAIM_TYPES),
                "claim_types": {},
                "present_required_claim_types": [],
                "missing_required_claim_types": [],
                "claim_count": 0,
                "metric_claim_count": 0,
                "unique_source_count": 0,
                "player_count": 0,
                "scout_names": [],
                "extraction_methods": {},
                "claim_quality_counts": {},
            },
        )
        claim_count = int(attrs.get("claim_count") or 0)
        metric_claim_count = int(attrs.get("metric_claim_count") or 0)
        unique_source_count = int(attrs.get("unique_source_count") or 0)
        player_count = int(attrs.get("player_count") or 0)
        row["claim_types"][claim_type] = {
            "entity_id": entity.entity_id,
            "required": bool(attrs.get("required")),
            "coverage_status": str(attrs.get("coverage_status") or "missing"),
            "quality_status": str(attrs.get("quality_status") or attrs.get("coverage_status") or "missing"),
            "quality_reasons": list(attrs.get("quality_reasons") or []),
            "claim_count": claim_count,
            "unique_source_count": unique_source_count,
            "metric_claim_count": metric_claim_count,
            "player_count": player_count,
            "freshness_required": bool(attrs.get("freshness_required")),
            "freshness_status": str(attrs.get("freshness_status") or "missing"),
            "dated_claim_count": int(attrs.get("dated_claim_count") or 0),
            "recent_30d_claim_count": int(attrs.get("recent_30d_claim_count") or 0),
            "strong_or_official_claim_count": int(attrs.get("strong_or_official_claim_count") or 0),
            "source_strength_status": str(attrs.get("source_strength_status") or "missing"),
            "scout_count": int(attrs.get("scout_count") or 0),
            "scout_names": list(attrs.get("scout_names") or []),
            "extraction_methods": dict(attrs.get("extraction_methods") or {}),
            "claim_quality_counts": dict(attrs.get("claim_quality_counts") or {}),
        }
        row["claim_count"] += claim_count
        row["metric_claim_count"] += metric_claim_count
        row["unique_source_count"] += unique_source_count
        row["player_count"] += player_count
        row["scout_names"] = sorted(set(row["scout_names"]) | set(attrs.get("scout_names") or []))
        _merge_counter_dict(row["extraction_methods"], attrs.get("extraction_methods") or {})
        _merge_counter_dict(row["claim_quality_counts"], attrs.get("claim_quality_counts") or {})

    for row in rows.values():
        claim_types = row["claim_types"]
        present = [
            claim_type
            for claim_type in SCOUTING_REQUIRED_CLAIM_TYPES
            if claim_types.get(claim_type, {}).get("coverage_status") == "covered"
        ]
        missing = [claim_type for claim_type in SCOUTING_REQUIRED_CLAIM_TYPES if claim_type not in present]
        row["present_required_claim_types"] = present
        row["missing_required_claim_types"] = missing
        row["required_claim_type_coverage"] = round(
            (len(SCOUTING_REQUIRED_CLAIM_TYPES) - len(missing)) / len(SCOUTING_REQUIRED_CLAIM_TYPES),
            4,
        )

    team_rows = sorted(rows.values(), key=lambda row: (row.get("side") != "home", str(row.get("team") or "")))
    return {
        "teams": team_rows,
        "team_count": len(team_rows),
        "teams_with_missing_required_claims": [
            row["team"] for row in team_rows if row["missing_required_claim_types"]
        ],
    }


def _scouting_backlog_audit(team_coverage: dict) -> dict:
    items = []
    for row in team_coverage.get("teams", []):
        team = str(row.get("team") or "")
        side = str(row.get("side") or "")
        claim_types = row.get("claim_types") or {}
        for claim_type in row.get("missing_required_claim_types", []):
            claim_type = str(claim_type)
            recipe = SCOUTING_RESCOUT_RECIPES.get(claim_type, {})
            topic = claim_types.get(claim_type) or {}
            quality_reasons = list(topic.get("quality_reasons") or [])
            needs_fresh = "needs_recent_source" in quality_reasons
            items.append(
                {
                    "status": "needs_fresh_rescout" if needs_fresh else "needs_rescout",
                    "team": team,
                    "side": side,
                    "claim_type": claim_type,
                    "reason": "missing_required_topic" if not quality_reasons else "needs_better_evidence",
                    "quality_status": str(topic.get("quality_status") or topic.get("coverage_status") or "missing"),
                    "quality_reasons": quality_reasons,
                    "priority": int(recipe.get("priority") or 40),
                    "recommended_scout": str(recipe.get("recommended_scout") or f"{claim_type}_scout"),
                    "query_focus": str(recipe.get("query_focus") or claim_type.replace("_", " ")),
                    "target_entity_id": str(topic.get("entity_id") or ""),
                    "acceptance_criteria": list(recipe.get("acceptance_criteria") or []),
                    "write_policy": "Admit only sourced evidence_claims; keep the KG topic missing when no admissible source is found.",
                }
            )
        for claim_type, topic in claim_types.items():
            claim_type = str(claim_type)
            if claim_type not in SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES:
                continue
            if topic.get("coverage_status") != "covered" or topic.get("freshness_status") != "needs_fresh_source":
                continue
            recipe = SCOUTING_RESCOUT_RECIPES.get(claim_type, {})
            items.append(
                {
                    "status": "needs_fresh_rescout",
                    "team": team,
                    "side": side,
                    "claim_type": claim_type,
                    "priority": int(recipe.get("priority") or 40),
                    "recommended_scout": str(recipe.get("recommended_scout") or f"{claim_type}_scout"),
                    "query_focus": str(recipe.get("query_focus") or claim_type.replace("_", " ")),
                    "target_entity_id": str(topic.get("entity_id") or ""),
                    "acceptance_criteria": list(recipe.get("acceptance_criteria") or []),
                    "write_policy": "Admit only recent sourced evidence_claims for freshness-sensitive topics; keep the quality gap visible otherwise.",
                    "gap_reason": "covered_topic_without_recent_source",
                }
            )
    items.sort(key=lambda item: (-item["priority"], item["team"], item["claim_type"]))
    return {
        "item_count": len(items),
        "items": items,
        "empty_policy": "No backlog item means every required team scouting topic is covered by admissible KG evidence and no freshness-sensitive topic needs a recent source.",
    }


def _counter(values) -> Counter:
    return Counter(str(value) for value in values if value not in {None, ""})


def _merge_counter_dict(target: dict, values: dict) -> None:
    for key, value in values.items():
        if key in {None, ""}:
            continue
        try:
            amount = int(value)
        except (TypeError, ValueError):
            continue
        target[str(key)] = int(target.get(str(key), 0)) + amount


def _write_knowledge_views(path: Path, result: RoundResult) -> None:
    views = [view.to_dict() for view in result.knowledge_views]
    path.write_text(json.dumps(views, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_world_graph(path: Path, result: RoundResult) -> None:
    graph = result.world_graph.to_dict()
    graph["schema_version"] = KG_SCHEMA_VERSION
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_kg_manifest(path: Path, result: RoundResult) -> None:
    path.write_text(json.dumps(_kg_manifest(result), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _kg_manifest(result: RoundResult) -> dict:
    entity_counts = Counter(entity.entity_type for entity in result.world_graph.entities)
    relationship_counts = Counter(relationship.relation_type for relationship in result.world_graph.relationships)
    integrity = _kg_integrity_audit(result)
    readiness = _kg_readiness_audit(result, integrity=integrity)
    admission = _kg_admission_audit(result)
    entrypoint_types = [
        "match",
        "team_match_profile",
        "team_scouting_topic",
        "player_match_profile",
        "source_domain_profile",
        "scout_match_profile",
        "scouting_gap",
    ]
    required_entity_types = [
        "match",
        "team",
        "finding",
        "evidence_claim",
        "scouting_topic",
        "team_scouting_topic",
        "team_match_profile",
        "source_domain_profile",
    ]
    return {
        "schema_version": KG_SCHEMA_VERSION,
        "graph_id": result.world_graph.graph_id,
        "round_id": result.world_graph.round_id,
        "files": {
            "world_graph": "world_graph.json",
            "scouting_audit": "scouting_audit.json",
            "findings": "findings.json",
            "knowledge_views": "knowledge_views.json",
        },
        "entity_count": len(result.world_graph.entities),
        "relationship_count": len(result.world_graph.relationships),
        "entity_counts": dict(sorted(entity_counts.items())),
        "relationship_counts": dict(sorted(relationship_counts.items())),
        "entity_types": sorted(entity_counts),
        "relationship_types": sorted(relationship_counts),
        "entrypoint_entity_types": entrypoint_types,
        "required_entity_types_present": {
            entity_type: entity_counts.get(entity_type, 0) > 0 for entity_type in required_entity_types
        },
        "profile_entity_types": [
            "team_match_profile",
            "player_match_profile",
            "source_domain_profile",
            "scout_match_profile",
        ],
        "lineage_relation": "summarizes_evidence_claim",
        "admission": admission,
        "integrity": integrity,
        "readiness": readiness,
        "ingestion_policy": {
            "source_of_truth": "world_graph.json",
            "admit_evidence_policy": "Use admissible evidence_claim nodes; weak/search aggregate claims are excluded from the graph.",
            "lineage_policy": "Profile nodes must link back to evidence_claim nodes with summarizes_evidence_claim.",
            "gap_policy": "Keep scouting_gap nodes visible until a required team/topic is covered by admissible evidence.",
        },
    }


def _write_compact_events(path: Path, result: RoundResult) -> None:
    entity_counts = _entity_type_counts(result)
    events = [{"event_type": "round_summary", **result.summary}]
    events.append({"event_type": "market_spec", **result.market_spec.to_dict()})
    events.extend({"event_type": "payment_receipt", **receipt.to_dict()} for receipt in result.payment_receipts)
    events.extend({"event_type": "balance_update", **update.to_dict()} for update in result.balance_updates)
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
    events.extend({"event_type": "social_action", **action.to_dict()} for action in result.social_actions)
    events.extend({"event_type": "debate_claim", **claim.to_dict()} for claim in result.claims)
    events.extend({"event_type": "forecast", **forecast.to_dict()} for forecast in result.forecasts)
    events.extend({"event_type": "internal_stake", **stake.to_dict()} for stake in result.internal_stakes)
    events.append({"event_type": "collective_decision", **result.collective_decision.to_dict()})
    events.append({"event_type": "settlement_summary", **result.settlement_summary})

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
