"""Colony harness orchestration."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from .agent import AntAgent
from .debate import DebateFeed
from .genes import random_genome
from .knowledge import build_knowledge_views
from .models import DebateClaim, DebateRoom, KnowledgeView, MatchContext, RoundResult
from .voice import TemplateVoiceModel, VoiceModel
from .world_graph import build_world_graph


@dataclass(frozen=True)
class DebateProfile:
    agent: AntAgent
    view: KnowledgeView
    match: MatchContext
    probability: float
    stance: str
    evidence_focus: str
    score: float


@dataclass(frozen=True)
class ConversationVenue:
    room_id: str
    topic: str
    description: str
    stance: str = "topic_room"


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
        knowledge_views_by_agent = build_knowledge_views(match, self.agents)
        profiles = self._build_debate_profiles(match, knowledge_views_by_agent)
        self._last_profiles = profiles
        rooms = self._run_room_debates(profiles)
        feed = self._run_final_chamber(rooms)

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
            "room_count": len(rooms),
            "room_claims": sum(len(room.claims) for room in rooms),
            "final_claims": len(feed.claims),
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
        all_debate_claims = [claim for room in rooms for claim in room.claims] + feed.claims
        world_graph = build_world_graph(match, claims=all_debate_claims, forecasts=forecasts)

        return RoundResult(
            round_id=match.round_id,
            claims=feed.claims,
            rooms=rooms,
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
        # Emit the roster up front so a replay consumer can bind agent_id -> index
        # before any debate_claim/forecast/bet_commitment references an agent.
        events.extend(
            {"event_type": "agent_record", **record} for record in self.public_roster()
        )
        events.extend({"event_type": "finding", **finding.to_dict()} for finding in result.findings)
        events.extend({"event_type": "knowledge_view", **view.to_dict()} for view in result.knowledge_views)
        events.extend({"event_type": "debate_room", **room.to_dict()} for room in result.rooms)
        events.append({"event_type": "world_graph", **result.world_graph.to_dict()})
        events.extend({"event_type": "debate_claim", **claim.to_dict()} for claim in result.claims)
        events.extend({"event_type": "forecast", **forecast.to_dict()} for forecast in result.forecasts)
        events.extend({"event_type": "bet_commitment", **commitment.to_dict()} for commitment in result.commitments)

        with path.open("w", encoding="utf-8") as handle:
            for event in events:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    def public_roster(self) -> list[dict]:
        return [agent.public_record for agent in self.agents]

    def _build_debate_profiles(
        self,
        match: MatchContext,
        knowledge_views_by_agent: dict[str, KnowledgeView],
    ) -> list[DebateProfile]:
        profiles: list[DebateProfile] = []
        for agent in self.agents:
            view = knowledge_views_by_agent[agent.agent_id]
            visible_match = view.to_match_context(match)
            probability = agent.private_baseline_probability(visible_match)
            profiles.append(
                DebateProfile(
                    agent=agent,
                    view=view,
                    match=visible_match,
                    probability=probability,
                    stance=_stance_for_probability(probability, visible_match.market_home_probability),
                    evidence_focus=_evidence_focus(visible_match),
                    score=_debate_score(agent),
                )
            )
        return profiles

    def _run_room_debates(self, profiles: list[DebateProfile]) -> list[DebateRoom]:
        rooms: list[DebateRoom] = []
        carried_claims_by_agent: dict[str, list[DebateClaim]] = {}
        speaking_visits_by_agent: dict[str, int] = {}
        venues = _conversation_venues(profiles, max_rooms=self._target_room_count())
        for venue in venues:
            room_profiles = _select_venue_participants(profiles, venue)
            representatives = _select_venue_speakers(room_profiles, venue, speaking_visits_by_agent)
            roles = _roles_for_representatives(len(representatives))
            room_claims: list[DebateClaim] = []
            for representative, role in zip(representatives, roles, strict=True):
                carried_claims = carried_claims_by_agent.get(representative.agent.agent_id, [])[-2:]
                prior_claims = carried_claims + room_claims
                prior_rooms = sorted({claim.room_id for claim in carried_claims if claim.room_id})
                room_claims.append(
                    representative.agent.speak(
                        representative.match,
                        self.rng,
                        self.voice_model,
                        selection_reason=(
                            f"{role} in {venue.room_id}: topic={venue.topic}, "
                            f"participants={len(room_profiles)}, "
                            f"carried_from={','.join(prior_rooms) if prior_rooms else 'none'}"
                        ),
                        access_tier=representative.view.access_tier,
                        visible_findings=len(representative.view.visible_findings),
                        prior_claims=prior_claims,
                        debate_phase="room",
                        room_id=venue.room_id,
                        debate_role=role,
                        debate_focus=venue.topic,
                    )
                )
                claim = room_claims[-1]
                carried_claims_by_agent.setdefault(representative.agent.agent_id, []).append(claim)
                speaking_visits_by_agent[representative.agent.agent_id] = (
                    speaking_visits_by_agent.get(representative.agent.agent_id, 0) + 1
                )

            synthesis_probability = _weighted_claim_probability(room_claims)
            synthesis_confidence = _average_confidence(room_claims)
            rooms.append(
                DebateRoom(
                    room_id=venue.room_id,
                    stance=venue.stance,
                    evidence_focus=venue.topic,
                    participant_ids=[profile.agent.agent_id for profile in room_profiles],
                    representative_ids=[profile.agent.agent_id for profile in representatives],
                    claims=room_claims,
                    synthesis_home_probability=None if synthesis_probability is None else round(synthesis_probability, 4),
                    synthesis_confidence=round(synthesis_confidence, 4),
                    synthesis=_room_synthesis(
                        room_id=venue.room_id,
                        stance=venue.stance,
                        evidence_focus=venue.topic,
                        participants=len(room_profiles),
                        claims=room_claims,
                    ),
                )
            )
        return rooms

    def _run_final_chamber(self, rooms: list[DebateRoom]) -> DebateFeed:
        final_feed = DebateFeed()
        room_claims = [claim for room in rooms for claim in room.claims]
        final_representatives = _select_final_representatives(rooms, self.speaker_slots)
        for room, representative_id in final_representatives:
            profile = self._profile_by_agent_id(representative_id)
            if profile is None:
                continue
            final_feed.append(
                profile.agent.speak(
                    profile.match,
                    self.rng,
                    self.voice_model,
                    selection_reason=(
                        f"final chamber representative for {room.room_id}: "
                        f"{room.stance}, focus={room.evidence_focus}, room_p={_format_probability(room.synthesis_home_probability)}"
                    ),
                    access_tier=profile.view.access_tier,
                    visible_findings=len(profile.view.visible_findings),
                    prior_claims=room_claims + final_feed.claims,
                    debate_phase="final",
                    room_id=room.room_id,
                    debate_role="room_representative",
                    debate_focus=room.evidence_focus,
                )
            )
        return final_feed

    def _profile_by_agent_id(self, agent_id: str) -> DebateProfile | None:
        for profile in getattr(self, "_last_profiles", []):
            if profile.agent.agent_id == agent_id:
                return profile
        return None

    def _target_room_count(self) -> int:
        return max(1, min(self.speaker_slots, max(1, (self.population_size + 7) // 8)))


def _debate_score(agent: AntAgent) -> float:
    return (agent.bankroll * 0.7) + (agent.accuracy * 100.0 * 0.3)


def _stance_for_probability(probability: float, market_probability: float) -> str:
    edge = probability - market_probability
    if edge >= 0.01:
        return "support_home"
    if edge <= -0.01:
        return "support_away"
    return "uncertainty"


def _evidence_focus(match: MatchContext) -> str:
    scored: list[tuple[float, str]] = []
    for finding in match.findings:
        for evidence in finding.evidence_claims:
            subject = str(evidence.get("subject") or evidence.get("team") or finding.source_type or "general")
            confidence = float(evidence.get("confidence") or finding.confidence or 0.35)
            if evidence.get("player"):
                confidence += 0.25
            if evidence.get("claim_type") == "injury_availability":
                confidence += 0.2
            scored.append((confidence, _clean_focus(subject)))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    source_scores = {
        "stats": match.stats_home_signal,
        "odds": match.odds_home_signal,
        "news": match.news_home_signal,
    }
    return max(source_scores, key=source_scores.get)


def _clean_focus(value: str) -> str:
    cleaned = " ".join(value.lower().replace("_", " ").split())
    return cleaned[:40] or "general"


def _conversation_venues(profiles: list[DebateProfile], *, max_rooms: int) -> list[ConversationVenue]:
    evidence_text = " ".join(_visible_evidence_text(profile.match) for profile in profiles[: min(len(profiles), 12)])
    candidates: list[tuple[str, str]] = []
    if "neymar" in evidence_text:
        candidates.append(("neymar_availability", "How much does Neymar availability move Brazil?"))
    if any(token in evidence_text for token in ("nayef aguerd", "ez abde", "morocco")):
        candidates.append(("morocco_availability", "Do Morocco injuries offset the Neymar drag?"))
    if "recent_form" in evidence_text or "recent form" in evidence_text or "last matches" in evidence_text:
        candidates.append(("team_form", "What do recent matches say about each team's baseline?"))
    if "player_form" in evidence_text or "season form" in evidence_text or "goals" in evidence_text:
        candidates.append(("player_form", "Which key players are in form strongly enough to move price?"))
    candidates.extend(
        [
            ("market_pricing", "Has the market already priced the injury news?"),
            ("source_audit", "Which sources are reliable enough to move price?"),
            ("stats_form", "Do baseline stats overpower noisy news?"),
            ("uncertainty", "Should the room widen uncertainty instead of taking a side?"),
        ]
    )
    venues = []
    for index, (topic, description) in enumerate(candidates[:max_rooms], start=1):
        venues.append(
            ConversationVenue(
                room_id=f"room-{index:02d}",
                topic=topic,
                description=description,
            )
        )
    return venues


def _visible_evidence_text(match: MatchContext) -> str:
    parts: list[str] = []
    for finding in match.findings:
        parts.append(finding.summary)
        for evidence in finding.evidence_claims:
            parts.append(str(evidence.get("claim_type") or ""))
            parts.append(str(evidence.get("subject") or ""))
            parts.append(str(evidence.get("team") or ""))
            parts.append(str(evidence.get("player") or ""))
            parts.append(str(evidence.get("claim") or ""))
    return " ".join(parts).lower()


def _select_venue_participants(profiles: list[DebateProfile], venue: ConversationVenue) -> list[DebateProfile]:
    target_size = max(6, min(len(profiles), max(10, len(profiles) // 3)))
    scored = sorted(
        ((_venue_affinity(profile, venue), profile) for profile in profiles),
        key=lambda item: (item[0], item[1].score),
        reverse=True,
    )
    participants = [profile for score, profile in scored if score >= 0.35][:target_size]
    if len(participants) < min(4, len(profiles)):
        participants = [profile for _score, profile in scored[: min(target_size, len(profiles))]]
    participants.sort(key=lambda profile: (_venue_affinity(profile, venue), profile.score), reverse=True)
    return participants


def _venue_affinity(profile: DebateProfile, venue: ConversationVenue) -> float:
    weights = profile.agent.genome.source_weights.normalized()
    text = _visible_evidence_text(profile.match)
    score = 0.15 + (profile.score / 400.0)
    if venue.topic == "neymar_availability":
        score += 0.75 if "neymar" in text else 0.0
        score += weights.news * 0.8
        score += weights.debate * 0.25
    elif venue.topic == "morocco_availability":
        score += 0.55 if any(token in text for token in ("nayef aguerd", "ez abde", "morocco")) else 0.0
        score += weights.news * 0.55
        score += weights.stats * 0.2
    elif venue.topic == "market_pricing":
        score += weights.odds * 1.0
        score += 0.25 if profile.agent.genome.herd_bias < -0.2 else 0.0
    elif venue.topic == "team_form":
        score += weights.stats * 0.9
        score += 0.45 if "recent_form" in text or "last matches" in text else 0.0
    elif venue.topic == "player_form":
        score += weights.stats * 0.55
        score += weights.news * 0.35
        score += 0.45 if "player_form" in text or "season form" in text or "goals" in text else 0.0
    elif venue.topic == "source_audit":
        score += weights.news * 0.4
        score += min(profile.agent.genome.query_budget / 2.0, 1.0) * 0.45
        score += 0.2 if profile.view.access_tier in {"shared", "private"} else 0.0
    elif venue.topic == "stats_form":
        score += weights.stats * 1.0
        score += 0.2 if profile.probability > profile.match.market_home_probability else 0.0
    elif venue.topic == "uncertainty":
        edge = abs(profile.probability - profile.match.market_home_probability)
        score += max(0.0, 0.45 - edge * 8.0)
        score += 0.2 if "skeptic" in profile.agent.genome.persona else 0.0
    return score


def _select_venue_speakers(
    room_profiles: list[DebateProfile],
    venue: ConversationVenue,
    speaking_visits_by_agent: dict[str, int],
) -> list[DebateProfile]:
    if len(room_profiles) <= 3:
        return room_profiles
    ranked = sorted(
        room_profiles,
        key=lambda profile: (
            _venue_affinity(profile, venue) + min(speaking_visits_by_agent.get(profile.agent.agent_id, 0), 2) * 0.12,
            profile.score,
        ),
        reverse=True,
    )
    speakers = [ranked[0]]
    bridge_candidates = [
        profile
        for profile in ranked[1:]
        if speaking_visits_by_agent.get(profile.agent.agent_id, 0) > 0 and profile not in speakers
    ]
    if bridge_candidates:
        speakers.append(bridge_candidates[0])
    contrast_candidates = [
        profile
        for profile in ranked[1:]
        if profile.stance != speakers[0].stance and profile not in speakers
    ]
    if contrast_candidates:
        speakers.append(contrast_candidates[0])
    for profile in ranked[1:]:
        if len(speakers) >= 3:
            break
        if profile not in speakers:
            speakers.append(profile)
    return speakers


def _select_final_representatives(rooms: list[DebateRoom], speaker_slots: int) -> list[tuple[DebateRoom, str]]:
    selected: list[tuple[DebateRoom, str]] = []
    used_agents: set[str] = set()
    for room in rooms:
        chosen = ""
        for agent_id in room.representative_ids:
            if agent_id not in used_agents:
                chosen = agent_id
                break
        if not chosen and room.representative_ids:
            chosen = room.representative_ids[0]
        if not chosen:
            continue
        selected.append((room, chosen))
        used_agents.add(chosen)
        if len(selected) >= speaker_slots:
            break
    return selected


def _cluster_profiles(profiles: list[DebateProfile], *, max_rooms: int) -> list[list[DebateProfile]]:
    buckets: dict[tuple[str, str], list[DebateProfile]] = {}
    for profile in profiles:
        buckets.setdefault((profile.stance, profile.evidence_focus), []).append(profile)

    ordered_buckets = sorted(
        buckets.values(),
        key=lambda bucket: (len(bucket), max(profile.score for profile in bucket)),
        reverse=True,
    )
    rooms: list[list[DebateProfile]] = [list(bucket) for bucket in ordered_buckets[:max_rooms]]
    if not rooms:
        return []

    for bucket in ordered_buckets[max_rooms:]:
        target = _best_merge_room(rooms, bucket[0])
        target.extend(bucket)

    while len(rooms) < max_rooms:
        largest = max(rooms, key=len)
        if len(largest) < 6:
            break
        split_at = len(largest) // 2
        rooms.append(largest[split_at:])
        del largest[split_at:]

    for room in rooms:
        room.sort(key=lambda profile: profile.score, reverse=True)
    return rooms


def _best_merge_room(rooms: list[list[DebateProfile]], profile: DebateProfile) -> list[DebateProfile]:
    same_stance = [room for room in rooms if room and room[0].stance == profile.stance]
    candidates = same_stance or rooms
    return min(candidates, key=len)


def _select_room_representatives(room_profiles: list[DebateProfile]) -> list[DebateProfile]:
    if len(room_profiles) <= 2:
        return room_profiles
    representatives = [room_profiles[0]]
    different_stance = [profile for profile in room_profiles[1:] if profile.stance != room_profiles[0].stance]
    if different_stance:
        representatives.append(different_stance[0])
    different_focus = [
        profile
        for profile in room_profiles[1:]
        if profile.evidence_focus != room_profiles[0].evidence_focus and profile not in representatives
    ]
    if different_focus:
        representatives.append(different_focus[0])
    for profile in room_profiles[1:]:
        if len(representatives) >= 3:
            break
        if profile not in representatives:
            representatives.append(profile)
    return representatives


def _roles_for_representatives(count: int) -> list[str]:
    roles = ["advocate", "challenger", "source_auditor"]
    if count > len(roles):
        roles.extend(["skeptic"] * (count - len(roles)))
    return roles[:count]


def _dominant_label(labels: object) -> str:
    counts: dict[str, int] = {}
    for label in labels:
        text = str(label)
        counts[text] = counts.get(text, 0) + 1
    if not counts:
        return "general"
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def _weighted_claim_probability(claims: list[DebateClaim]) -> float | None:
    if not claims:
        return None
    weighted_sum = 0.0
    total_weight = 0.0
    for claim in claims:
        weight = max(claim.confidence, 0.05)
        weighted_sum += claim.stated_home_probability * weight
        total_weight += weight
    return weighted_sum / max(total_weight, 1e-9)


def _average_confidence(claims: list[DebateClaim]) -> float:
    if not claims:
        return 0.0
    return sum(claim.confidence for claim in claims) / len(claims)


def _room_synthesis(
    *,
    room_id: str,
    stance: str,
    evidence_focus: str,
    participants: int,
    claims: list[DebateClaim],
) -> str:
    probability = _weighted_claim_probability(claims)
    top_subjects = []
    for claim in claims:
        for evidence in claim.referenced_evidence[:2]:
            subject = evidence.get("subject") or evidence.get("team")
            if subject and subject not in top_subjects:
                top_subjects.append(str(subject))
    subjects = ", ".join(top_subjects[:3]) if top_subjects else evidence_focus
    return (
        f"{room_id} grouped {participants} predictors around {stance}/{evidence_focus}. "
        f"Room synthesis prices home at {_format_probability(probability)} with evidence focus on {subjects}."
    )


def _format_probability(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1%}"
