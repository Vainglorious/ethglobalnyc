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
    "team_history": {
        "priority": 55,
        "recommended_scout": "team_profile_scout",
        "query_focus": "team history, FIFA membership, confederation history, tournament record",
        "acceptance_criteria": [
            "source is official or reference-quality",
            "claim contains a concrete year, competition record, or affiliation fact",
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
