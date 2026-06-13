"""Fast checks for strict scouting inputs and KG metric promotion."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from .artifacts import _scouting_backlog_audit, _team_scouting_coverage_audit
from .live_scouts import (
    NewsItem,
    SquadPlayer,
    _claim_metrics,
    _claim_metrics_for_match,
    _claim_subject,
    _filter_topic_items,
    _parse_wikipedia_squad_players,
    _squad_roster_claims,
    _extract_claims_from_text,
    _source_recency_metadata,
    _tactical_items_from_team_scouts,
)
from .models import Finding, MatchContext
from .scout_adapters.polygun import polygun_findings_for_match
from .scout_adapters.telegram import telegram_findings_for_match
from .world_graph import build_world_graph


class ScoutingQualityTests(unittest.TestCase):
    def test_squad_depth_rejects_prediction_item_without_raw_evidence(self) -> None:
        items = [
            NewsItem(
                title="Brazil vs Morocco prediction, odds and betting tips",
                source="SEO site",
                link="https://example.test/prediction",
                published="",
            )
        ]

        self.assertEqual(_filter_topic_items(items, "squad_depth", team="Brazil"), [])

    def test_claim_metrics_extracts_player_and_availability_signals(self) -> None:
        form_metrics = _claim_metrics(
            "player_form",
            "Raphinha has 18 goals, 9 assists and 2.4 key passes per game in 42 matches.",
        )
        injury_metrics = _claim_metrics("injury_availability", "Achraf Hakimi is ruled out with a hamstring injury.")
        history_archive_metrics = _claim_metrics("match_history", "Brazil 2026 Results - ESPN scores and fixtures")
        tactical_metrics = _claim_metrics("tactical", "Morocco World Cup Squad: lineup and key players in a 4-1-4-1 formation")
        history_metrics = _claim_metrics(
            "team_history",
            "It has been a member of FIFA since 1960, with the Confederation of African Football since 1959.",
        )

        self.assertEqual(form_metrics["goals"], 18)
        self.assertEqual(form_metrics["assists"], 9)
        self.assertEqual(form_metrics["key_passes_per_game"], 2.4)
        self.assertEqual(form_metrics["appearances"], 42)
        self.assertEqual(injury_metrics["availability_status"], "out")
        self.assertEqual(injury_metrics["injury_body_part"], "hamstring")
        self.assertEqual(history_archive_metrics["results_season_year"], 2026)
        self.assertEqual(history_archive_metrics["archive_signal"], "results_archive")
        self.assertEqual(tactical_metrics["tactical_signal"], "lineup")
        self.assertEqual(tactical_metrics["formation"], "4-1-4-1")
        self.assertEqual(history_metrics["fifa_member_since_year"], 1960)
        self.assertEqual(history_metrics["confederation_member_since_year"], 1959)

    def test_match_history_score_metrics_require_explicit_team_score(self) -> None:
        metrics = _claim_metrics_for_match(
            "match_history",
            "Brazil beat Morocco 3-0 in their last meeting.",
            home_team="Brazil",
            away_team="Morocco",
        )
        vague_metrics = _claim_metrics_for_match(
            "match_history",
            "Brazil and Morocco have previous meetings in World Cup history.",
            home_team="Brazil",
            away_team="Morocco",
        )

        self.assertEqual(metrics["historical_team_a"], "Brazil")
        self.assertEqual(metrics["historical_team_b"], "Morocco")
        self.assertEqual(metrics["historical_team_a_score"], 3)
        self.assertEqual(metrics["historical_team_b_score"], 0)
        self.assertEqual(metrics["historical_result_signal"], "explicit_score")
        self.assertNotIn("historical_result_signal", vague_metrics)

    def test_source_recency_metadata_normalizes_rfc_dates(self) -> None:
        metadata = _source_recency_metadata("Sat, 13 Jun 2026 18:00:00 GMT", today=date(2026, 6, 13))

        self.assertEqual(metadata["source_published_date"], "2026-06-13")
        self.assertEqual(metadata["source_recency_days"], 0)
        self.assertEqual(metadata["source_recency_bucket"], "last_7_days")

    def test_tactical_items_are_promoted_only_from_clean_lineup_sources(self) -> None:
        accepted = NewsItem(
            title="Morocco World Cup Squad: Full Player List and Key Players",
            source="World Cup Pass",
            link="https://example.test/morocco-squad",
            published="",
        )
        rejected = NewsItem(
            title="Brazil vs Morocco score prediction and betting tips",
            source="Boostmatch",
            link="https://boostmatch.example/picks",
            published="",
        )

        items = _tactical_items_from_team_scouts(
            {"Morocco": {"squad_depth": [accepted, rejected]}},
            home_team="Brazil",
            away_team="Morocco",
        )

        self.assertEqual(items, [accepted])

    def test_player_subject_prefers_longest_known_alias(self) -> None:
        subject, team, player = _claim_subject(
            "Achraf Hakimi had 2 goals and 2 assists in Ligue 1.",
            home_team="Brazil",
            away_team="Morocco",
        )

        self.assertEqual(subject, "Achraf Hakimi")
        self.assertEqual(team, "Morocco")
        self.assertEqual(player, "Achraf Hakimi")

    def test_wikipedia_squad_parser_handles_nested_templates_and_wikilinks(self) -> None:
        wikitext = """
        == Current squad ==
        {{nat fs player|no=1|pos=GK|name=[[Alisson Becker|Alisson]]|age={{birth date and age|1992|10|2}}|caps=70|goals=0|club={{flagicon|ENG}} [[Liverpool F.C.|Liverpool]]}}
        {{nat fs player|no=2|pos=DF|name=[[Achraf Hakimi]]|caps=80|goals=10|club={{flagicon|FRA}} [[Paris Saint-Germain F.C.|Paris Saint-Germain]]}}
        == Recent call-ups ==
        {{nat fs player|pos=FW|name=[[Not Current]]|caps=1|goals=0|club=[[Example FC]]}}
        """

        players = _parse_wikipedia_squad_players(
            wikitext,
            team="Brazil",
            source_title="Brazil national football team",
            source_url="https://en.wikipedia.org/wiki/Brazil_national_football_team",
        )

        self.assertEqual([player.name for player in players], ["Alisson", "Achraf Hakimi"])
        self.assertEqual(players[0].position, "GK")
        self.assertEqual(players[0].club, "Liverpool")
        self.assertEqual(players[0].caps, 70)
        self.assertEqual(players[1].goals, 10)

    def test_squad_roster_claims_include_structured_player_metrics(self) -> None:
        players = [
            SquadPlayer(
                team="Brazil",
                name="Alisson",
                position="GK",
                club="Liverpool",
                caps=70,
                goals=0,
                source_title="Brazil national football team",
                source_url="https://en.wikipedia.org/wiki/Brazil_national_football_team",
            )
        ]

        claims = _squad_roster_claims({"Brazil": players, "Morocco": []}, home_team="Brazil", away_team="Morocco")

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claim_type, "squad_roster")
        self.assertEqual(claims[0].player, "Alisson")
        self.assertEqual(claims[0].metrics["position"], "GK")
        self.assertEqual(claims[0].metrics["club"], "Liverpool")
        self.assertEqual(claims[0].metrics["international_caps"], 70)

    def test_roster_known_players_are_used_for_claim_subjects(self) -> None:
        known_players = {"Brazil": ["gabriel magalhães", "magalhães"], "Morocco": []}

        claims = _extract_claims_from_text(
            text="Gabriel Magalhães has 1 goal and 17 appearances for Brazil this season.",
            source_title="Roster-aware player form",
            source_url="https://example.test/form",
            home_team="Brazil",
            away_team="Morocco",
            known_players=known_players,
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].subject, "Gabriel Magalhães")
        self.assertEqual(claims[0].team, "Brazil")
        self.assertEqual(claims[0].player, "Gabriel Magalhães")
        self.assertEqual(claims[0].metrics["goals"], 1)
        self.assertEqual(claims[0].metrics["appearances"], 17)

    def test_roster_known_players_canonicalize_diacritics(self) -> None:
        known_players = {"Brazil": ["bruno guimarães", "guimarães"], "Morocco": []}

        subject, team, player = _claim_subject(
            "Bruno Guimaraes has 2 assists for Brazil this season.",
            home_team="Brazil",
            away_team="Morocco",
            known_players=known_players,
        )

        self.assertEqual(subject, "Bruno Guimarães")
        self.assertEqual(team, "Brazil")
        self.assertEqual(player, "Bruno Guimarães")

    def test_optional_scouts_return_nothing_without_real_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_telegram = os.environ.pop("COLONY_TELEGRAM_SCOUT_JSON", None)
            old_telegram_live = os.environ.pop("COLONY_TELEGRAM_ENABLE_LIVE", None)
            old_polygun = os.environ.pop("COLONY_POLYGUN_SNAPSHOT_JSON", None)
            try:
                telegram = telegram_findings_for_match(
                    round_id="round:test",
                    home_team="Brazil",
                    away_team="Morocco",
                    market=0.55,
                    news_probability=0.54,
                    cache_dir=Path(tmp),
                    refresh=True,
                    timeout_seconds=1,
                )
                polygun = polygun_findings_for_match(
                    round_id="round:test",
                    home_team="Brazil",
                    away_team="Morocco",
                    market=0.55,
                    cache_dir=Path(tmp),
                )
            finally:
                if old_telegram is not None:
                    os.environ["COLONY_TELEGRAM_SCOUT_JSON"] = old_telegram
                if old_telegram_live is not None:
                    os.environ["COLONY_TELEGRAM_ENABLE_LIVE"] = old_telegram_live
                if old_polygun is not None:
                    os.environ["COLONY_POLYGUN_SNAPSHOT_JSON"] = old_polygun

        self.assertEqual(telegram, [])
        self.assertEqual(polygun, [])

    def test_polygun_ignores_account_balance_without_match_market_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "polygun.json"
            snapshot_path.write_text(
                '{"messages": [{"id": 1, "text": "Balance: 124.50 pUSD. Net worth visible."}]}',
                encoding="utf-8",
            )
            old_polygun = os.environ.get("COLONY_POLYGUN_SNAPSHOT_JSON")
            os.environ["COLONY_POLYGUN_SNAPSHOT_JSON"] = str(snapshot_path)
            try:
                findings = polygun_findings_for_match(
                    round_id="round:test",
                    home_team="Brazil",
                    away_team="Morocco",
                    market=0.55,
                    cache_dir=Path(tmp),
                )
            finally:
                if old_polygun is None:
                    os.environ.pop("COLONY_POLYGUN_SNAPSHOT_JSON", None)
                else:
                    os.environ["COLONY_POLYGUN_SNAPSHOT_JSON"] = old_polygun

        self.assertEqual(findings, [])

    def test_polygun_market_snapshot_requires_match_team_and_adds_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "polygun.json"
            snapshot_path.write_text(
                '{"messages": [{"id": 7, "text": "Brazil market panel: Buy Yes price 0.57"}]}',
                encoding="utf-8",
            )
            old_polygun = os.environ.get("COLONY_POLYGUN_SNAPSHOT_JSON")
            os.environ["COLONY_POLYGUN_SNAPSHOT_JSON"] = str(snapshot_path)
            try:
                findings = polygun_findings_for_match(
                    round_id="round:test",
                    home_team="Brazil",
                    away_team="Morocco",
                    market=0.55,
                    cache_dir=Path(tmp),
                )
            finally:
                if old_polygun is None:
                    os.environ.pop("COLONY_POLYGUN_SNAPSHOT_JSON", None)
                else:
                    os.environ["COLONY_POLYGUN_SNAPSHOT_JSON"] = old_polygun

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].source_type, "market")
        self.assertEqual(findings[0].evidence_claims[0]["claim_type"], "market_snapshot")
        self.assertEqual(findings[0].evidence_claims[0]["metrics"]["visible_price_probability"], 0.57)

    def test_world_graph_promotes_claim_metrics_and_taxonomy_to_nodes(self) -> None:
        finding = Finding(
            finding_id="round:test:player_form",
            scout_name="player_form_scout",
            access_level="public",
            source_type="news",
            finding_name="player_form",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://www.example.test/player"],
            evidence_claims=[
                {
                    "claim_type": "player_form",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "Raphinha",
                    "claim": "Raphinha has 18 goals this season.",
                    "impact": "context_home",
                    "confidence": 0.52,
                    "source_title": "Example player report",
                    "source_url": "https://www.example.test/player",
                    "source_published": "Sat, 13 Jun 2026 18:00:00 GMT",
                    "source_published_date": "2026-06-13",
                    "source_recency_days": 0,
                    "source_recency_bucket": "last_7_days",
                    "source_kind": "stats",
                    "source_quality": "strong",
                    "metrics": {"goals": 18},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertTrue(any(entity.entity_type == "metric" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "player_stat_line" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "scouting_topic" for entity in graph.entities))
        self.assertTrue(any(rel.relation_type == "has_metric" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "mentions_player_stat_line" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_scouting_topic" for rel in graph.relationships))
        self.assertTrue(any(entity.entity_type == "scout" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "claim_type" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "claim_impact" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_domain" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_kind" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_quality" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_recency" for entity in graph.entities))
        self.assertTrue(
            any(entity.entity_type == "source_domain" and entity.name == "example.test" for entity in graph.entities)
        )
        self.assertTrue(any(rel.relation_type == "produced" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_claim_type" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_claim_impact" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "from_domain" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_source_kind" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_source_quality" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_source_recency" for rel in graph.relationships))

    def test_world_graph_scouting_topics_track_covered_and_missing_claim_types(self) -> None:
        finding = Finding(
            finding_id="round:test:form",
            scout_name="player_form_scout",
            access_level="public",
            source_type="stats",
            finding_name="player_form",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/player"],
            evidence_claims=[
                {
                    "claim_type": "player_form",
                    "subject": "Raphinha",
                    "team": "Brazil",
                    "player": "Raphinha",
                    "claim": "Raphinha has 18 goals this season.",
                    "impact": "context_home",
                    "confidence": 0.52,
                    "source_title": "Example player report",
                    "source_url": "https://example.test/player",
                    "source_kind": "stats",
                    "source_quality": "strong",
                    "metrics": {"goals": 18},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)
        topics = {
            entity.name: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "scouting_topic"
        }
        team_topics = {
            entity.name: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "team_scouting_topic"
        }
        gaps = {
            entity.name: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "scouting_gap"
        }

        self.assertEqual(topics["player_form"]["coverage_status"], "covered")
        self.assertEqual(topics["player_form"]["claim_count"], 1)
        self.assertEqual(topics["player_form"]["metric_claim_count"], 1)
        self.assertEqual(topics["tactical"]["coverage_status"], "missing")
        self.assertEqual(topics["tactical"]["claim_count"], 0)
        self.assertEqual(team_topics["Brazil player_form"]["coverage_status"], "covered")
        self.assertEqual(team_topics["Brazil player_form"]["claim_count"], 1)
        self.assertEqual(team_topics["Brazil player_form"]["metric_claim_count"], 1)
        self.assertEqual(team_topics["Brazil player_form"]["player_count"], 1)
        self.assertEqual(team_topics["Morocco player_form"]["coverage_status"], "missing")
        self.assertEqual(team_topics["Morocco player_form"]["claim_count"], 0)
        self.assertEqual(gaps["Morocco player_form gap"]["status"], "needs_rescout")
        self.assertEqual(gaps["Morocco player_form gap"]["recommended_scout"], "player_form_scout")
        self.assertEqual(gaps["Morocco player_form gap"]["claim_type"], "player_form")
        self.assertTrue(any(rel.relation_type == "has_team_scouting_topic" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_scouting_gap" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "targets_team_scouting_topic" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "supports_scouting_topic" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "supports_team_scouting_topic" for rel in graph.relationships))

        audit = _team_scouting_coverage_audit(type("Result", (), {"world_graph": graph})())
        rows = {row["team"]: row for row in audit["teams"]}
        self.assertEqual(rows["Brazil"]["claim_types"]["player_form"]["coverage_status"], "covered")
        self.assertEqual(rows["Brazil"]["claim_types"]["player_form"]["claim_count"], 1)
        self.assertIn("player_form", rows["Morocco"]["missing_required_claim_types"])
        self.assertIn("Morocco", audit["teams_with_missing_required_claims"])
        backlog = _scouting_backlog_audit(audit)
        missing_player_form = [
            item
            for item in backlog["items"]
            if item["team"] == "Morocco" and item["claim_type"] == "player_form"
        ]
        self.assertEqual(len(missing_player_form), 1)
        self.assertEqual(missing_player_form[0]["status"], "needs_rescout")
        self.assertEqual(missing_player_form[0]["recommended_scout"], "player_form_scout")
        self.assertIn("team_scouting_topic:", missing_player_form[0]["target_entity_id"])

    def test_world_graph_flags_stale_freshness_sensitive_topics(self) -> None:
        finding = Finding(
            finding_id="round:test:availability",
            scout_name="availability_scout",
            access_level="public",
            source_type="lineup",
            finding_name="availability",
            home_probability=0.54,
            home_delta=0.0,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/injury"],
            evidence_claims=[
                {
                    "claim_type": "injury_availability",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "Neymar",
                    "claim": "Neymar is doubtful with a calf issue.",
                    "impact": "negative_home",
                    "confidence": 0.55,
                    "source_title": "Example injury report",
                    "source_url": "https://example.test/injury",
                    "source_kind": "news",
                    "source_quality": "strong",
                    "metrics": {"availability_status": "doubtful", "injury_body_part": "calf"},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)
        team_topics = {
            entity.name: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "team_scouting_topic"
        }
        gaps = {
            entity.name: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "scouting_gap"
        }

        self.assertEqual(team_topics["Brazil injury_availability"]["coverage_status"], "covered")
        self.assertEqual(team_topics["Brazil injury_availability"]["freshness_status"], "needs_fresh_source")
        self.assertEqual(team_topics["Brazil injury_availability"]["recent_30d_claim_count"], 0)
        self.assertEqual(gaps["Brazil injury_availability gap"]["status"], "needs_fresh_rescout")
        self.assertEqual(gaps["Brazil injury_availability gap"]["gap_reason"], "covered_topic_without_recent_source")

        audit = _team_scouting_coverage_audit(type("Result", (), {"world_graph": graph})())
        backlog = _scouting_backlog_audit(audit)
        fresh_items = [
            item
            for item in backlog["items"]
            if item["team"] == "Brazil" and item["claim_type"] == "injury_availability"
        ]
        self.assertEqual(fresh_items[0]["status"], "needs_fresh_rescout")

    def test_world_graph_promotes_match_metadata_nodes(self) -> None:
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            match_date="2026-06-13",
            match_time="18:00 UTC-4",
            group_name="Group C",
            stage_name="Matchday 3",
            venue_name="New York/New Jersey (East Rutherford)",
            findings=[],
        )

        graph = build_world_graph(match)
        match_entity = next(entity for entity in graph.entities if entity.entity_type == "match")

        self.assertEqual(match_entity.attributes["date"], "2026-06-13")
        self.assertEqual(match_entity.attributes["time"], "18:00 UTC-4")
        self.assertTrue(any(entity.entity_type == "venue" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "group" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "stage" for entity in graph.entities))
        self.assertTrue(any(rel.relation_type == "played_at" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "part_of_group" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "part_of_stage" for rel in graph.relationships))

    def test_world_graph_promotes_squad_roster_club_and_position_nodes(self) -> None:
        finding = Finding(
            finding_id="round:test:squad_roster",
            scout_name="squad_roster_scout",
            access_level="public",
            source_type="lineup",
            finding_name="structured_current_squad_roster_read",
            home_probability=None,
            home_delta=None,
            confidence=0.52,
            cost=0.0,
            citations=["https://en.wikipedia.org/wiki/Brazil_national_football_team"],
            evidence_claims=[
                {
                    "claim_type": "squad_roster",
                    "subject": "Alisson",
                    "team": "Brazil",
                    "player": "Alisson",
                    "claim": "Alisson is listed in the current Brazil squad: GK, Liverpool, 70 caps",
                    "impact": "context_home",
                    "confidence": 0.52,
                    "source_title": "Brazil national football team",
                    "source_url": "https://en.wikipedia.org/wiki/Brazil_national_football_team",
                    "source_kind": "reference",
                    "source_quality": "medium",
                    "metrics": {
                        "roster_signal": "current_squad",
                        "position": "GK",
                        "club": "Liverpool",
                        "international_caps": 70,
                    },
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertTrue(any(entity.entity_type == "club" and entity.name == "Liverpool" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "position" and entity.name == "GK" for entity in graph.entities))
        self.assertTrue(any(rel.relation_type == "affiliated_with" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "plays_position" for rel in graph.relationships))

    def test_world_graph_does_not_promote_minutes_only_player_stat_line(self) -> None:
        finding = Finding(
            finding_id="round:test:minutes",
            scout_name="squad_depth_scout",
            access_level="public",
            source_type="lineup",
            finding_name="squad_depth_and_predicted_xi_read",
            home_probability=0.54,
            home_delta=-0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/minutes"],
            evidence_claims=[
                {
                    "claim_type": "player_form",
                    "subject": "Neymar",
                    "team": "Brazil",
                    "player": "Neymar",
                    "claim": "Neymar is not expected to play a full 90 minutes here.",
                    "impact": "context_home",
                    "confidence": 0.5,
                    "source_title": "Brazil team news",
                    "source_url": "https://example.test/minutes",
                    "source_kind": "news",
                    "source_quality": "strong",
                    "metrics": {"minutes": 90},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertFalse(any(entity.entity_type == "player_stat_line" for entity in graph.entities))

    def test_world_graph_promotes_explicit_match_history_results(self) -> None:
        finding = Finding(
            finding_id="round:test:history",
            scout_name="match_history_scout",
            access_level="public",
            source_type="stats",
            finding_name="head_to_head_and_match_history_read",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.52,
            cost=0.0,
            citations=["https://example.test/h2h"],
            evidence_claims=[
                {
                    "claim_type": "match_history",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil beat Morocco 3-0 in their last meeting.",
                    "impact": "context_home",
                    "confidence": 0.52,
                    "source_title": "Brazil Morocco H2H",
                    "source_url": "https://example.test/h2h",
                    "source_kind": "stats",
                    "source_quality": "strong",
                    "metrics": {
                        "historical_team_a": "Brazil",
                        "historical_team_b": "Morocco",
                        "historical_team_a_score": 3,
                        "historical_team_b_score": 0,
                        "historical_result_label": "Brazil 3-0 Morocco",
                        "historical_result_signal": "explicit_score",
                    },
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertTrue(any(entity.entity_type == "match_result" for entity in graph.entities))
        self.assertTrue(any(rel.relation_type == "mentions_result" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "historical_context_for" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "team_a" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "team_b" for rel in graph.relationships))

    def test_world_graph_promotes_availability_events(self) -> None:
        finding = Finding(
            finding_id="round:test:availability",
            scout_name="squad_availability_scout",
            access_level="public",
            source_type="lineup",
            finding_name="injury_and_player_availability_read",
            home_probability=0.52,
            home_delta=-0.03,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/injury"],
            evidence_claims=[
                {
                    "claim_type": "injury_availability",
                    "subject": "Neymar",
                    "team": "Brazil",
                    "player": "Neymar",
                    "claim": "Neymar is ruled out with a hamstring injury.",
                    "impact": "negative_home",
                    "confidence": 0.72,
                    "source_title": "Brazil injury report",
                    "source_url": "https://example.test/injury",
                    "source_kind": "news",
                    "source_quality": "strong",
                    "metrics": {"availability_status": "out", "injury_body_part": "hamstring"},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertTrue(any(entity.entity_type == "availability_event" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "availability_status" and entity.name == "out" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "body_part" and entity.name == "hamstring" for entity in graph.entities))
        self.assertTrue(any(rel.relation_type == "mentions_availability_event" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "availability_context_for" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_availability_status" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_body_part" for rel in graph.relationships))

    def test_world_graph_promotes_explicit_formations(self) -> None:
        finding = Finding(
            finding_id="round:test:tactical",
            scout_name="tactical_matchup_scout",
            access_level="public",
            source_type="stats",
            finding_name="tactical_style_and_key_matchups_read",
            home_probability=0.54,
            home_delta=-0.01,
            confidence=0.48,
            cost=0.0,
            citations=["https://example.test/tactical"],
            evidence_claims=[
                {
                    "claim_type": "tactical",
                    "subject": "Morocco",
                    "team": "Morocco",
                    "player": "",
                    "claim": "Morocco set up in a 4-1-4-1 formation.",
                    "impact": "context_away",
                    "confidence": 0.48,
                    "source_title": "Morocco tactical preview",
                    "source_url": "https://example.test/tactical",
                    "source_kind": "web",
                    "source_quality": "medium",
                    "metrics": {"tactical_signal": "formation", "formation": "4-1-4-1"},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertTrue(any(entity.entity_type == "formation" and entity.name == "4-1-4-1" for entity in graph.entities))
        self.assertTrue(any(rel.relation_type == "mentions_formation" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "formation_context_for" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "used_by_team" for rel in graph.relationships))

    def test_world_graph_rejects_weak_evidence_claims(self) -> None:
        finding = Finding(
            finding_id="round:test:weak",
            scout_name="weak_scout",
            access_level="public",
            source_type="news",
            finding_name="weak_claim",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://tips.example/prediction"],
            evidence_claims=[
                {
                    "claim_type": "market_preview",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil vs Morocco prediction and betting tips.",
                    "confidence": 0.2,
                    "source_title": "Betting tips",
                    "source_url": "https://tips.example/prediction",
                    "source_kind": "web",
                    "source_quality": "weak",
                    "metrics": {},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertFalse(any(entity.entity_type == "evidence_claim" for entity in graph.entities))

    def test_world_graph_rejects_medium_search_aggregate_claims(self) -> None:
        finding = Finding(
            finding_id="round:test:search",
            scout_name="google_news_scout",
            access_level="public",
            source_type="news",
            finding_name="news_visibility_read",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://news.google.com/"],
            evidence_claims=[
                {
                    "claim_type": "lineup",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil lineup appears in a news aggregate title.",
                    "confidence": 0.4,
                    "source_title": "Google News match query",
                    "source_url": "https://news.google.com/",
                    "source_kind": "search",
                    "source_quality": "medium",
                    "metrics": {},
                }
            ],
        )
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[finding],
        )

        graph = build_world_graph(match)

        self.assertFalse(any(entity.entity_type == "evidence_claim" for entity in graph.entities))


if __name__ == "__main__":
    unittest.main()
