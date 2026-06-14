"""Internal USDC ledger for Colony v1.

This is intentionally an off-chain deterministic ledger. Real x402/Arc receipts
can later plug into the same PaymentReceipt/BalanceUpdate event shape.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import Iterable

from .agent import AntAgent
from .models import (
    BalanceUpdate,
    DebateRoom,
    Finding,
    Forecast,
    InternalStake,
    KnowledgeView,
    MarketSpec,
    MatchContext,
    PaymentReceipt,
    Side,
)


SHARED_FINDING_PRICE = 0.05
PRIVATE_FINDING_PRICE = 0.12
WORLD_DISCOUNT = 0.5
ROOM_SUMMARY_FEE = 0.03
TREASURY_ID = "colony_treasury"


class EconomyLedger:
    def __init__(self, round_id: str) -> None:
        self.round_id = round_id
        self.payment_receipts: list[PaymentReceipt] = []
        self.balance_updates: list[BalanceUpdate] = []
        self.internal_stakes: list[InternalStake] = []
        self.contributor_scores: defaultdict[str, float] = defaultdict(float)
        self.treasury_balance = 0.0
        self._receipt_index = 0

    def debit_agent(
        self,
        agent: AntAgent,
        amount: float,
        *,
        payee_id: str,
        payment_type: str,
        resource_id: str,
        description: str,
        metadata: dict | None = None,
    ) -> bool:
        amount = round(max(amount, 0.0), 4)
        if amount <= 0.0 or agent.bankroll + 1e-9 < amount:
            return False
        agent.bankroll = round(agent.bankroll - amount, 4)
        receipt_id = self._next_receipt_id(payment_type)
        self.payment_receipts.append(
            PaymentReceipt(
                receipt_id=receipt_id,
                round_id=self.round_id,
                payer_id=agent.agent_id,
                payee_id=payee_id,
                amount=amount,
                payment_type=payment_type,
                resource_id=resource_id,
                description=description,
                metadata=dict(metadata or {}),
            )
        )
        self.balance_updates.append(
            BalanceUpdate(
                round_id=self.round_id,
                agent_id=agent.agent_id,
                delta=round(-amount, 4),
                balance=round(agent.bankroll, 4),
                reason=payment_type,
                related_id=receipt_id,
            )
        )
        return True

    def credit_agent(self, agent: AntAgent, amount: float, *, reason: str, related_id: str = "") -> None:
        amount = round(max(amount, 0.0), 4)
        if amount <= 0.0:
            return
        agent.bankroll = round(agent.bankroll + amount, 4)
        self.balance_updates.append(
            BalanceUpdate(
                round_id=self.round_id,
                agent_id=agent.agent_id,
                delta=amount,
                balance=round(agent.bankroll, 4),
                reason=reason,
                related_id=related_id,
            )
        )

    def credit_treasury(self, amount: float) -> None:
        self.treasury_balance = round(self.treasury_balance + max(amount, 0.0), 4)

    def record_contributor(self, agent_id: str, score: float) -> None:
        if agent_id:
            self.contributor_scores[agent_id] += max(score, 0.0)

    def _next_receipt_id(self, kind: str) -> str:
        self._receipt_index += 1
        return f"pay:{self.round_id}:{kind}:{self._receipt_index:05d}"


def market_spec_for_match(match: MatchContext) -> MarketSpec:
    stage = f"{match.stage_name} {match.group_name}".lower()
    knockout_markers = ("round of", "knockout", "quarter", "semi", "final", "third place")
    is_knockout = any(marker in stage for marker in knockout_markers) and "group" not in stage
    market_type = "binary_qualification" if is_knockout else "three_way"
    outcomes = (
        ["home_qualifies", "away_qualifies"]
        if market_type == "binary_qualification"
        else ["home_win", "draw", "away_win"]
    )
    result_side = result_side_for_match(match, market_type=market_type)
    return MarketSpec(
        round_id=match.round_id,
        market_type=market_type,
        outcomes=outcomes,
        result_side=result_side,
        settlement_status="settled" if result_side != "pass" else "pending",
    )


def result_side_for_match(match: MatchContext, *, market_type: str) -> Side:
    score = str(match.score or "").strip()
    if not score:
        return "pass"
    numbers = [int(value) for value in re.findall(r"\d+", score)]
    if len(numbers) < 2:
        return "pass"
    home_goals, away_goals = numbers[0], numbers[1]
    if home_goals > away_goals:
        return "home"
    if away_goals > home_goals:
        return "away"
    if market_type == "three_way":
        return "draw"
    return "pass"


def build_paid_knowledge_views(
    match: MatchContext,
    agents: Iterable[AntAgent],
    ledger: EconomyLedger,
) -> dict[str, KnowledgeView]:
    findings = list(match.findings)
    public_findings = [finding for finding in findings if finding.access_level == "public"]
    paid_findings = [
        finding for finding in findings
        if finding.access_level in {"shared", "private"}
    ]
    paid_findings.sort(key=lambda item: (_finding_price(item), -item.confidence, item.finding_id))

    views: dict[str, KnowledgeView] = {}
    for agent in agents:
        visible = list(public_findings)
        spent = 0.0
        budget = min(max(agent.genome.query_budget, 0.0), max(agent.bankroll, 0.0))
        for finding in paid_findings:
            price = priced_finding_for_agent(finding, agent)
            if spent + price > budget + 1e-9:
                continue
            paid = ledger.debit_agent(
                agent,
                price,
                payee_id=f"scout:{finding.scout_name}",
                payment_type="buy_data",
                resource_id=finding.finding_id,
                description=f"Bought {finding.access_level} finding from {finding.scout_name}.",
                metadata={
                    "access_level": finding.access_level,
                    "source_type": finding.source_type,
                    "base_price": _finding_price(finding),
                    "world_discount": _has_world_discount(agent),
                },
            )
            if not paid:
                continue
            spent = round(spent + price, 4)
            visible.append(finding)
        access_tier = _access_tier_for_visible_findings(visible)
        views[agent.agent_id] = KnowledgeView(
            agent_id=agent.agent_id,
            access_tier=access_tier,
            visible_findings=visible,
            market_home_probability=_source_probability(
                visible,
                source_types={"market"},
                baseline=match.market_home_probability,
            ),
            stats_home_signal=_source_probability(
                visible,
                source_types={"stats", "lineup"},
                baseline=match.stats_home_signal,
            ),
            odds_home_signal=_source_probability(
                visible,
                source_types={"odds"},
                baseline=match.odds_home_signal,
            ),
            news_home_signal=_source_probability(
                visible,
                source_types={"news", "social", "weather", "retrieval"},
                baseline=match.news_home_signal,
            ),
        )
    return views


def priced_finding_for_agent(finding: Finding, agent: AntAgent) -> float:
    price = _finding_price(finding)
    if price > 0.0 and _has_world_discount(agent):
        price *= WORLD_DISCOUNT
    return round(max(price, 0.0001 if price > 0 else 0.0), 4)


def settle_room_payments(
    *,
    rooms: list[DebateRoom],
    agents: list[AntAgent],
    ledger: EconomyLedger,
) -> None:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    for room in rooms:
        representatives = [agents_by_id[agent_id] for agent_id in room.representative_ids if agent_id in agents_by_id]
        if not representatives:
            continue
        buyer_ids = _summary_buyers(room, agents_by_id)
        room_pool = 0.0
        for buyer_id in buyer_ids:
            buyer = agents_by_id[buyer_id]
            paid = ledger.debit_agent(
                buyer,
                ROOM_SUMMARY_FEE,
                payee_id=f"room:{room.room_id}",
                payment_type="request_summary",
                resource_id=room.room_id,
                description=f"Requested room summary for {room.evidence_focus}.",
                metadata={"representatives": room.representative_ids},
            )
            if paid:
                room_pool = round(room_pool + ROOM_SUMMARY_FEE, 4)
        if room_pool <= 0.0:
            continue
        grounded_auditors = _grounded_auditors(room, agents_by_id)
        rep_pool = room_pool * (0.7 if grounded_auditors else 1.0)
        audit_pool = room_pool - rep_pool
        _credit_many(ledger, representatives, rep_pool, reason="room_summary_reward", related_id=room.room_id)
        for representative in representatives:
            ledger.record_contributor(representative.agent_id, 1.0)
        if grounded_auditors:
            _credit_many(ledger, grounded_auditors, audit_pool, reason="request_audit_reward", related_id=room.room_id)
            for auditor in grounded_auditors:
                ledger.record_contributor(auditor.agent_id, 1.35)


def debit_internal_stakes(
    *,
    agents: list[AntAgent],
    forecasts: list[Forecast],
    ledger: EconomyLedger,
) -> list[Forecast]:
    agents_by_id = {agent.agent_id: agent for agent in agents}
    updated: list[Forecast] = []
    for forecast in forecasts:
        agent = agents_by_id.get(forecast.agent_id)
        if agent is None or forecast.side == "pass":
            updated.append(forecast)
            continue
        amount = round(min(max(forecast.stake, 0.0), max(agent.bankroll, 0.0)), 4)
        if amount <= 0.0:
            updated.append(replace(forecast, stake=0.0, side="pass", decision_reason="Insufficient balance to stake."))
            continue
        receipt_id = f"stake:{ledger.round_id}:{forecast.agent_id}"
        agent.bankroll = round(agent.bankroll - amount, 4)
        ledger.balance_updates.append(
            BalanceUpdate(
                round_id=ledger.round_id,
                agent_id=agent.agent_id,
                delta=round(-amount, 4),
                balance=round(agent.bankroll, 4),
                reason="internal_stake",
                related_id=receipt_id,
            )
        )
        ledger.internal_stakes.append(
            InternalStake(
                round_id=ledger.round_id,
                agent_id=agent.agent_id,
                side=forecast.side,
                amount=amount,
                confidence=_forecast_confidence(forecast),
            )
        )
        updated.append(replace(forecast, stake=amount, bankroll=round(agent.bankroll + amount, 4)))
    return updated


def settle_internal_pool(
    *,
    market_spec: MarketSpec,
    agents: list[AntAgent],
    ledger: EconomyLedger,
) -> dict:
    if market_spec.result_side == "pass":
        return {
            "round_id": market_spec.round_id,
            "status": "pending",
            "market_type": market_spec.market_type,
            "result_side": "pass",
            "staked_total": round(sum(stake.amount for stake in ledger.internal_stakes), 4),
            "treasury_balance": ledger.treasury_balance,
            "payouts": [],
        }

    agents_by_id = {agent.agent_id: agent for agent in agents}
    stakes = ledger.internal_stakes
    correct = [stake for stake in stakes if stake.side == market_spec.result_side]
    losing = [stake for stake in stakes if stake.side != market_spec.result_side]
    correct_stake_total = round(sum(stake.amount for stake in correct), 4)
    losing_pool = round(sum(stake.amount for stake in losing), 4)
    correct_reward_pool = round(losing_pool * 0.8, 4) if correct else 0.0
    contributor_pool = round(losing_pool * 0.1, 4) if ledger.contributor_scores else 0.0
    treasury_fee = round(losing_pool - correct_reward_pool - contributor_pool, 4)
    payouts: list[dict] = []

    correct_weight = sum(stake.amount * stake.confidence for stake in correct)
    for stake in correct:
        agent = agents_by_id.get(stake.agent_id)
        if agent is None:
            continue
        share = (stake.amount * stake.confidence / correct_weight) if correct_weight > 0 else 0.0
        payout = round(stake.amount + correct_reward_pool * share, 4)
        ledger.credit_agent(agent, payout, reason="settlement_correct_forecast", related_id=market_spec.round_id)
        payouts.append({"agent_id": agent.agent_id, "type": "correct_forecast", "amount": payout})

    contributor_total = sum(ledger.contributor_scores.values())
    if contributor_pool > 0 and contributor_total > 0:
        for agent_id, score in sorted(ledger.contributor_scores.items()):
            agent = agents_by_id.get(agent_id)
            if agent is None:
                continue
            payout = round(contributor_pool * (score / contributor_total), 4)
            ledger.credit_agent(agent, payout, reason="settlement_contribution", related_id=market_spec.round_id)
            payouts.append({"agent_id": agent.agent_id, "type": "contribution", "amount": payout})
    ledger.credit_treasury(treasury_fee)
    ledger.internal_stakes = [
        replace(stake, status="settled", result_side=market_spec.result_side)
        for stake in ledger.internal_stakes
    ]
    return {
        "round_id": market_spec.round_id,
        "status": "settled",
        "market_type": market_spec.market_type,
        "result_side": market_spec.result_side,
        "staked_total": round(correct_stake_total + losing_pool, 4),
        "correct_stake_total": correct_stake_total,
        "losing_pool": losing_pool,
        "correct_reward_pool": correct_reward_pool,
        "contributor_pool": contributor_pool,
        "treasury_fee": treasury_fee,
        "treasury_balance": ledger.treasury_balance,
        "payouts": payouts,
    }


def _finding_price(finding: Finding) -> float:
    if finding.access_level == "private":
        return PRIVATE_FINDING_PRICE
    if finding.access_level == "shared":
        return SHARED_FINDING_PRICE
    return 0.0


def _has_world_discount(agent: AntAgent) -> bool:
    return bool(agent.world_verified or agent.verified_lineage)


def _access_tier_for_visible_findings(findings: list[Finding]) -> str:
    levels = {finding.access_level for finding in findings}
    if "private" in levels:
        return "private"
    if "shared" in levels:
        return "shared"
    return "public"


def _source_probability(findings: list[Finding], *, source_types: set[str], baseline: float) -> float:
    weighted_total = 0.0
    weight = 0.0
    for finding in findings:
        if finding.source_type not in source_types or finding.home_probability is None:
            continue
        confidence = max(finding.confidence, 0.01)
        weighted_total += finding.home_probability * confidence
        weight += confidence
    if weight <= 0.0:
        return baseline
    return round(weighted_total / weight, 4)


def _summary_buyers(room: DebateRoom, agents_by_id: dict[str, AntAgent]) -> list[str]:
    reps = set(room.representative_ids)
    candidates = [
        agents_by_id[agent_id]
        for agent_id in room.participant_ids
        if agent_id in agents_by_id and agent_id not in reps
    ]
    candidates.sort(
        key=lambda agent: (
            agent.genome.query_budget,
            agent.bankroll,
            agent.accuracy,
        ),
        reverse=True,
    )
    return [agent.agent_id for agent in candidates[: min(3, len(candidates))]]


def _grounded_auditors(room: DebateRoom, agents_by_id: dict[str, AntAgent]) -> list[AntAgent]:
    auditors: list[AntAgent] = []
    seen: set[str] = set()
    for claim in room.claims:
        if claim.debate_role not in {"challenger", "source_auditor", "skeptic"}:
            continue
        if not claim.dispute or not claim.referenced_evidence:
            continue
        agent = agents_by_id.get(claim.speaker_id)
        if agent is None or agent.agent_id in seen:
            continue
        auditors.append(agent)
        seen.add(agent.agent_id)
    return auditors


def _credit_many(
    ledger: EconomyLedger,
    agents: list[AntAgent],
    amount: float,
    *,
    reason: str,
    related_id: str,
) -> None:
    if amount <= 0.0 or not agents:
        return
    share = round(amount / len(agents), 4)
    for agent in agents:
        ledger.credit_agent(agent, share, reason=reason, related_id=related_id)


def _forecast_confidence(forecast: Forecast) -> float:
    return round(min(0.95, 0.35 + min(abs(forecast.edge) / 0.08, 1.0) * 0.5), 4)
