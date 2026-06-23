"""Tests for Supabase prematch snapshot injection in run_match."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

import run_match  # noqa: E402


class PrematchSnapshotRunnerTest(unittest.TestCase):
    def test_supabase_claim_rows_become_public_findings(self) -> None:
        match = SimpleNamespace(
            round_id="worldcup_2026_france_iraq",
            home_team="France",
            away_team="Iraq",
            market_home_probability=0.52,
        )
        rows = [
            {
                "claim_id": "claim_1",
                "team": "France",
                "subject": "France vs Iraq pre-match coverage",
                "claim_type": "social_signal",
                "claim": "France training sentiment is positive before kickoff.",
                "confidence": 0.7,
                "source_kind": "social",
                "source_domain": "x.com",
                "source_title": "@team",
                "source_url": "https://x.com/team/status/1",
                "source_published": "2026-06-22T20:00:00Z",
                "available_at_utc": "2026-06-22T20:00:00Z",
                "source_quality": "medium",
                "metrics": {"signal_type": "social_context"},
            }
        ]

        findings = run_match._prematch_findings_from_claim_rows(
            snapshot_id="snapshot_france_iraq",
            rows=rows,
            match=match,
        )

        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding.scout_name, "supabase_prematch_snapshot")
        self.assertEqual(finding.access_level, "public")
        self.assertEqual(finding.source_type, "social")
        self.assertIsNone(finding.home_probability)
        self.assertEqual(finding.evidence_claims[0]["snapshot_id"], "snapshot_france_iraq")
        self.assertEqual(finding.evidence_claims[0]["available_at_utc"], "2026-06-22T20:00:00Z")
        self.assertEqual(finding.citations, ["https://x.com/team/status/1"])

    def test_explicit_claim_probability_is_preserved(self) -> None:
        match = SimpleNamespace(
            round_id="worldcup_2026_france_iraq",
            home_team="France",
            away_team="Iraq",
            market_home_probability=0.52,
        )
        rows = [
            {
                "claim_id": "market_1",
                "claim_type": "market_anchor",
                "claim": "Market implied France probability is 61%.",
                "confidence": 0.9,
                "source_kind": "market",
                "source_url": "https://example.test/market",
                "metrics": {"binary_home_probability": 0.61},
            }
        ]

        findings = run_match._prematch_findings_from_claim_rows(
            snapshot_id="snapshot_france_iraq",
            rows=rows,
            match=match,
        )

        self.assertEqual(findings[0].source_type, "market")
        self.assertEqual(findings[0].home_probability, 0.61)
        self.assertEqual(findings[0].home_delta, 0.09)

    def test_market_signal_is_mapped_to_odds_with_impact_probability(self) -> None:
        match = SimpleNamespace(
            round_id="worldcup_2026_france_iraq",
            home_team="France",
            away_team="Iraq",
            market_home_probability=0.5,
        )
        rows = [
            {
                "claim_id": "odds_1",
                "claim_type": "market_signal",
                "claim": "Can Iraq beat France? Nah, just a 4% chance.",
                "impact": "context_home",
                "confidence": 0.8,
                "source_kind": "social",
                "source_url": "https://example.test/odds",
                "metrics": {"signal_type": "prediction_or_market", "home_minus_away": 0.0},
            }
        ]

        findings = run_match._prematch_findings_from_claim_rows(
            snapshot_id="snapshot_france_iraq",
            rows=rows,
            match=match,
        )

        self.assertEqual(findings[0].source_type, "odds")
        self.assertGreater(findings[0].home_probability, 0.5)
        self.assertGreater(findings[0].home_delta, 0.0)

    def test_snapshot_impact_claims_create_source_signal(self) -> None:
        match = SimpleNamespace(
            round_id="worldcup_2026_france_iraq",
            home_team="France",
            away_team="Iraq",
            market_home_probability=0.5,
        )
        rows = [
            {
                "claim_id": "news_1",
                "claim_type": "prematch_media_signal",
                "claim": "France Aim to Dominate Group I.",
                "impact": "context_home",
                "confidence": 0.6,
                "source_kind": "news",
                "source_url": "https://example.test/news",
                "metrics": {"signal_type": "media_preview"},
            },
            {
                "claim_id": "news_2",
                "claim_type": "prematch_media_signal",
                "claim": "Iraq injury concern before France.",
                "impact": "context_away",
                "confidence": 0.6,
                "source_kind": "news",
                "source_url": "https://example.test/news2",
                "metrics": {"signal_type": "media_preview"},
            },
        ]

        findings = run_match._prematch_findings_from_claim_rows(
            snapshot_id="snapshot_france_iraq",
            rows=rows,
            match=match,
        )

        self.assertEqual(findings[0].source_type, "news")
        self.assertAlmostEqual(findings[0].home_probability, 0.5, places=4)


if __name__ == "__main__":
    unittest.main()
