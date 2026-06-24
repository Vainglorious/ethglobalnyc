"""Tests for natural judgment normalization."""

from __future__ import annotations

import unittest

from .models import Forecast, MatchContext
from .reasoning import CamelReasoner, CamelReasonerConfig, apply_judgment_to_forecast, normalize_judgment


def _forecast() -> Forecast:
    return Forecast(
        agent_id="ant_0001",
        wallet_address="",
        ens_name="",
        access_tier="public",
        visible_findings=2,
        persona="test persona",
        risk_profile="balanced",
        social_stance="supportive_home",
        activity_level="regular",
        influence_weight="medium",
        response_delay="normal",
        active_windows="pre_match",
        home_probability=0.55,
        market_edge=0.05,
        edge_threshold=0.03,
        edge=0.05,
        side="home",
        stake=5.0,
        bankroll=100.0,
        decision_reason="legacy reason",
    )


class ReasoningTests(unittest.TestCase):
    def test_non_bet_intent_becomes_micro_survival_stake(self) -> None:
        match = MatchContext(
            round_id="round_1",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        judgment = normalize_judgment(
            {
                "stance": "undecided",
                "civic_choice": "draw",
                "conviction": "low",
                "intent": "buy_info",
                "risk_intent": "aggressive",
                "thesis": "The draw is the least bad civic choice, but I do not like the risk.",
                "main_signal": "mixed",
                "risk_read": "too_risky",
                "one_line": "I need a stronger thesis before risking more than micro.",
            },
            agent_id="ant_0001",
            persona_id="source_auditor",
            input_style="structured_evidence_cards",
            source="camel",
        )

        updated = apply_judgment_to_forecast(forecast=_forecast(), match=match, judgment=judgment)

        self.assertEqual(judgment.risk_intent, "micro")
        self.assertEqual(judgment.action, "commit_stake")
        self.assertEqual(judgment.commitment_label, "micro")
        self.assertEqual(judgment.stake_level, "micro")
        self.assertEqual(updated.judgment["risk_read"], "too_risky")
        self.assertGreater(updated.stake, 0.0)
        self.assertLess(updated.stake, 1.0)
        self.assertEqual(updated.side, "draw")
        self.assertEqual(updated.judgment["civic_choice"], "draw")
        self.assertEqual(updated.judgment["intent"], "bet")
        self.assertEqual(updated.judgment["action"], "commit_stake")
        self.assertEqual(updated.judgment["stake_level"], "micro")
        self.assertIn("micro", updated.decision_reason)

    def test_bet_intent_can_update_side_and_scale_stake(self) -> None:
        match = MatchContext(
            round_id="round_1",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        judgment = normalize_judgment(
            {
                "stance": "away",
                "civic_choice": "away",
                "conviction": "medium",
                "intent": "bet",
                "risk_intent": "small",
                "thesis": "The consensus is too crowded.",
                "main_signal": "market_mispricing",
                "risk_read": "acceptable",
                "one_line": "The consensus is too crowded.",
            },
            agent_id="ant_0001",
            persona_id="contrarian",
            input_style="structured_evidence_cards",
            source="camel",
        )

        updated = apply_judgment_to_forecast(forecast=_forecast(), match=match, judgment=judgment)

        self.assertEqual(updated.side, "away")
        self.assertEqual(updated.stake, 2.25)
        self.assertLess(updated.home_probability, 0.55)
        self.assertEqual(updated.judgment["action"], "commit_stake")
        self.assertEqual(updated.judgment["commitment_label"], "small")
        self.assertEqual(updated.judgment["risk_intent"], "small")
        self.assertEqual(updated.judgment["stake_level"], "small")
        self.assertEqual(updated.judgment["risk_read"], "acceptable")

    def test_camel_error_uses_micro_survival_fallback(self) -> None:
        match = MatchContext(
            round_id="round_1",
            home_team="France",
            away_team="Argentina",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
        )
        judgment = normalize_judgment(
            {
                "stance": "undecided",
                "civic_choice": "draw",
                "conviction": "very_low",
                "intent": "pass",
                "risk_intent": "none",
                "one_line": "CAMEL unavailable.",
            },
            agent_id="ant_0001",
            persona_id="source_auditor",
            input_style="structured_evidence_cards",
            source="camel_error",
        )

        updated = apply_judgment_to_forecast(forecast=_forecast(), match=match, judgment=judgment)

        self.assertGreater(updated.stake, 0.0)
        self.assertLess(updated.stake, 1.0)
        self.assertEqual(updated.side, "home")
        self.assertEqual(updated.judgment["action"], "commit_stake")
        self.assertEqual(updated.judgment["commitment_label"], "micro")
        self.assertEqual(updated.judgment["risk_intent"], "micro")
        self.assertEqual(updated.judgment["stake_level"], "micro")
        self.assertEqual(updated.judgment["risk_read"], "too_risky")
        self.assertEqual(updated.judgment["source"], "camel_error")
        self.assertIn("fallback", updated.judgment["thesis"].lower())

    def test_public_action_is_compat_only_and_becomes_micro_commitment(self) -> None:
        judgment = normalize_judgment(
            {
                "stance": "home",
                "civic_choice": "home",
                "conviction": "medium",
                "action": "challenge_source",
                "risk_intent": "medium",
                "action_target": "E2 source_quality",
                "thesis": "The injury angle matters, but I size it as survival risk.",
                "main_signal": "injury",
                "one_line": "The injury claim is useful only if the source survives audit.",
            },
            agent_id="ant_0001",
            persona_id="source_auditor",
            input_style="structured_evidence_cards",
            source="camel",
        )

        self.assertEqual(judgment.intent, "bet")
        self.assertEqual(judgment.action, "commit_stake")
        self.assertEqual(judgment.risk_intent, "micro")
        self.assertEqual(judgment.commitment_label, "micro")
        self.assertEqual(judgment.stake_level, "micro")
        self.assertEqual(judgment.action_target, "E2 source_quality")

    def test_normalizes_common_llm_aliases_before_validation(self) -> None:
        judgment = normalize_judgment(
            {
                "stance": "home",
                "persona_id": "ant_0001",
                "civic_choice": "home",
                "conviction": "solid",
                "action": "commit_stake",
                "commitment_label": "3",
                "risk_read": "reasonable",
                "thesis": "Brazil's lineup and recent form are enough for a controlled position.",
                "main_signal": "lineup form",
                "social_move": "support",
            },
            agent_id="ant_0001",
            persona_id="tactical_scout",
            input_style="structured_evidence_cards",
            source="camel",
        )

        self.assertEqual(judgment.persona_id, "tactical_scout")
        self.assertEqual(judgment.conviction, "medium")
        self.assertEqual(judgment.stake_level, "medium")
        self.assertEqual(judgment.commitment_label, "medium")
        self.assertEqual(judgment.risk_intent, "medium")
        self.assertEqual(judgment.risk_read, "acceptable")
        self.assertEqual(judgment.social_move, "defend")

    def test_camel_reasoner_clamps_too_short_timeout(self) -> None:
        reasoner = CamelReasoner(CamelReasonerConfig(timeout_seconds=8))

        self.assertGreaterEqual(reasoner.config.timeout_seconds, 30)


if __name__ == "__main__":
    unittest.main()
