"""Shared scouting topic taxonomy and re-scout recipes."""

from __future__ import annotations

SCOUTING_REQUIRED_CLAIM_TYPES = (
    "team_profile",
    "recent_form",
    "player_form",
    "squad_roster",
    "injury_availability",
    "lineup",
    "match_history",
    "tactical",
)

SCOUTING_FRESHNESS_REQUIRED_CLAIM_TYPES = (
    "injury_availability",
    "lineup",
)

SCOUTING_RESCOUT_RECIPES = {
    "team_profile": {
        "priority": 50,
        "recommended_scout": "team_profile_scout",
        "query_focus": "official team profile, federation profile, FIFA profile",
        "acceptance_criteria": [
            "source is official, reference, or strong news/stat source",
            "claim names the team explicitly",
        ],
    },
    "recent_form": {
        "priority": 70,
        "recommended_scout": "recent_form_scout",
        "query_focus": "recent fixtures, recent results, last matches, form table",
        "acceptance_criteria": [
            "source is stats, official, or strong news",
            "claim names the team and contains a concrete fixture, result, or form record",
        ],
    },
    "player_form": {
        "priority": 74,
        "recommended_scout": "player_form_scout",
        "query_focus": "key player season form, goals, assists, appearances, ratings",
        "acceptance_criteria": [
            "claim names a player tied to the team",
            "claim contains at least one concrete performance metric",
        ],
    },
    "squad_roster": {
        "priority": 65,
        "recommended_scout": "squad_roster_scout",
        "query_focus": "current squad, official squad list, roster positions and clubs",
        "acceptance_criteria": [
            "source is official or reference-quality",
            "claim names a player and includes roster context such as position, club, caps, or goals",
        ],
    },
    "injury_availability": {
        "priority": 88,
        "recommended_scout": "availability_scout",
        "query_focus": "injury report, suspension, doubtful, ruled out, squad availability",
        "acceptance_criteria": [
            "source is dated or recent enough for match context",
            "claim contains an explicit availability status",
        ],
    },
    "lineup": {
        "priority": 82,
        "recommended_scout": "squad_depth_scout",
        "query_focus": "predicted XI, lineup, squad depth, starting roles",
        "acceptance_criteria": [
            "source is match-specific",
            "claim contains lineup, role, or predicted-XI context rather than generic squad text",
        ],
    },
    "match_history": {
        "priority": 90,
        "recommended_scout": "match_history_scout",
        "query_focus": "head-to-head, previous meetings, team result archive, recent match history",
        "acceptance_criteria": [
            "claim names the team explicitly",
            "scorelines are admitted only when both teams and the score are explicit",
        ],
    },
    "tactical": {
        "priority": 78,
        "recommended_scout": "tactical_scout",
        "query_focus": "formation, pressing, transitions, set pieces, tactical matchup",
        "acceptance_criteria": [
            "claim names the team or matchup explicitly",
            "claim contains a formation, role, tactical phase, or matchup detail",
        ],
    },
}


def scouting_topic_quality(
    claim_type: str,
    *,
    claim_count: int,
    metric_claim_count: int = 0,
    player_count: int = 0,
    recent_30d_claim_count: int = 0,
    strong_or_official_claim_count: int = 0,
    claim_quality_counts: dict | None = None,
) -> tuple[str, list[str]]:
    """Return whether a topic has useful evidence for KG coverage."""

    if claim_count <= 0:
        return "missing", ["missing_claim"]

    qualities = claim_quality_counts or {}
    reasons: list[str] = []
    if claim_type in SCOUTING_REQUIRED_CLAIM_TYPES and strong_or_official_claim_count <= 0:
        reasons.append("needs_stronger_source")

    if claim_type == "recent_form":
        if metric_claim_count <= 0 and int(qualities.get("recent_results_window") or 0) <= 0:
            reasons.append("needs_recent_results_window")
    elif claim_type == "player_form":
        if player_count <= 0:
            reasons.append("needs_player")
        if metric_claim_count <= 0 and int(qualities.get("season_output") or 0) <= 0:
            reasons.append("needs_player_season_metric")
    elif claim_type == "squad_roster":
        if player_count <= 0:
            reasons.append("needs_roster_player")
    elif claim_type == "injury_availability":
        if int(qualities.get("availability_status") or 0) <= 0:
            reasons.append("needs_availability_status")
        if recent_30d_claim_count <= 0:
            reasons.append("needs_recent_source")
    elif claim_type == "lineup":
        if (
            metric_claim_count <= 0
            and int(qualities.get("formation_signal") or 0) <= 0
            and int(qualities.get("lineup_signal") or 0) <= 0
        ):
            reasons.append("needs_lineup_or_role_signal")
        if recent_30d_claim_count <= 0:
            reasons.append("needs_recent_source")
    elif claim_type == "match_history":
        if (
            metric_claim_count <= 0
            and int(qualities.get("explicit_score") or 0) <= 0
            and int(qualities.get("h2h_record") or 0) <= 0
        ):
            reasons.append("needs_match_history_metric")
    elif claim_type == "tactical":
        if metric_claim_count <= 0 and int(qualities.get("formation_signal") or 0) <= 0:
            reasons.append("needs_tactical_detail")

    return ("needs_better_evidence", reasons) if reasons else ("usable", [])
