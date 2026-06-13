"""Colony harness orchestration."""

from __future__ import annotations

import json
import random
from pathlib import Path

from .agent import AntAgent
from .debate import DebateFeed
from .genes import random_genome
from .knowledge import build_knowledge_views
from .models import MatchContext, RoundResult
from .voice import TemplateVoiceModel, VoiceModel
from .world_graph import build_world_graph


class ColonyHarness:
    def __init__(
        self,
        population_size: int = 40,
        speaker_slots: int = 6,
        seed: int = 42,
        starting_bankroll: float = 100.0,
        voice_model: VoiceModel | None = None,
    ) -> None:
        if population_size < 1:
            raise ValueError("population_size must be positive")
        if speaker_slots < 1:
            raise ValueError("speaker_slots must be positive")

        self.population_size = population_size
        self.speaker_slots = min(speaker_slots, population_size)
        self.seed = seed
        self.rng = random.Random(seed)
        self.starting_bankroll = starting_bankroll
        self.voice_model = voice_model or TemplateVoiceModel()
        self.agents = self._spawn_agents()

    def _spawn_agents(self) -> list[AntAgent]:
        agents: list[AntAgent] = []
        for index in range(self.population_size):
            genome = random_genome(self.rng)
            agent = AntAgent(
                agent_id=f"ant_{index:04d}",
                name=f"ant-{index:04d}",
                generation=0,
                genome=genome,
                bankroll=round(self.starting_bankroll * self.rng.uniform(0.92, 1.08), 4),
                accuracy=round(self.rng.uniform(0.35, 0.65), 4),
            )
            agents.append(agent)
        return agents

    def select_debaters(self) -> list[tuple[AntAgent, str]]:
        ranked = sorted(
            self.agents,
            key=lambda ant: (ant.bankroll * 0.7) + (ant.accuracy * 100.0 * 0.3),
            reverse=True,
        )
        elite_count = max(1, self.speaker_slots // 2)
        elite = ranked[:elite_count]
        remaining = [agent for agent in self.agents if agent not in elite]
        wildcards = self.rng.sample(remaining, k=self.speaker_slots - elite_count)
        selected: list[tuple[AntAgent, str]] = []
        for rank, agent in enumerate(elite, start=1):
            score = (agent.bankroll * 0.7) + (agent.accuracy * 100.0 * 0.3)
            selected.append((agent, f"elite rank {rank}: bankroll/accuracy score {score:.2f}"))
        for agent in wildcards:
            selected.append((agent, "wildcard: exploration slot for diversity and noisy debate"))
        return selected

    def select_speakers(self) -> list[AntAgent]:
        return [agent for agent, _reason in self.select_debaters()]

    def run_round(self, match: MatchContext) -> RoundResult:
        feed = DebateFeed()
        knowledge_views_by_agent = build_knowledge_views(match, self.agents)

        for speaker, selection_reason in self.select_debaters():
            view = knowledge_views_by_agent[speaker.agent_id]
            visible_match = view.to_match_context(match)
            feed.append(
                speaker.speak(
                    visible_match,
                    self.rng,
                    self.voice_model,
                    selection_reason,
                    view.access_tier,
                    len(view.visible_findings),
                )
            )

        debate_signal = feed.consensus_home_probability()
        forecasts = []
        for agent in self.agents:
            view = knowledge_views_by_agent[agent.agent_id]
            visible_match = view.to_match_context(match)
            forecasts.append(
                agent.forecast(
                    visible_match,
                    debate_signal,
                    view.access_tier,
                    len(view.visible_findings),
                )
            )
        commitments = [
            agent.commit_bet(forecast, match.round_id)
            for agent, forecast in zip(self.agents, forecasts, strict=True)
        ]

        home_bets = sum(1 for forecast in forecasts if forecast.side == "home")
        away_bets = sum(1 for forecast in forecasts if forecast.side == "away")
        passes = sum(1 for forecast in forecasts if forecast.side == "pass")
        total_staked = round(sum(forecast.stake for forecast in forecasts), 4)

        summary = {
            "population": self.population_size,
            "speaker_slots": self.speaker_slots,
            "debate_home_probability": None if debate_signal is None else round(debate_signal, 4),
            "market_home_probability": match.market_home_probability,
            "findings": len(match.findings),
            "public_findings": sum(1 for finding in match.findings if finding.access_level == "public"),
            "shared_findings": sum(1 for finding in match.findings if finding.access_level == "shared"),
            "private_findings": sum(1 for finding in match.findings if finding.access_level == "private"),
            "public_views": sum(1 for view in knowledge_views_by_agent.values() if view.access_tier == "public"),
            "shared_views": sum(1 for view in knowledge_views_by_agent.values() if view.access_tier == "shared"),
            "private_views": sum(1 for view in knowledge_views_by_agent.values() if view.access_tier == "private"),
            "home_bets": home_bets,
            "away_bets": away_bets,
            "passes": passes,
            "total_staked": total_staked,
        }
        world_graph = build_world_graph(match, claims=feed.claims, forecasts=forecasts)

        return RoundResult(
            round_id=match.round_id,
            claims=feed.claims,
            forecasts=forecasts,
            commitments=commitments,
            findings=match.findings,
            knowledge_views=list(knowledge_views_by_agent.values()),
            world_graph=world_graph,
            summary=summary,
        )

    def write_jsonl(self, result: RoundResult, output_path: str | Path) -> None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        events = []
        events.append({"event_type": "round_summary", **result.summary})
        events.extend({"event_type": "finding", **finding.to_dict()} for finding in result.findings)
        events.extend({"event_type": "knowledge_view", **view.to_dict()} for view in result.knowledge_views)
        events.append({"event_type": "world_graph", **result.world_graph.to_dict()})
        events.extend({"event_type": "debate_claim", **claim.to_dict()} for claim in result.claims)
        events.extend({"event_type": "forecast", **forecast.to_dict()} for forecast in result.forecasts)
        events.extend({"event_type": "bet_commitment", **commitment.to_dict()} for commitment in result.commitments)

        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def public_roster(self) -> list[dict]:
        return [agent.public_record for agent in self.agents]
