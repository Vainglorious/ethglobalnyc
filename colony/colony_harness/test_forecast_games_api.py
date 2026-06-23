"""Tests for forecast game metadata exposed by the API."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from colony_api import main as api


class ForecastGamesApiTest(unittest.TestCase):
    def test_marks_only_games_with_prematch_snapshots_as_previous_testable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kg_path = root / "world_cup_kg.json"
            kg_path.write_text(
                json.dumps(
                    {
                        "entities": [
                            {
                                "entity_id": "match:world_cup_2026:051:2026_06_22_france_iraq",
                                "entity_type": "match",
                                "name": "France vs Iraq",
                                "attributes": {
                                    "team1": "France",
                                    "team2": "Iraq",
                                    "date": "2026-06-22",
                                    "time": "17:00 UTC-4",
                                    "round": "Matchday 12",
                                    "group": "Group I",
                                    "ground": "Philadelphia",
                                },
                            },
                            {
                                "entity_id": "match:world_cup_2026:052:2026_06_22_norway_senegal",
                                "entity_type": "match",
                                "name": "Norway vs Senegal",
                                "attributes": {
                                    "team1": "Norway",
                                    "team2": "Senegal",
                                    "date": "2026-06-22",
                                    "time": "20:00 UTC-4",
                                    "round": "Matchday 12",
                                    "group": "Group I",
                                    "ground": "New York/New Jersey",
                                },
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            scrape_dir = root / "prematch_scrape" / "france_iraq_pre_kickoff_20260622"
            (scrape_dir / "kg").mkdir(parents=True)
            (scrape_dir / "normalized").mkdir(parents=True)
            (scrape_dir / "kg" / "prematch_kg_source.json").write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "finding_id": "prematch_news_scrape:france_vs_iraq",
                                "evidence_claims": [
                                    {"claim_type": "lineup", "claim": "France rotated midfield."},
                                    {"claim_type": "social_signal", "claim": "Iraq fans were optimistic."},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (scrape_dir / "normalized" / "prematch_documents.json").write_text(
                json.dumps(
                    {
                        "created_at_utc": "2026-06-22T20:48:10+00:00",
                        "match": {
                            "home_team": "France",
                            "away_team": "Iraq",
                            "kickoff_utc": "2026-06-22T21:00:00Z",
                            "prediction_cutoff_utc": "2026-06-22T21:00:00Z",
                        },
                        "summary": {"total": 3, "usable": 2, "source_count": 2},
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(api, "WORLD_CUP_KG", kg_path),
                patch.object(api, "PREMATCH_SCRAPE_ROOT", root / "prematch_scrape"),
                patch.object(api, "PREMATCH_TEST_MANIFEST", root / "missing_manifest.json"),
                patch.object(api, "_prematch_supabase_index", return_value={}),
            ):
                light_games = api._forecast_games_from_kg(include_previous_test_data=False)
                games = api._forecast_games_from_kg(include_previous_test_data=True)

        light_by_name = {game["name"]: game for game in light_games}
        self.assertFalse(light_by_name["France vs Iraq"]["has_previous_test_data"])
        self.assertIsNone(light_by_name["France vs Iraq"]["previous_test_data"])
        by_name = {game["name"]: game for game in games}
        self.assertTrue(by_name["France vs Iraq"]["has_previous_test_data"])
        self.assertEqual(by_name["France vs Iraq"]["previous_test_data"]["usable_document_count"], 2)
        self.assertEqual(by_name["France vs Iraq"]["previous_test_data"]["evidence_claim_count"], 2)
        self.assertFalse(by_name["Norway vs Senegal"]["has_previous_test_data"])
        self.assertIsNone(by_name["Norway vs Senegal"]["previous_test_data"])

    def test_can_use_tracked_manifest_when_raw_prematch_runs_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kg_path = root / "world_cup_kg.json"
            kg_path.write_text(
                json.dumps(
                    {
                        "entities": [
                            {
                                "entity_id": "match:world_cup_2026:051:2026_06_22_france_iraq",
                                "entity_type": "match",
                                "name": "France vs Iraq",
                                "attributes": {
                                    "team1": "France",
                                    "team2": "Iraq",
                                    "date": "2026-06-22",
                                    "time": "17:00 UTC-4",
                                    "round": "Matchday 12",
                                    "group": "Group I",
                                    "ground": "Philadelphia",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "prematch_test_data_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "prematch-test-data-manifest-v1",
                        "entries": [
                            {
                                "match_slug": "france_vs_iraq",
                                "home_team": "France",
                                "away_team": "Iraq",
                                "kind": "prematch_scrape_manifest",
                                "usable_document_count": 168,
                                "evidence_claim_count": 168,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(api, "WORLD_CUP_KG", kg_path),
                patch.object(api, "PREMATCH_SCRAPE_ROOT", root / "missing_runs"),
                patch.object(api, "PREMATCH_TEST_MANIFEST", manifest_path),
                patch.object(api, "_prematch_supabase_index", return_value={}),
            ):
                games = api._forecast_games_from_kg(include_previous_test_data=True)

        self.assertTrue(games[0]["has_previous_test_data"])
        self.assertEqual(games[0]["previous_test_data"]["usable_document_count"], 168)
        self.assertEqual(games[0]["previous_test_data"]["kind"], "prematch_scrape_manifest")

    def test_prefers_supabase_snapshot_over_fallback_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kg_path = root / "world_cup_kg.json"
            kg_path.write_text(
                json.dumps(
                    {
                        "entities": [
                            {
                                "entity_id": "match:world_cup_2026:051:2026_06_22_france_iraq",
                                "entity_type": "match",
                                "name": "France vs Iraq",
                                "attributes": {
                                    "team1": "France",
                                    "team2": "Iraq",
                                    "date": "2026-06-22",
                                    "time": "17:00 UTC-4",
                                    "round": "Matchday 12",
                                    "group": "Group I",
                                    "ground": "Philadelphia",
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            manifest_path = root / "prematch_test_data_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "entries": [
                            {
                                "match_slug": "france_vs_iraq",
                                "kind": "prematch_scrape_manifest",
                                "usable_document_count": 1,
                                "evidence_claim_count": 1,
                                "source": "legacy-manifest",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            supabase_index = {
                "france_vs_iraq": {
                    "kind": "prematch_supabase_snapshot",
                    "source": "supabase:prematch_snapshots",
                    "snapshot_id": "worldcup_2026_france_vs_iraq_20260622T210000Z",
                    "usable_document_count": 168,
                    "evidence_claim_count": 168,
                }
            }

            with (
                patch.object(api, "WORLD_CUP_KG", kg_path),
                patch.object(api, "PREMATCH_SCRAPE_ROOT", root / "missing_runs"),
                patch.object(api, "PREMATCH_TEST_MANIFEST", manifest_path),
                patch.object(api, "_prematch_supabase_index", return_value=supabase_index),
            ):
                games = api._forecast_games_from_kg(include_previous_test_data=True)

        data = games[0]["previous_test_data"]
        self.assertEqual(data["kind"], "prematch_supabase_snapshot")
        self.assertEqual(data["snapshot_id"], "worldcup_2026_france_vs_iraq_20260622T210000Z")
        self.assertEqual(data["usable_document_count"], 168)
        self.assertEqual(data["fallback_sources"], ["legacy-manifest"])

    def test_previous_run_requires_prematch_snapshot_id(self) -> None:
        request = api.UserColonyRunRequest(match="France vs Iraq", run_mode="previous_test")

        with self.assertRaises(api.HTTPException) as raised:
            api._validate_previous_test_snapshot(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("prematch_snapshot_id", str(raised.exception.detail))

    def test_previous_run_rejects_missing_snapshot(self) -> None:
        request = api.UserColonyRunRequest(
            match="France vs Iraq",
            run_mode="previous_test",
            prematch_snapshot_id="missing_snapshot",
        )

        with patch.object(api, "_fetch_prematch_snapshot", return_value=None):
            with self.assertRaises(api.HTTPException) as raised:
                api._validate_previous_test_snapshot(request)

        self.assertEqual(raised.exception.status_code, 404)

    def test_previous_run_rejects_snapshot_for_other_match(self) -> None:
        request = api.UserColonyRunRequest(
            match="France vs Iraq",
            run_mode="previous_test",
            prematch_snapshot_id="portugal_uzbekistan",
        )
        snapshot = {
            "snapshot_id": "portugal_uzbekistan",
            "status": "ready",
            "home_team": "Portugal",
            "away_team": "Uzbekistan",
        }

        with patch.object(api, "_fetch_prematch_snapshot", return_value=snapshot):
            with self.assertRaises(api.HTTPException) as raised:
                api._validate_previous_test_snapshot(request)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("teams", str(raised.exception.detail))

    def test_public_benchmark_run_is_sanitized(self) -> None:
        row = {
            "pubkey": "ABCDEF1234567890",
            "run_id": "colony_1",
            "status": "succeeded",
            "created_at": "2026-06-23T00:00:00Z",
            "config_snapshot": {
                "run_mode": "previous_test",
                "prematch_snapshot_id": "snapshot_1",
                "colony": {"config": {"private_weight": 1}},
            },
            "artifacts": {
                "run_mode": "previous_test",
                "prematch_snapshot_id": "snapshot_1",
                "match": {"name": "France vs Iraq"},
                "snapshot": {"document_count": 168, "claim_count": 168},
                "prediction": {"winner": "France", "confidence": "medium"},
                "agent_count": 50,
            },
        }

        public = api._public_benchmark_run(row)

        self.assertEqual(public["run_id"], "colony_1")
        self.assertEqual(public["pubkey"], "ABCDEF1234567890")
        self.assertEqual(public["prematch_snapshot_id"], "snapshot_1")
        self.assertEqual(public["document_count"], 168)
        self.assertNotIn("config_snapshot", public)
        self.assertNotIn("colony", public)

    def test_previous_command_uses_snapshot_without_live_scout_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            request = api.UserColonyRunRequest(
                match="France vs Iraq",
                run_mode="previous_test",
                prematch_snapshot_id="snapshot_france_iraq",
                data_mode="public",
                refresh_data=True,
                include_x=True,
                include_camel=True,
                include_telegram=True,
                include_polygun=True,
                include_deepseek_scout=True,
            )

            command = api._build_colony_run_command("wallet_1", request, Path(tmp))

        self.assertIn("--prematch-snapshot-id", command)
        self.assertIn("snapshot_france_iraq", command)
        self.assertIn("--no-memory-writes", command)
        data_mode_index = command.index("--data-mode") + 1
        self.assertEqual(command[data_mode_index], "synthetic")
        self.assertNotIn("--refresh-data", command)
        self.assertNotIn("--include-x", command)
        self.assertNotIn("--include-camel", command)
        self.assertNotIn("--include-telegram", command)
        self.assertNotIn("--include-polygun", command)
        self.assertNotIn("--include-deepseek-scout", command)


if __name__ == "__main__":
    unittest.main()
