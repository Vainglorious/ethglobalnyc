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

            with patch.object(api, "WORLD_CUP_KG", kg_path), patch.object(api, "PREMATCH_SCRAPE_ROOT", root / "prematch_scrape"):
                games = api._forecast_games_from_kg()

        by_name = {game["name"]: game for game in games}
        self.assertTrue(by_name["France vs Iraq"]["has_previous_test_data"])
        self.assertEqual(by_name["France vs Iraq"]["previous_test_data"]["usable_document_count"], 2)
        self.assertEqual(by_name["France vs Iraq"]["previous_test_data"]["evidence_claim_count"], 2)
        self.assertFalse(by_name["Norway vs Senegal"]["has_previous_test_data"])
        self.assertIsNone(by_name["Norway vs Senegal"]["previous_test_data"])


if __name__ == "__main__":
    unittest.main()
