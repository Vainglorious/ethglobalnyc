"""Tests for ant minds and lightweight memory logging."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from .harness import ColonyHarness
from .memory import JsonAntMemoryStore, forecast_memory_signal, forecast_memory_text
from .models import MatchContext


class MindMemoryTests(unittest.TestCase):
    def test_json_memory_is_scoped_by_ant(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonAntMemoryStore(Path(tmpdir) / "memory.jsonl")
            store.remember(agent_id="ant_0001", text="I trust audited odds.", metadata={"round_id": "r1"})
            store.remember(agent_id="ant_0002", text="I chase sentiment.", metadata={"round_id": "r1"})

            recall = store.recall(agent_id="ant_0001", query="audited odds", limit=5)

            self.assertEqual(len(recall["results"]), 1)
            self.assertEqual(recall["results"][0]["agent_id"], "ant_0001")
            self.assertIn("audited odds", recall["results"][0]["memory"])

    def test_json_memory_does_not_fallback_to_unrelated_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = JsonAntMemoryStore(Path(tmpdir) / "memory.jsonl")
            store.remember(
                agent_id="ant_0001",
                text="France vs Senegal ended home.",
                metadata={"home_team": "France", "away_team": "Senegal", "result_side": "home"},
            )

            recall = store.recall(
                agent_id="ant_0001",
                query="past match memory",
                limit=5,
                metadata={"home_team": "Brazil", "away_team": "Morocco"},
            )

            self.assertEqual(recall["results"], [])
            self.assertEqual(recall["candidate_count"], 0)
            self.assertEqual(recall["filtered_count"], 1)

    def test_forecast_memory_signal_uses_settled_relevant_results(self) -> None:
        signal = forecast_memory_signal(
            {
                "results": [
                    {"metadata": {"result_side": "home", "side": "home"}},
                    {"metadata": {"result_side": "away", "side": "home"}},
                ]
            }
        )

        self.assertTrue(signal["available"])
        self.assertEqual(signal["samples"], 2)
        self.assertEqual(signal["home_probability"], 0.5)
        self.assertEqual(signal["confidence"], 0.95)
        self.assertEqual(signal["self_correct_rate"], 0.5)

    def test_forecast_memory_text_names_risk_profile(self) -> None:
        text = forecast_memory_text(
            forecast={"round_id": "r1", "side": "away", "risk_profile": "risky", "decision_reason": "thin edge"},
            mind={"label": "contrarian"},
        )

        self.assertIn("risk profile risky", text)
        self.assertNotIn("risky risk", text)

    def test_round_logs_minds_memory_and_class_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_backend = os.environ.get("COLONY_MEMORY_BACKEND")
            old_path = os.environ.get("COLONY_MEMORY_PATH")
            os.environ["COLONY_MEMORY_BACKEND"] = "json"
            os.environ["COLONY_MEMORY_PATH"] = str(Path(tmpdir) / "memory.jsonl")
            try:
                harness = ColonyHarness(population_size=12, speaker_slots=4, seed=7)
                match = MatchContext(
                    round_id="round_mind_memory",
                    home_team="France",
                    away_team="Senegal",
                    market_home_probability=0.47,
                    stats_home_signal=0.55,
                    odds_home_signal=0.48,
                    news_home_signal=0.51,
                )

                result = harness.run_round(match)
            finally:
                _restore_env("COLONY_MEMORY_BACKEND", old_backend)
                _restore_env("COLONY_MEMORY_PATH", old_path)

        self.assertEqual(len(result.agent_minds), 12)
        self.assertEqual(len(result.memory_recall), 12)
        self.assertEqual(len(result.memory_writes), 12)
        self.assertEqual(len(result.class_transitions), 12)
        self.assertTrue(result.summary["archetypes"])
        self.assertTrue(result.summary["social_classes"])
        self.assertTrue(result.forecasts[0].archetype)
        self.assertTrue(result.forecasts[0].mind_summary)
        self.assertIn("memory_backend", result.summary)

    def test_round_can_disable_memory_writes_for_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_backend = os.environ.get("COLONY_MEMORY_BACKEND")
            old_path = os.environ.get("COLONY_MEMORY_PATH")
            memory_path = Path(tmpdir) / "memory.jsonl"
            os.environ["COLONY_MEMORY_BACKEND"] = "json"
            os.environ["COLONY_MEMORY_PATH"] = str(memory_path)
            try:
                harness = ColonyHarness(
                    population_size=8,
                    speaker_slots=4,
                    seed=8,
                    memory_write_enabled=False,
                )
                match = MatchContext(
                    round_id="round_readonly_memory",
                    home_team="France",
                    away_team="Iraq",
                    market_home_probability=0.52,
                    stats_home_signal=0.54,
                    odds_home_signal=0.51,
                    news_home_signal=0.53,
                )

                result = harness.run_round(match)
            finally:
                _restore_env("COLONY_MEMORY_BACKEND", old_backend)
                _restore_env("COLONY_MEMORY_PATH", old_path)

        self.assertEqual(len(result.memory_recall), 8)
        self.assertEqual(result.memory_writes, [])
        self.assertEqual(result.summary["memory_writes"], 0)
        self.assertFalse(result.summary["memory_write_enabled"])
        self.assertFalse(memory_path.exists())


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
