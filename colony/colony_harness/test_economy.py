"""Checks for the internal USDC economy ledger."""

from __future__ import annotations

import unittest

from .agent import AntAgent
from .economy import EconomyLedger, build_paid_knowledge_views, market_spec_for_match, settle_internal_pool
from .genes import Genome, SourceWeights
from .models import Finding, InternalStake, MarketSpec, MatchContext


def _genome(query_budget: float = 1.0) -> Genome:
    return Genome(
        estimator="poisson",
        model="parametric",
        risk_appetite=0.1,
        edge_threshold=0.02,
        source_weights=SourceWeights(stats=0.25, odds=0.25, news=0.25, debate=0.25),
        herd_bias=0.0,
        query_budget=query_budget,
        persona="cold probabilist",
    )


def _agent(agent_id: str, *, bankroll: float = 10.0, world_verified: bool = False) -> AntAgent:
    return AntAgent(
        agent_id=agent_id,
        name=agent_id.replace("_", "-"),
        generation=0,
        genome=_genome(),
        bankroll=bankroll,
        accuracy=0.5,
        world_verified=world_verified,
    )


class EconomyTests(unittest.TestCase):
    def test_group_stage_market_allows_draw_result(self) -> None:
        match = MatchContext(
            round_id="round_group",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            group_name="Group A",
            score="1-1",
        )

        spec = market_spec_for_match(match)

        self.assertEqual(spec.market_type, "three_way")
        self.assertEqual(spec.outcomes, ["home_win", "draw", "away_win"])
        self.assertEqual(spec.result_side, "draw")
        self.assertEqual(spec.settlement_status, "settled")

    def test_knockout_market_is_binary_qualification(self) -> None:
        match = MatchContext(
            round_id="round_ko",
            home_team="Brazil",
            away_team="Morocco",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            stage_name="Round of 16",
            score="2-1",
        )

        spec = market_spec_for_match(match)

        self.assertEqual(spec.market_type, "binary_qualification")
        self.assertEqual(spec.outcomes, ["home_qualifies", "away_qualifies"])
        self.assertEqual(spec.result_side, "home")

    def test_world_verified_agents_pay_discounted_data_price(self) -> None:
        finding = Finding(
            finding_id="finding:shared",
            scout_name="lineup_scout",
            access_level="shared",
            source_type="lineup",
            finding_name="lineup",
            home_probability=0.55,
            home_delta=0.02,
            confidence=0.7,
            cost=0.0,
        )
        match = MatchContext(
            round_id="round_data",
            home_team="France",
            away_team="Senegal",
            market_home_probability=0.5,
            stats_home_signal=0.5,
            odds_home_signal=0.5,
            news_home_signal=0.5,
            findings=[finding],
        )
        standard = _agent("ant_0000", bankroll=1.0)
        premium = _agent("ant_0001", bankroll=1.0, world_verified=True)
        ledger = EconomyLedger(match.round_id)

        views = build_paid_knowledge_views(match, [standard, premium], ledger)

        self.assertEqual(views[standard.agent_id].access_tier, "shared")
        self.assertEqual(views[premium.agent_id].access_tier, "shared")
        amounts = {receipt.payer_id: receipt.amount for receipt in ledger.payment_receipts}
        self.assertEqual(amounts[standard.agent_id], 0.05)
        self.assertEqual(amounts[premium.agent_id], 0.025)
        self.assertEqual(standard.bankroll, 0.95)
        self.assertEqual(premium.bankroll, 0.975)

    def test_settlement_distributes_losing_pool_80_10_10(self) -> None:
        winner = _agent("ant_0000", bankroll=0.0)
        contributor = _agent("ant_0001", bankroll=0.0)
        loser = _agent("ant_0002", bankroll=0.0)
        ledger = EconomyLedger("round_settle")
        ledger.internal_stakes = [
            InternalStake("round_settle", winner.agent_id, "home", 10.0, 1.0),
            InternalStake("round_settle", loser.agent_id, "away", 10.0, 1.0),
        ]
        ledger.record_contributor(contributor.agent_id, 1.0)
        spec = MarketSpec(
            round_id="round_settle",
            market_type="three_way",
            outcomes=["home_win", "draw", "away_win"],
            result_side="home",
            settlement_status="settled",
        )

        summary = settle_internal_pool(market_spec=spec, agents=[winner, contributor, loser], ledger=ledger)

        self.assertEqual(summary["losing_pool"], 10.0)
        self.assertEqual(summary["correct_reward_pool"], 8.0)
        self.assertEqual(summary["contributor_pool"], 1.0)
        self.assertEqual(summary["treasury_fee"], 1.0)
        self.assertEqual(winner.bankroll, 18.0)
        self.assertEqual(contributor.bankroll, 1.0)
        self.assertEqual(ledger.treasury_balance, 1.0)


if __name__ == "__main__":
    unittest.main()
