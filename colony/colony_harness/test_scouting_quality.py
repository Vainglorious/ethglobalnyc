"""Fast checks for strict scouting inputs and KG metric promotion."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from . import live_scouts as live_scouts_module
from .artifacts import (
    _kg_admission_audit,
    _kg_integrity_audit,
    _kg_manifest,
    _kg_readiness_audit,
    _scouting_backlog_audit,
    _team_scouting_coverage_audit,
)
from .live_scouts import (
    NewsItem,
    SquadPlayer,
    _claim_metrics,
    _claim_metrics_for_match,
    _claim_subject,
    _deepseek_claims_from_payload,
    deepseek_agent_findings_for_match,
    _filter_topic_items,
    _focused_rescout_queries,
    _parse_wikipedia_squad_players,
    _squad_roster_claims,
    _extract_claims_from_text,
    _source_recency_metadata,
    _tactical_items_from_team_scouts,
)
from .kg_ingestion import KGIngestionError, load_scouting_kg_bundle, validate_scouting_kg_run
from .models import DebateClaim, Finding, MatchContext
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
            "Raphinha has 18 goals, 9 assists, 27 goal contributions, 21 starts and 2.4 key passes per game in 42 matches during the 2025-26 season.",
        )
        injury_metrics = _claim_metrics("injury_availability", "Achraf Hakimi is ruled out with a hamstring injury.")
        history_archive_metrics = _claim_metrics("match_history", "Brazil 2026 Results - ESPN scores and fixtures")
        tactical_metrics = _claim_metrics("tactical", "Morocco World Cup Squad: lineup and key players in a 4-1-4-1 formation")
        lineup_metrics = _claim_metrics("lineup", "Brazil vs Morocco predicted line-ups and probable starting XI")
        recent_metrics = _claim_metrics(
            "recent_form",
            "Morocco are unbeaten in their last 6 matches, won 4 of their last 6, scored 12 goals in their last 6 and conceded 4 goals in their last 6.",
        )

        self.assertEqual(form_metrics["goals"], 18)
        self.assertEqual(form_metrics["assists"], 9)
        self.assertEqual(form_metrics["goal_contributions"], 27)
        self.assertEqual(form_metrics["starts"], 21)
        self.assertEqual(form_metrics["key_passes_per_game"], 2.4)
        self.assertEqual(form_metrics["appearances"], 42)
        self.assertEqual(form_metrics["season_label"], "2025-26")
        self.assertEqual(injury_metrics["availability_status"], "out")
        self.assertEqual(injury_metrics["injury_body_part"], "hamstring")
        self.assertEqual(history_archive_metrics["results_season_year"], 2026)
        self.assertEqual(history_archive_metrics["archive_signal"], "results_archive")
        self.assertEqual(tactical_metrics["tactical_signal"], "lineup")
        self.assertEqual(tactical_metrics["formation"], "4-1-4-1")
        self.assertEqual(tactical_metrics["lineup_signal"], "lineup")
        self.assertEqual(lineup_metrics["lineup_signal"], "predicted_lineups")
        self.assertEqual(recent_metrics["recent_sample_matches"], 6)
        self.assertEqual(recent_metrics["recent_wins"], 4)
        self.assertEqual(recent_metrics["unbeaten_matches"], 6)
        self.assertEqual(recent_metrics["recent_goals_for"], 12)
        self.assertEqual(recent_metrics["recent_goals_against"], 4)

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
        record_metrics = _claim_metrics_for_match(
            "match_history",
            "Brazil have won 2 of their 3 previous meetings with Morocco.",
            home_team="Brazil",
            away_team="Morocco",
        )
        source_record_metrics = _claim_metrics_for_match(
            "match_history",
            "Brazil vs Morocco Past H2H Results. Last 5, Brazil won 3, Draw 1, Lose 1, 2.6 Goals per match, 1.4 Goals.",
            home_team="Brazil",
            away_team="Morocco",
        )

        self.assertEqual(metrics["historical_team_a"], "Brazil")
        self.assertEqual(metrics["historical_team_b"], "Morocco")
        self.assertEqual(metrics["historical_team_a_score"], 3)
        self.assertEqual(metrics["historical_team_b_score"], 0)
        self.assertEqual(metrics["historical_result_signal"], "explicit_score")
        self.assertNotIn("historical_result_signal", vague_metrics)
        self.assertEqual(record_metrics["historical_team_a"], "Brazil")
        self.assertEqual(record_metrics["historical_team_b"], "Morocco")
        self.assertEqual(record_metrics["historical_team_a_wins"], 2)
        self.assertEqual(record_metrics["historical_meetings"], 3)
        self.assertEqual(record_metrics["historical_record_signal"], "h2h_record")
        self.assertEqual(source_record_metrics["h2h_recent_sample_matches"], 5)
        self.assertEqual(source_record_metrics["h2h_team_a_wins"], 3)
        self.assertEqual(source_record_metrics["h2h_draws"], 1)
        self.assertEqual(source_record_metrics["h2h_team_a_losses"], 1)
        self.assertEqual(source_record_metrics["h2h_team_a_goals_per_match"], 2.6)
        self.assertEqual(source_record_metrics["historical_record_signal"], "h2h_recent_record")

    def test_focused_rescout_queries_follow_quality_reasons(self) -> None:
        recent_queries = _focused_rescout_queries(
            team="Brazil",
            claim_type="recent_form",
            quality_reasons=["needs_recent_results_window"],
        )
        player_queries = _focused_rescout_queries(
            team="Morocco",
            claim_type="player_form",
            quality_reasons=["needs_player", "needs_player_season_metric"],
        )

        self.assertIn("last 5 results", recent_queries[0])
        self.assertIn("W D L", recent_queries[0])
        self.assertIn("player stats goals assists appearances", player_queries[0])
        self.assertIn("key players goals assists season stats", player_queries[1])

    def test_deepseek_agent_claims_are_source_locked_and_useful(self) -> None:
        source = NewsItem(
            title="Brazil projected lineup and Neymar injury update",
            source="ESPN",
            link="https://example.test/brazil-lineup",
            published="Sat, 13 Jun 2026 18:00:00 GMT",
        )
        payload = [
            {
                "claim_type": "injury_availability",
                "team": "Brazil",
                "player": "Neymar",
                "claim": "Neymar is doubtful with a calf injury.",
                "source_url": "https://example.test/brazil-lineup",
            },
            {
                "claim_type": "team_history",
                "team": "Brazil",
                "claim": "Brazil joined FIFA in 1923.",
                "source_url": "https://example.test/brazil-lineup",
            },
            {
                "claim_type": "lineup",
                "team": "Brazil",
                "claim": "Brazil may use a 4-3-3.",
                "source_url": "https://not-provided.test/story",
            },
        ]

        claims = _deepseek_claims_from_payload(
            payload,
            home_team="Brazil",
            away_team="Morocco",
            source_items=[source],
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claim_type, "injury_availability")
        self.assertEqual(claims[0].team, "Brazil")
        self.assertEqual(claims[0].source_url, "https://example.test/brazil-lineup")
        self.assertEqual(claims[0].extraction_method, "deepseek_agent")
        self.assertEqual(claims[0].metrics["availability_status"], "doubtful")

    def test_deepseek_role_filter_keeps_agent_scope_tight(self) -> None:
        source = NewsItem(
            title="Morocco tactical preview and lineup notes",
            source="Analyst",
            link="https://example.test/morocco-tactics",
            published="Sat, 13 Jun 2026 18:00:00 GMT",
        )
        payload = [
            {
                "claim_type": "tactical",
                "team": "Morocco",
                "claim": "Morocco are expected to defend in a compact 4-1-4-1 shape.",
                "source_url": "https://example.test/morocco-tactics",
            },
            {
                "claim_type": "injury_availability",
                "team": "Morocco",
                "player": "Achraf Hakimi",
                "claim": "Achraf Hakimi is doubtful.",
                "source_url": "https://example.test/morocco-tactics",
            },
        ]

        claims = _deepseek_claims_from_payload(
            payload,
            home_team="Brazil",
            away_team="Morocco",
            source_items=[source],
            allowed_claim_types={"tactical"},
        )

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].claim_type, "tactical")
        self.assertEqual(claims[0].team, "Morocco")

    def test_deepseek_findings_are_split_by_agent_role(self) -> None:
        source = NewsItem(
            title="Brazil Morocco scouting notebook",
            source="Notebook",
            link="https://example.test/scouting",
            published="Sat, 13 Jun 2026 18:00:00 GMT",
        )
        original_fetch = live_scouts_module.fetch_deepseek_agent_claims
        seen_roles: list[str] = []

        def fake_fetch(**kwargs):
            role = kwargs["role"]
            seen_roles.append(role.scout_name)
            claim_type = role.allowed_claim_types[0]
            payload = [
                {
                    "claim_type": claim_type,
                    "team": "Brazil",
                    "player": "Neymar" if claim_type in {"injury_availability", "player_form"} else "",
                    "claim": "Brazil have a role-specific source-locked scouting signal.",
                    "source_url": "https://example.test/scouting",
                }
            ]
            return _deepseek_claims_from_payload(
                payload,
                home_team="Brazil",
                away_team="Morocco",
                source_items=[source],
                allowed_claim_types=set(role.allowed_claim_types),
            )

        try:
            live_scouts_module.fetch_deepseek_agent_claims = fake_fetch
            findings = deepseek_agent_findings_for_match(
                round_id="round:test",
                home_team="Brazil",
                away_team="Morocco",
                market=0.5,
                stats=0.55,
                news=0.52,
                cache_dir=Path(tempfile.gettempdir()),
                refresh=False,
                timeout_seconds=1,
                source_items=[source],
            )
        finally:
            live_scouts_module.fetch_deepseek_agent_claims = original_fetch

        self.assertEqual(
            seen_roles,
            ["deepseek_availability_agent", "deepseek_form_player_agent", "deepseek_tactical_agent"],
        )
        self.assertEqual(
            [finding.scout_name for finding in findings],
            ["deepseek_availability_agent", "deepseek_form_player_agent", "deepseek_tactical_agent"],
        )

    def test_source_recency_metadata_normalizes_rfc_dates(self) -> None:
        metadata = _source_recency_metadata("Sat, 13 Jun 2026 18:00:00 GMT", today=date(2026, 6, 13))

        self.assertEqual(metadata["source_published_date"], "2026-06-13")
        self.assertEqual(metadata["source_recency_days"], 0)
        self.assertEqual(metadata["source_recency_bucket"], "last_7_days")

    def test_source_recency_metadata_uses_relative_source_context(self) -> None:
        metadata = _source_recency_metadata(
            "",
            source_context="Brazil vs Morocco Lineups, Team News & Preview | RotoWire - 2 hours ago",
            today=date(2026, 6, 13),
        )
        older_metadata = _source_recency_metadata(
            "",
            source_context="Brazil squad update - 2 weeks ago",
            today=date(2026, 6, 13),
        )

        self.assertEqual(metadata["source_published_date"], "2026-06-13")
        self.assertEqual(metadata["source_recency_days"], 0)
        self.assertEqual(metadata["source_recency_bucket"], "last_7_days")
        self.assertEqual(older_metadata["source_published_date"], "2026-05-30")
        self.assertEqual(older_metadata["source_recency_days"], 14)
        self.assertEqual(older_metadata["source_recency_bucket"], "last_30_days")

    def test_availability_lineup_sentence_promotes_both_claim_types(self) -> None:
        claims = _extract_claims_from_text(
            text="Nayef Aguerd (pubalgia), Morocco's best center-back, is not in the predicted starting XI.",
            source_title="Brazil vs Morocco Lineups, Team News & Preview | RotoWire - 2 hours ago",
            source_url="https://example.test/lineups",
            home_team="Brazil",
            away_team="Morocco",
        )
        claim_types = sorted(claim.claim_type for claim in claims)
        lineup_claim = next(claim for claim in claims if claim.claim_type == "lineup")

        self.assertEqual(claim_types, ["injury_availability", "lineup"])
        self.assertEqual(lineup_claim.team, "Morocco")
        self.assertEqual(lineup_claim.player, "Nayef Aguerd")
        self.assertEqual(lineup_claim.source_recency_bucket, "last_7_days")

    def test_match_history_metrics_use_source_context(self) -> None:
        claims = _extract_claims_from_text(
            text="Brazil vs Morocco Past H2H Results, Asian Handicap Win%: 100.0%, Total Goals Over%: 100.0%.",
            source_title="Brazil vs Morocco Head to Head History - AiScore - Brazil vs Morocco Past H2H Results, Asian Handicap Win%: 100.0%, Total Goals Over%: 100.0%. Last 5, Brazil won 3, Draw 1, Lose 1, 2.6 Goals per match, 1.4 Goals.",
            source_url="https://example.test/h2h",
            home_team="Brazil",
            away_team="Morocco",
        )
        claim = next(claim for claim in claims if claim.claim_type == "match_history")

        self.assertEqual(claim.metrics["h2h_recent_sample_matches"], 5)
        self.assertEqual(claim.metrics["h2h_team_a_wins"], 3)
        self.assertEqual(claim.metrics["h2h_draws"], 1)
        self.assertEqual(claim.metrics["h2h_team_a_losses"], 1)
        self.assertEqual(claim.metrics["h2h_team_a_goals_per_match"], 2.6)

        body_claims = _extract_claims_from_text(
            text="This page lists the head-to-head record of Brazil vs Morocco including biggest victories and defeats between the two sides.",
            source_title="Brazil vs Morocco Head to Head History - AiScore. Last 5, Brazil won 3, Draw 1, Lose 1, 2.6 Goals per match, 1.4 Goals.",
            source_url="https://example.test/h2h",
            home_team="Brazil",
            away_team="Morocco",
        )
        body_claim = next(claim for claim in body_claims if claim.claim_type == "match_history")

        self.assertNotIn("h2h_recent_sample_matches", body_claim.metrics)

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

    def test_telegram_social_claims_keep_player_engagement_and_verification_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            export_path = Path(tmp) / "telegram.json"
            export_path.write_text(
                json.dumps(
                    {
                        "messages": [
                            {
                                "id": 11,
                                "chat": "BrazilTeamNews",
                                "text": "Official: Neymar is ruled out for Brazil with a hamstring injury.",
                                "views": 12000,
                                "forwards": 320,
                                "reactions": {"👍": 1400, "😢": 120},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            old_telegram = os.environ.get("COLONY_TELEGRAM_SCOUT_JSON")
            os.environ["COLONY_TELEGRAM_SCOUT_JSON"] = str(export_path)
            try:
                findings = telegram_findings_for_match(
                    round_id="round:test",
                    home_team="Brazil",
                    away_team="Morocco",
                    market=0.55,
                    news_probability=0.54,
                    cache_dir=Path(tmp),
                    refresh=True,
                    timeout_seconds=1,
                )
            finally:
                if old_telegram is None:
                    os.environ.pop("COLONY_TELEGRAM_SCOUT_JSON", None)
                else:
                    os.environ["COLONY_TELEGRAM_SCOUT_JSON"] = old_telegram

        self.assertEqual(len(findings), 1)
        claim = findings[0].evidence_claims[0]
        self.assertEqual(claim["player"], "Neymar")
        self.assertEqual(claim["metrics"]["availability_status"], "out")
        self.assertEqual(claim["metrics"]["verification_signal"], "official")
        self.assertEqual(claim["metrics"]["telegram_views"], 12000)
        self.assertEqual(claim["metrics"]["telegram_reactions"], 1520)

        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=findings,
        )
        graph = build_world_graph(match)
        claim_qualities = {entity.name for entity in graph.entities if entity.entity_type == "claim_quality"}
        player_profiles = {
            entity.attributes["player"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "player_match_profile"
        }
        scout_profiles = {
            entity.attributes["scout_name"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "scout_match_profile"
        }

        self.assertIn("social_verified_signal", claim_qualities)
        self.assertIn("engagement_backed", claim_qualities)
        self.assertEqual(player_profiles["Neymar"]["availability_statuses"], ["out"])
        self.assertEqual(scout_profiles["telegram_social_scout"]["claim_count"], 1)
        self.assertEqual(scout_profiles["telegram_social_scout"]["claim_types"]["injury_availability"], 1)
        self.assertEqual(scout_profiles["telegram_social_scout"]["players"], ["Neymar"])
        self.assertEqual(scout_profiles["telegram_social_scout"]["metric_keys"]["telegram_views"], 1)
        self.assertEqual(scout_profiles["telegram_social_scout"]["claim_quality_counts"]["social_verified_signal"], 1)
        self.assertTrue(any(rel.relation_type == "has_scout_match_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "profiles_scout" for rel in graph.relationships))

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
                json.dumps(
                    {
                        "messages": [
                            {
                                "id": 7,
                                "text": "Market ID 558936\nWill Brazil beat Morocco?\nBrazil market panel",
                                "buttons": [
                                    {"row": 0, "col": 0, "text": "Buy Yes 57¢", "callback": True},
                                    {"row": 0, "col": 1, "text": "Buy No 43¢", "callback": True},
                                ],
                            }
                        ]
                    }
                ),
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
        metrics = findings[0].evidence_claims[0]["metrics"]
        self.assertEqual(metrics["buy_yes_price_probability"], 0.57)
        self.assertEqual(metrics["buy_no_price_probability"], 0.43)
        self.assertEqual(metrics["polygun_market_id"], "558936")
        self.assertEqual(metrics["market_question"], "Will Brazil beat Morocco?")
        self.assertEqual(metrics["visible_button_count"], 2)
        self.assertTrue(metrics["has_callback_buttons"])

        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=findings,
        )
        graph = build_world_graph(match)
        claim_qualities = {entity.name for entity in graph.entities if entity.entity_type == "claim_quality"}

        self.assertIn("market_snapshot", claim_qualities)
        self.assertIn("visible_market_price", claim_qualities)

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
                    "metrics": {
                        "goals": 18,
                        "assists": 9,
                        "goal_contributions": 27,
                        "starts": 21,
                        "season_label": "2025-26",
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

        self.assertTrue(any(entity.entity_type == "metric" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "player_stat_line" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "team_match_profile" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "player_match_profile" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "scouting_topic" for entity in graph.entities))
        team_profiles = {
            entity.attributes["team"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "team_match_profile"
        }
        self.assertEqual(team_profiles["Brazil"]["claim_types"]["player_form"], 1)
        self.assertEqual(team_profiles["Brazil"]["player_count"], 1)
        self.assertIn("Raphinha", team_profiles["Brazil"]["players"])
        self.assertEqual(team_profiles["Brazil"]["claim_quality_counts"]["match_actionable"], 1)
        self.assertEqual(team_profiles["Brazil"]["claim_quality_counts"]["season_output"], 1)
        self.assertEqual(len(team_profiles["Brazil"]["evidence_claim_ids"]), 1)
        player_profiles = {
            entity.attributes["player"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "player_match_profile"
        }
        self.assertEqual(player_profiles["Raphinha"]["team"], "Brazil")
        self.assertEqual(player_profiles["Raphinha"]["claim_types"]["player_form"], 1)
        self.assertEqual(player_profiles["Raphinha"]["performance_metrics"]["goals"], ["18"])
        self.assertEqual(player_profiles["Raphinha"]["performance_metrics"]["assists"], ["9"])
        self.assertEqual(player_profiles["Raphinha"]["performance_metrics"]["goal_contributions"], ["27"])
        self.assertEqual(player_profiles["Raphinha"]["season_labels"], ["2025-26"])
        self.assertEqual(player_profiles["Raphinha"]["season_stat_summary"]["goals_max"], 18)
        self.assertEqual(player_profiles["Raphinha"]["season_stat_summary"]["assists_max"], 9)
        self.assertEqual(player_profiles["Raphinha"]["season_stat_summary"]["goal_contributions_max"], 27)
        self.assertEqual(player_profiles["Raphinha"]["season_stat_summary"]["starts_max"], 21)
        self.assertEqual(player_profiles["Raphinha"]["claim_quality_counts"]["match_actionable"], 1)
        self.assertEqual(player_profiles["Raphinha"]["claim_quality_counts"]["season_output"], 1)
        self.assertEqual(player_profiles["Raphinha"]["evidence_claim_ids"], team_profiles["Brazil"]["evidence_claim_ids"])
        self.assertTrue(any(rel.relation_type == "has_metric" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "mentions_player_stat_line" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_team_match_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_player_match_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_match_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "summarizes_player_match_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_scouting_topic" for rel in graph.relationships))
        self.assertTrue(any(entity.entity_type == "scout" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "claim_type" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "claim_impact" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_domain" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_kind" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_quality" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_recency" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "claim_quality" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "source_domain_profile" for entity in graph.entities))
        self.assertTrue(any(entity.entity_type == "scout_match_profile" for entity in graph.entities))
        domain_profiles = {
            entity.attributes["domain"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "source_domain_profile"
        }
        self.assertEqual(domain_profiles["example.test"]["claim_types"]["player_form"], 1)
        self.assertEqual(domain_profiles["example.test"]["source_quality"]["strong"], 1)
        self.assertEqual(domain_profiles["example.test"]["claim_quality_counts"]["match_actionable"], 1)
        self.assertEqual(domain_profiles["example.test"]["claim_quality_counts"]["season_output"], 1)
        self.assertEqual(domain_profiles["example.test"]["scout_names"], ["player_form_scout"])
        self.assertEqual(domain_profiles["example.test"]["evidence_claim_ids"], team_profiles["Brazil"]["evidence_claim_ids"])
        scout_profiles = {
            entity.attributes["scout_name"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "scout_match_profile"
        }
        self.assertEqual(scout_profiles["player_form_scout"]["claim_types"]["player_form"], 1)
        self.assertEqual(scout_profiles["player_form_scout"]["players"], ["Raphinha"])
        self.assertEqual(scout_profiles["player_form_scout"]["claim_quality_counts"]["season_output"], 1)
        self.assertEqual(scout_profiles["player_form_scout"]["evidence_claim_ids"], team_profiles["Brazil"]["evidence_claim_ids"])
        claim_qualities = {entity.name for entity in graph.entities if entity.entity_type == "claim_quality"}
        self.assertIn("metric_backed", claim_qualities)
        self.assertIn("player_specific", claim_qualities)
        self.assertIn("match_actionable", claim_qualities)
        self.assertIn("season_output", claim_qualities)
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
        self.assertTrue(any(rel.relation_type == "has_claim_quality" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_source_domain_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "profiles_domain" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "has_scout_match_profile" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "profiles_scout" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "summarizes_finding" for rel in graph.relationships))
        self.assertTrue(any(rel.relation_type == "summarizes_evidence_claim" for rel in graph.relationships))

        integrity = _kg_integrity_audit(type("Result", (), {"world_graph": graph})())
        self.assertTrue(integrity["passes"])
        self.assertEqual(integrity["orphan_relationship_count"], 0)
        self.assertEqual(integrity["summarizes_evidence_claim_missing_target_count"], 0)
        manifest = _kg_manifest(type("Result", (), {"world_graph": graph})())
        self.assertEqual(manifest["schema_version"], "scouting-kg-v1")
        self.assertTrue(manifest["integrity"]["passes"])
        self.assertIn("team_match_profile", manifest["entrypoint_entity_types"])
        self.assertIn("scout_match_profile", manifest["entrypoint_entity_types"])
        self.assertIn("scout_match_profile", manifest["profile_entity_types"])
        self.assertTrue(manifest["required_entity_types_present"]["evidence_claim"])
        readiness = _kg_readiness_audit(type("Result", (), {"findings": [finding], "world_graph": graph})())
        self.assertEqual(readiness["status"], "load_ready_with_scouting_backlog")
        self.assertTrue(readiness["kg_load_ready"])
        self.assertFalse(readiness["scouting_complete"])
        self.assertEqual(readiness["forbidden_claim_counts"], {})

    def test_kg_integrity_reports_duplicate_evidence_claims_without_blocking_load(self) -> None:
        shared_claim = {
            "claim_type": "player_form",
            "team": "Brazil",
            "player": "Raphinha",
            "subject": "Raphinha",
            "claim": "Raphinha has 18 goals this season.",
            "impact": "context_home",
            "source_url": "https://example.test/raphinha-form",
            "source_title": "Raphinha season stats",
            "source_quality": "strong",
            "source_kind": "stats",
            "confidence": 0.72,
            "metrics": {"goals": 18},
        }
        findings = [
            Finding(
                finding_id="round:test:form_a",
                scout_name="player_form_scout",
                access_level="public",
                source_type="stats",
                finding_name="player_form_a",
                home_probability=0.56,
                home_delta=0.01,
                confidence=0.72,
                cost=0.0,
                evidence_claims=[dict(shared_claim)],
            ),
            Finding(
                finding_id="round:test:form_b",
                scout_name="deepseek_form_player_agent",
                access_level="public",
                source_type="retrieval",
                finding_name="player_form_b",
                home_probability=0.56,
                home_delta=0.01,
                confidence=0.72,
                cost=0.0,
                evidence_claims=[dict(shared_claim)],
            ),
        ]
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=findings,
        )

        graph = build_world_graph(match)
        integrity = _kg_integrity_audit(type("Result", (), {"world_graph": graph})())

        self.assertTrue(integrity["passes"])
        self.assertEqual(integrity["duplicate_evidence_claim_group_count"], 1)
        self.assertEqual(integrity["duplicate_evidence_claim_count"], 2)
        duplicate_group = integrity["duplicate_evidence_claim_groups"][0]
        self.assertEqual(duplicate_group["claim_type"], "player_form")
        self.assertEqual(duplicate_group["team"], "brazil")
        self.assertEqual(duplicate_group["subject"], "raphinha")
        self.assertEqual(len(duplicate_group["evidence_claim_ids"]), 2)

    def test_kg_ingestion_bundle_materializes_entrypoints_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp)
            self._write_minimal_kg_ingestion_run(run_path, scouting_complete=True)

            bundle = load_scouting_kg_bundle(run_path, require_complete=True)

        self.assertTrue(bundle["validation"]["passes"])
        self.assertEqual(bundle["schema_version"], "scouting-kg-v1")
        self.assertEqual(len(bundle["entrypoints"]["team_match_profile"]), 1)
        self.assertEqual(bundle["entrypoints"]["team_match_profile"][0]["attributes"]["team"], "Brazil")
        self.assertEqual(
            bundle["profile_lineage"]["team_match_profile:brazil"],
            ["evidence_claim:player_form"],
        )
        self.assertEqual(
            bundle["profile_lineage"]["scout_match_profile:player_form_scout"],
            ["evidence_claim:player_form"],
        )
        self.assertEqual(len(bundle["entrypoints"]["scout_match_profile"]), 1)
        self.assertEqual(len(bundle["lineage_edges"]), 4)

    def test_kg_ingestion_require_complete_rejects_backlog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp)
            self._write_minimal_kg_ingestion_run(run_path, scouting_complete=False)

            validation = validate_scouting_kg_run(run_path)
            with self.assertRaises(KGIngestionError):
                load_scouting_kg_bundle(run_path, require_complete=True)

        self.assertTrue(validation["passes"])
        self.assertTrue(validation["kg_load_ready"])
        self.assertFalse(validation["scouting_complete"])

    def test_kg_ingestion_warns_on_duplicate_evidence_claim_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp)
            self._write_minimal_kg_ingestion_run(run_path, scouting_complete=True)
            manifest_path = run_path / "kg_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["integrity"] = {
                "passes": True,
                "duplicate_evidence_claim_group_count": 2,
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            validation = validate_scouting_kg_run(run_path, require_complete=True)
            bundle = load_scouting_kg_bundle(run_path, require_complete=True)

        self.assertTrue(validation["passes"])
        self.assertIn("duplicate_evidence_claim_groups:2", validation["warnings"])
        self.assertIn("duplicate_evidence_claim_groups:2", bundle["validation"]["warnings"])

    def test_kg_ingestion_warns_on_rejected_evidence_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp)
            self._write_minimal_kg_ingestion_run(run_path, scouting_complete=True)
            manifest_path = run_path / "kg_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["admission"] = {
                "raw_claim_count": 3,
                "admitted_claim_count": 1,
                "rejected_claim_count": 2,
                "rejection_reasons": {"unknown_impact": 1, "missing_impact": 1},
            }
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            validation = validate_scouting_kg_run(run_path, require_complete=True)
            bundle = load_scouting_kg_bundle(run_path, require_complete=True)

        self.assertTrue(validation["passes"])
        self.assertIn("rejected_evidence_claims:2", validation["warnings"])
        self.assertEqual(bundle["admission"]["rejected_claim_count"], 2)
        self.assertIn("rejected_evidence_claims:2", bundle["validation"]["warnings"])

    def test_rescout_from_audit_keeps_freshness_targets_and_quality_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "scouting_audit.json"
            audit_path.write_text(
                json.dumps(
                    {
                        "scouting_backlog": {
                            "items": [
                                {
                                    "status": "needs_fresh_rescout",
                                    "team": "Brazil",
                                    "claim_type": "injury_availability",
                                    "target_entity_id": "team_scouting_topic:brazil:injury",
                                    "quality_status": "needs_better_evidence",
                                    "quality_reasons": ["needs_recent_source"],
                                },
                                {
                                    "status": "covered",
                                    "team": "Brazil",
                                    "claim_type": "lineup",
                                },
                            ]
                        }
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            args = type(
                "Args",
                (),
                {"rescout_from_audit": str(audit_path), "scout_focus": []},
            )()

            colony_path = str(Path(__file__).resolve().parents[1])
            sys.path.insert(0, colony_path)
            try:
                from run_match import _rescout_targets_from_args

                targets = _rescout_targets_from_args(args)
            finally:
                sys.path.remove(colony_path)

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["status"], "needs_fresh_rescout")
        self.assertEqual(targets[0]["quality_reasons"], ["needs_recent_source"])

    def _write_minimal_kg_ingestion_run(self, run_path: Path, *, scouting_complete: bool) -> None:
        entities = [
            {
                "entity_id": "match:round:test",
                "entity_type": "match",
                "name": "Brazil vs Morocco",
                "attributes": {"round_id": "round:test"},
            },
            {"entity_id": "team:brazil", "entity_type": "team", "name": "Brazil", "attributes": {}},
            {"entity_id": "team:morocco", "entity_type": "team", "name": "Morocco", "attributes": {}},
            {"entity_id": "finding:player_form", "entity_type": "finding", "name": "player form", "attributes": {}},
            {
                "entity_id": "evidence_claim:player_form",
                "entity_type": "evidence_claim",
                "name": "Raphinha form",
                "attributes": {
                    "claim_type": "player_form",
                    "team": "Brazil",
                    "player": "Raphinha",
                    "claim": "Raphinha has 18 goals this season.",
                    "metrics": {"goals": 18},
                },
            },
            {
                "entity_id": "scouting_topic:player_form",
                "entity_type": "scouting_topic",
                "name": "player_form",
                "attributes": {"claim_type": "player_form", "coverage_status": "covered"},
            },
            {
                "entity_id": "team_scouting_topic:brazil:player_form",
                "entity_type": "team_scouting_topic",
                "name": "Brazil player_form",
                "attributes": {"team": "Brazil", "claim_type": "player_form", "coverage_status": "covered"},
            },
            {
                "entity_id": "team_match_profile:brazil",
                "entity_type": "team_match_profile",
                "name": "Brazil match profile",
                "attributes": {
                    "team": "Brazil",
                    "claim_count": 1,
                    "evidence_claim_ids": ["evidence_claim:player_form"],
                },
            },
            {
                "entity_id": "player_match_profile:raphinha",
                "entity_type": "player_match_profile",
                "name": "Raphinha match profile",
                "attributes": {
                    "team": "Brazil",
                    "player": "Raphinha",
                    "claim_count": 1,
                    "evidence_claim_ids": ["evidence_claim:player_form"],
                },
            },
            {
                "entity_id": "source_domain_profile:example",
                "entity_type": "source_domain_profile",
                "name": "example.test source profile",
                "attributes": {
                    "domain": "example.test",
                    "claim_count": 1,
                    "evidence_claim_ids": ["evidence_claim:player_form"],
                },
            },
            {
                "entity_id": "scout_match_profile:player_form_scout",
                "entity_type": "scout_match_profile",
                "name": "player_form_scout match profile",
                "attributes": {
                    "scout_name": "player_form_scout",
                    "claim_count": 1,
                    "evidence_claim_ids": ["evidence_claim:player_form"],
                },
            },
        ]
        relationships = [
            {
                "source_id": "team:brazil",
                "relation_type": "plays_home_in",
                "target_id": "match:round:test",
                "weight": 1.0,
                "attributes": {},
            },
            {
                "source_id": "finding:player_form",
                "relation_type": "has_evidence_claim",
                "target_id": "evidence_claim:player_form",
                "weight": 1.0,
                "attributes": {},
            },
            {
                "source_id": "team_match_profile:brazil",
                "relation_type": "summarizes_evidence_claim",
                "target_id": "evidence_claim:player_form",
                "weight": 1.0,
                "attributes": {},
            },
            {
                "source_id": "player_match_profile:raphinha",
                "relation_type": "summarizes_evidence_claim",
                "target_id": "evidence_claim:player_form",
                "weight": 1.0,
                "attributes": {},
            },
            {
                "source_id": "source_domain_profile:example",
                "relation_type": "summarizes_evidence_claim",
                "target_id": "evidence_claim:player_form",
                "weight": 1.0,
                "attributes": {},
            },
            {
                "source_id": "scout_match_profile:player_form_scout",
                "relation_type": "summarizes_evidence_claim",
                "target_id": "evidence_claim:player_form",
                "weight": 1.0,
                "attributes": {},
            },
        ]
        readiness = {
            "status": "ready_complete" if scouting_complete else "load_ready_with_scouting_backlog",
            "kg_load_ready": True,
            "scouting_complete": scouting_complete,
            "blocking_reasons": [],
            "forbidden_claim_counts": {},
            "scouting_backlog_count": 0 if scouting_complete else 1,
            "freshness_backlog_count": 0,
        }
        manifest = {
            "schema_version": "scouting-kg-v1",
            "graph_id": "world_graph:round:test",
            "round_id": "round:test",
            "files": {
                "world_graph": "world_graph.json",
                "scouting_audit": "scouting_audit.json",
                "findings": "findings.json",
                "knowledge_views": "knowledge_views.json",
            },
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "entity_counts": {
                "match": 1,
                "team": 2,
                "finding": 1,
                "evidence_claim": 1,
                "scouting_topic": 1,
                "team_scouting_topic": 1,
                "team_match_profile": 1,
                "player_match_profile": 1,
                "source_domain_profile": 1,
                "scout_match_profile": 1,
            },
            "relationship_counts": {
                "plays_home_in": 1,
                "has_evidence_claim": 1,
                "summarizes_evidence_claim": 4,
            },
            "entrypoint_entity_types": [
                "match",
                "team_match_profile",
                "team_scouting_topic",
                "player_match_profile",
                "source_domain_profile",
                "scout_match_profile",
                "scouting_gap",
            ],
            "required_entity_types_present": {
                "match": True,
                "team": True,
                "finding": True,
                "evidence_claim": True,
                "scouting_topic": True,
                "team_scouting_topic": True,
                "team_match_profile": True,
                "source_domain_profile": True,
            },
            "profile_entity_types": [
                "team_match_profile",
                "player_match_profile",
                "source_domain_profile",
                "scout_match_profile",
            ],
            "lineage_relation": "summarizes_evidence_claim",
            "integrity": {"passes": True},
            "readiness": readiness,
            "ingestion_policy": {"source_of_truth": "world_graph.json"},
        }
        audit = {
            "kg_readiness": readiness,
            "scouting_backlog": {
                "item_count": 0 if scouting_complete else 1,
                "items": []
                if scouting_complete
                else [{"status": "needs_rescout", "team": "Morocco", "claim_type": "lineup"}],
            },
        }
        graph = {
            "schema_version": "scouting-kg-v1",
            "graph_id": "world_graph:round:test",
            "round_id": "round:test",
            "entities": entities,
            "relationships": relationships,
        }
        for path, payload in {
            "kg_manifest.json": manifest,
            "world_graph.json": graph,
            "scouting_audit.json": audit,
            "findings.json": [],
            "knowledge_views.json": [],
        }.items():
            (run_path / path).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
        self.assertEqual(topics["player_form"]["scout_names"], ["player_form_scout"])
        self.assertEqual(topics["player_form"]["claim_quality_counts"]["metric_backed"], 1)
        self.assertEqual(topics["player_form"]["claim_quality_counts"]["match_actionable"], 1)
        self.assertEqual(topics["tactical"]["coverage_status"], "missing")
        self.assertEqual(topics["tactical"]["claim_count"], 0)
        self.assertEqual(team_topics["Brazil player_form"]["coverage_status"], "covered")
        self.assertEqual(team_topics["Brazil player_form"]["claim_count"], 1)
        self.assertEqual(team_topics["Brazil player_form"]["metric_claim_count"], 1)
        self.assertEqual(team_topics["Brazil player_form"]["player_count"], 1)
        self.assertEqual(team_topics["Brazil player_form"]["scout_names"], ["player_form_scout"])
        self.assertEqual(team_topics["Brazil player_form"]["claim_quality_counts"]["player_specific"], 1)
        self.assertEqual(team_topics["Brazil player_form"]["claim_quality_counts"]["strong_or_official_source"], 1)
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
        self.assertTrue(any(rel.relation_type == "covered_by_scout" for rel in graph.relationships))

        audit = _team_scouting_coverage_audit(type("Result", (), {"world_graph": graph})())
        rows = {row["team"]: row for row in audit["teams"]}
        self.assertEqual(rows["Brazil"]["claim_types"]["player_form"]["coverage_status"], "covered")
        self.assertEqual(rows["Brazil"]["claim_types"]["player_form"]["claim_count"], 1)
        self.assertEqual(rows["Brazil"]["claim_types"]["player_form"]["scout_names"], ["player_form_scout"])
        self.assertEqual(rows["Brazil"]["claim_types"]["player_form"]["claim_quality_counts"]["metric_backed"], 1)
        self.assertEqual(rows["Brazil"]["scout_names"], ["player_form_scout"])
        self.assertEqual(rows["Brazil"]["claim_quality_counts"]["match_actionable"], 1)
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

    def test_world_graph_integrity_accepts_synthesis_debate_claims_without_forecasts(self) -> None:
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=[],
        )
        claim = DebateClaim(
            round_id="round:test",
            speaker_id="colony_synthesis",
            speaker_name="Colony synthesis",
            model="synthesis",
            persona="synthesis",
            access_tier="public",
            visible_findings=0,
            claim_type="synthesis",
            selection_reason="final",
            stated_home_probability=0.55,
            confidence=0.5,
            direction="home",
            message="Brazil lean.",
        )

        graph = build_world_graph(match, claims=[claim])
        integrity = _kg_integrity_audit(type("Result", (), {"world_graph": graph})())

        self.assertTrue(any(entity.entity_id == "predictor:colony_synthesis" for entity in graph.entities))
        self.assertTrue(integrity["passes"])
        self.assertEqual(integrity["orphan_relationship_count"], 0)

    def test_kg_readiness_blocks_forbidden_claim_types(self) -> None:
        finding = Finding(
            finding_id="round:test:history_noise",
            scout_name="noisy_profile_scout",
            access_level="public",
            source_type="stats",
            finding_name="noisy_profile",
            home_probability=0.55,
            home_delta=0.0,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/history"],
            evidence_claims=[
                {
                    "claim_type": "team_history",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil joined FIFA in 1923.",
                    "impact": "context_home",
                    "confidence": 0.5,
                    "source_title": "Brazil profile",
                    "source_url": "https://example.test/history",
                    "source_kind": "reference",
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
        readiness = _kg_readiness_audit(type("Result", (), {"findings": [finding], "world_graph": graph})())

        self.assertFalse(readiness["kg_load_ready"])
        self.assertIn("forbidden_claim_types_present", readiness["blocking_reasons"])
        self.assertEqual(readiness["forbidden_claim_counts"]["team_history"], 1)

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

        self.assertEqual(team_topics["Brazil injury_availability"]["coverage_status"], "needs_better_evidence")
        self.assertEqual(team_topics["Brazil injury_availability"]["quality_status"], "needs_better_evidence")
        self.assertEqual(team_topics["Brazil injury_availability"]["quality_reasons"], ["needs_recent_source"])
        self.assertEqual(team_topics["Brazil injury_availability"]["freshness_status"], "needs_fresh_source")
        self.assertEqual(team_topics["Brazil injury_availability"]["recent_30d_claim_count"], 0)
        self.assertEqual(gaps["Brazil injury_availability gap"]["status"], "needs_fresh_rescout")
        self.assertEqual(gaps["Brazil injury_availability gap"]["gap_reason"], "needs_better_evidence")
        self.assertEqual(gaps["Brazil injury_availability gap"]["quality_reasons"], ["needs_recent_source"])

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
                },
                {
                    "claim_type": "match_history",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil have won 2 of their 3 previous meetings with Morocco.",
                    "impact": "context_home",
                    "confidence": 0.54,
                    "source_title": "Brazil Morocco H2H record",
                    "source_url": "https://example.test/h2h-record",
                    "source_kind": "stats",
                    "source_quality": "strong",
                    "metrics": {
                        "historical_team_a": "Brazil",
                        "historical_team_b": "Morocco",
                        "historical_team_a_wins": 2,
                        "historical_meetings": 3,
                        "h2h_recent_sample_matches": 5,
                        "h2h_team_a_wins": 3,
                        "h2h_draws": 1,
                        "h2h_team_a_losses": 1,
                        "h2h_team_a_goals_per_match": 2.6,
                        "historical_record_signal": "h2h_record",
                    },
                },
                {
                    "claim_type": "recent_form",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil are unbeaten in their last 6 matches, won 4 of their last 6, scored 12 goals in their last 6 and conceded 4 goals in their last 6.",
                    "impact": "context_home",
                    "confidence": 0.56,
                    "source_title": "Brazil recent form",
                    "source_url": "https://example.test/recent-form",
                    "source_kind": "stats",
                    "source_quality": "strong",
                    "metrics": {
                        "recent_sample_matches": 6,
                        "recent_wins": 4,
                        "unbeaten_matches": 6,
                        "recent_goals_for": 12,
                        "recent_goals_against": 4,
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
        team_profiles = {
            entity.attributes["team"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "team_match_profile"
        }
        brazil_profile = team_profiles["Brazil"]
        self.assertEqual(brazil_profile["recent_form_summary"]["recent_sample_matches_max"], 6)
        self.assertEqual(brazil_profile["recent_form_summary"]["recent_wins_max"], 4)
        self.assertEqual(brazil_profile["recent_form_summary"]["recent_goals_for_max"], 12)
        self.assertEqual(brazil_profile["recent_form_summary"]["recent_goals_against_max"], 4)
        self.assertEqual(brazil_profile["match_history_summary"]["historical_team_a_wins_max"], 2)
        self.assertEqual(brazil_profile["match_history_summary"]["historical_meetings_max"], 3)
        self.assertEqual(brazil_profile["match_history_summary"]["h2h_recent_sample_matches_max"], 5)
        self.assertEqual(brazil_profile["match_history_summary"]["h2h_team_a_wins_max"], 3)
        self.assertEqual(brazil_profile["match_history_summary"]["h2h_draws_max"], 1)
        self.assertEqual(brazil_profile["match_history_summary"]["h2h_team_a_losses_max"], 1)
        self.assertEqual(brazil_profile["match_history_summary"]["h2h_team_a_goals_per_match_max"], 2.6)
        self.assertEqual(brazil_profile["claim_quality_counts"]["h2h_record"], 1)
        self.assertEqual(brazil_profile["claim_quality_counts"]["recent_results_window"], 1)

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

    def test_world_graph_flags_conflicting_player_availability(self) -> None:
        findings = [
            Finding(
                finding_id="round:test:availability_a",
                scout_name="availability_scout",
                access_level="public",
                source_type="lineup",
                finding_name="availability_a",
                home_probability=0.52,
                home_delta=-0.03,
                confidence=0.5,
                cost=0.0,
                citations=["https://example.test/doubtful"],
                evidence_claims=[
                    {
                        "claim_type": "injury_availability",
                        "subject": "Neymar",
                        "team": "Brazil",
                        "player": "Neymar",
                        "claim": "Neymar is doubtful with a calf issue.",
                        "impact": "negative_home",
                        "confidence": 0.58,
                        "source_title": "Brazil injury report",
                        "source_url": "https://example.test/doubtful",
                        "source_kind": "news",
                        "source_quality": "strong",
                        "metrics": {"availability_status": "doubtful", "injury_body_part": "calf"},
                    }
                ],
            ),
            Finding(
                finding_id="round:test:availability_b",
                scout_name="telegram_social_scout",
                access_level="shared",
                source_type="social",
                finding_name="availability_b",
                home_probability=0.51,
                home_delta=-0.04,
                confidence=0.42,
                cost=0.0,
                citations=["telegram://BrazilTeamNews/11"],
                evidence_claims=[
                    {
                        "claim_type": "injury_availability",
                        "subject": "Neymar",
                        "team": "Brazil",
                        "player": "Neymar",
                        "claim": "Official: Neymar is ruled out for Brazil.",
                        "impact": "negative_home",
                        "confidence": 0.6,
                        "source_title": "Telegram:BrazilTeamNews",
                        "source_url": "telegram://BrazilTeamNews/11",
                        "source_kind": "social",
                        "source_quality": "medium",
                        "metrics": {"availability_status": "out", "verification_signal": "official"},
                    }
                ],
            ),
        ]
        match = MatchContext(
            round_id="round:test",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.55,
            stats_home_signal=0.54,
            odds_home_signal=0.55,
            news_home_signal=0.56,
            findings=findings,
        )

        graph = build_world_graph(match)
        player_profiles = {
            entity.attributes["player"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "player_match_profile"
        }
        team_profiles = {
            entity.attributes["team"]: entity.attributes
            for entity in graph.entities
            if entity.entity_type == "team_match_profile"
        }

        self.assertEqual(player_profiles["Neymar"]["availability_statuses"], ["doubtful", "out"])
        self.assertEqual(player_profiles["Neymar"]["availability_status_counts"], {"doubtful": 1, "out": 1})
        self.assertTrue(player_profiles["Neymar"]["availability_conflict"])
        self.assertEqual(team_profiles["Brazil"]["availability_conflict_players"], ["Neymar"])
        self.assertEqual(team_profiles["Brazil"]["availability_status_counts"], {"doubtful": 1, "out": 1})

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

    def test_world_graph_rejects_unknown_or_missing_impact_claims(self) -> None:
        finding = Finding(
            finding_id="round:test:bad_impact",
            scout_name="raw_adapter_scout",
            access_level="public",
            source_type="news",
            finding_name="bad_impact_claims",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/bad-impact"],
            evidence_claims=[
                {
                    "claim_type": "lineup",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil have a possible team-news signal.",
                    "impact": "unknown",
                    "confidence": 0.4,
                    "source_title": "Brazil team news",
                    "source_url": "https://example.test/bad-impact",
                    "source_kind": "news",
                    "source_quality": "medium",
                    "metrics": {},
                },
                {
                    "claim_type": "player_form",
                    "subject": "Raphinha",
                    "team": "Brazil",
                    "player": "Raphinha",
                    "claim": "Raphinha has 18 goals this season.",
                    "confidence": 0.55,
                    "source_title": "Raphinha season stats",
                    "source_url": "https://example.test/missing-impact",
                    "source_kind": "stats",
                    "source_quality": "strong",
                    "metrics": {"goals": 18},
                },
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
        admission = _kg_admission_audit(type("Result", (), {"findings": [finding], "world_graph": graph})())

        self.assertFalse(any(entity.entity_type == "evidence_claim" for entity in graph.entities))
        self.assertEqual(admission["raw_claim_count"], 2)
        self.assertEqual(admission["admitted_claim_count"], 0)
        self.assertEqual(admission["rejected_claim_count"], 2)
        self.assertEqual(admission["rejection_reasons"], {"missing_impact": 1, "unknown_impact": 1})

    def test_player_form_topic_requires_player_season_metric_for_coverage(self) -> None:
        finding = Finding(
            finding_id="round:test:vague_player_form",
            scout_name="player_form_scout",
            access_level="public",
            source_type="news",
            finding_name="vague_player_form",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/player-form"],
            evidence_claims=[
                {
                    "claim_type": "player_form",
                    "subject": "Raphinha",
                    "team": "Brazil",
                    "player": "Raphinha",
                    "claim": "Raphinha has been important for Brazil this season.",
                    "impact": "context_home",
                    "confidence": 0.55,
                    "source_title": "Brazil player report",
                    "source_url": "https://example.test/player-form",
                    "source_kind": "news",
                    "source_quality": "strong",
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
        audit = _team_scouting_coverage_audit(type("Result", (), {"world_graph": graph})())
        brazil = next(row for row in audit["teams"] if row["team"] == "Brazil")

        self.assertEqual(team_topics["Brazil player_form"]["coverage_status"], "needs_better_evidence")
        self.assertEqual(team_topics["Brazil player_form"]["quality_reasons"], ["needs_player_season_metric"])
        self.assertEqual(gaps["Brazil player_form gap"]["gap_reason"], "needs_better_evidence")
        self.assertEqual(gaps["Brazil player_form gap"]["quality_reasons"], ["needs_player_season_metric"])
        self.assertIn("player_form", brazil["missing_required_claim_types"])

    def test_lineup_topic_is_covered_by_predicted_lineups_signal(self) -> None:
        metrics = _claim_metrics("lineup", "Brazil vs Morocco predicted line-ups and probable starting XI")
        finding = Finding(
            finding_id="round:test:lineup",
            scout_name="squad_depth_scout",
            access_level="public",
            source_type="lineup",
            finding_name="lineup_signal",
            home_probability=0.56,
            home_delta=0.01,
            confidence=0.5,
            cost=0.0,
            citations=["https://example.test/lineups"],
            evidence_claims=[
                {
                    "claim_type": "lineup",
                    "subject": "Brazil",
                    "team": "Brazil",
                    "player": "",
                    "claim": "Brazil vs Morocco predicted line-ups and probable starting XI.",
                    "impact": "context_home",
                    "confidence": 0.58,
                    "source_title": "Brazil Morocco predicted line-ups",
                    "source_url": "https://example.test/lineups",
                    "source_published_date": "2026-06-13",
                    "source_recency_days": 0,
                    "source_recency_bucket": "last_7_days",
                    "source_kind": "news",
                    "source_quality": "strong",
                    "metrics": metrics,
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
        qualities = {entity.name for entity in graph.entities if entity.entity_type == "claim_quality"}

        self.assertEqual(team_topics["Brazil lineup"]["coverage_status"], "covered")
        self.assertEqual(team_topics["Brazil lineup"]["quality_status"], "usable")
        self.assertEqual(team_topics["Brazil lineup"]["claim_quality_counts"]["lineup_signal"], 1)
        self.assertIn("lineup_signal", qualities)

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
