"""MiroFish-style social action feed derived from grounded debate rooms."""

from __future__ import annotations

import random

from .models import DebateClaim, DebateRoom, Forecast, MatchContext, SocialAction

ACTIVITY_RATE = {
    "quiet": 0.22,
    "regular": 0.42,
    "active": 0.68,
    "very_active": 0.88,
}

INFLUENCE_BONUS = {
    "low": 0.0,
    "medium": 0.12,
    "high": 0.24,
}


def forecast_side_for_probability(home_probability: float) -> str:
    if abs(home_probability - 0.5) < 0.006:
        return "draw"
    return "home" if home_probability > 0.5 else "away"


def build_social_actions(
    *,
    match: MatchContext,
    rooms: list[DebateRoom],
    final_claims: list[DebateClaim],
    forecasts_by_agent: dict[str, Forecast] | None = None,
    rng: random.Random | None = None,
) -> list[SocialAction]:
    random_source = rng or random.Random(0)
    forecasts = forecasts_by_agent or {}
    actions: list[SocialAction] = []
    claim_to_action: dict[tuple[str, str, str], str] = {}
    for room_index, room in enumerate(rooms, start=1):
        previous_action_id = ""
        previous_actor_id = ""
        for index, claim in enumerate(room.claims):
            action_id = f"social:{claim.round_id}:{room.room_id}:{index + 1:02d}:{claim.speaker_id}"
            action_type = _action_type_for_claim(claim, is_first=index == 0)
            action = SocialAction(
                action_id=action_id,
                round_id=claim.round_id,
                room_id=room.room_id,
                phase="room",
                action_type=action_type,
                actor_id=claim.speaker_id,
                actor_name=claim.speaker_name,
                role=claim.debate_role or "speaker",
                stance=_stance_label(claim.direction),
                target_action_id=_target_action_id(claim, claim_to_action) or previous_action_id,
                target_actor_id=claim.dispute.get("target_speaker_id") or previous_actor_id,
                topic=room.evidence_focus,
                text=_social_text(claim, match=match),
                grounded_elements=_grounded_elements(claim),
                tags=_tags(claim, room),
                weight=_social_weight(claim),
                metadata={
                    "platform": "colony_room",
                    "simulated_hour": _simulated_hour(room_index, index),
                    "round_index": room_index,
                    "activation_reason": "representative_speaker",
                    "recommendation_score": 1.0,
                    "oasis_action": _oasis_action_name(action_type),
                },
            )
            actions.append(action)
            claim_to_action[_claim_key(claim)] = action_id
            previous_action_id = action_id
            previous_actor_id = claim.speaker_id
        actions.extend(
            _room_crowd_actions(
                match=match,
                room=room,
                room_index=room_index,
                room_actions=actions,
                forecasts_by_agent=forecasts,
                rng=random_source,
            )
        )

    for index, claim in enumerate(final_claims):
        action_id = f"social:{claim.round_id}:final:{index + 1:02d}:{claim.speaker_id}"
        actions.append(
            SocialAction(
                action_id=action_id,
                round_id=claim.round_id,
                room_id="final",
                phase="final",
                action_type="synthesis",
                actor_id=claim.speaker_id,
                actor_name=claim.speaker_name,
                role=claim.debate_role or "synthesis",
                stance=_stance_label(claim.direction),
                target_action_id="",
                target_actor_id="",
                topic="final_synthesis",
                text=_social_text(claim, match=match),
                grounded_elements=_grounded_elements(claim),
                tags=_tags(claim, None),
                weight=_social_weight(claim),
                metadata={
                    "platform": "final_chamber",
                    "simulated_hour": _simulated_hour(len(rooms) + 1, index),
                    "round_index": len(rooms) + 1,
                    "activation_reason": "final_synthesis",
                    "recommendation_score": 1.0,
                    "oasis_action": "CREATE_POST",
                },
            )
        )
        actions.extend(
            _final_prediction_cards(
                match=match,
                claim=claim,
                forecasts_by_agent=forecasts,
                rng=random_source,
            )
        )
    return actions


def _claim_key(claim: DebateClaim) -> tuple[str, str, str]:
    return (claim.round_id, claim.room_id or "global", claim.speaker_id)


def _target_action_id(claim: DebateClaim, claim_to_action: dict[tuple[str, str, str], str]) -> str:
    target_id = claim.dispute.get("target_speaker_id") if claim.dispute else ""
    if not target_id:
        return ""
    return claim_to_action.get((claim.round_id, claim.room_id or "global", target_id), "")


def _action_type_for_claim(claim: DebateClaim, *, is_first: bool) -> str:
    if claim.dispute:
        return "challenge"
    if claim.debate_role in {"source_auditor", "skeptic"}:
        return "audit"
    if is_first or claim.debate_role == "advocate":
        return "post"
    return "reply"


def _stance_label(direction: str) -> str:
    if direction == "home":
        return "leans_home"
    if direction == "away":
        return "leans_away"
    return "neutral"


def _social_text(claim: DebateClaim, *, match: MatchContext) -> str:
    text = " ".join(claim.message.strip().split())
    if text.startswith(f"{claim.speaker_name}:"):
        text = text.split(":", 1)[1].strip()
    text = text.replace("home", match.home_team).replace("away", match.away_team)
    if claim.dispute:
        target = claim.dispute.get("target_speaker_name") or "the previous claim"
        critique = str(claim.dispute.get("critique_type") or "challenge").replace("_", " ")
        return f"Replying to {target}, {text} [{critique}]"
    return text


def _grounded_elements(claim: DebateClaim) -> list[dict]:
    elements = []
    for evidence in claim.referenced_evidence[:4]:
        subject = evidence.get("subject") or evidence.get("team") or evidence.get("player") or "match"
        source = evidence.get("source_title") or evidence.get("scout_name") or evidence.get("source_domain") or "source"
        elements.append(
            {
                "finding_id": evidence.get("finding_id", ""),
                "subject": subject,
                "claim_type": evidence.get("claim_type", "claim"),
                "claim": evidence.get("claim", ""),
                "source": source,
                "source_url": evidence.get("source_url", ""),
                "source_quality": evidence.get("source_quality", evidence.get("source_kind", "")),
            }
        )
    return elements


def _tags(claim: DebateClaim, room: DebateRoom | None) -> list[str]:
    tags = list(claim.evidence_tags)
    if room is not None:
        tags.append(room.evidence_focus)
    if claim.dispute:
        tags.append(str(claim.dispute.get("critique_type") or "challenge"))
    return sorted({tag for tag in tags if tag})


def _social_weight(claim: DebateClaim) -> float:
    base = max(claim.confidence, 0.1)
    if claim.dispute:
        base += 0.15
    if claim.debate_role == "source_auditor":
        base += 0.1
    return round(min(base, 1.0), 4)


def _simulated_hour(room_index: int, event_index: int) -> float:
    return round(18.0 + room_index * 0.45 + event_index * 0.035, 3)


def _oasis_action_name(action_type: str) -> str:
    return {
        "post": "CREATE_POST",
        "reply": "CREATE_COMMENT",
        "audit": "CREATE_COMMENT",
        "challenge": "CREATE_COMMENT",
        "comment_challenge": "CREATE_COMMENT",
        "comment_support": "CREATE_COMMENT",
        "endorse": "LIKE_POST",
        "like": "LIKE_POST",
        "quote_reply": "QUOTE_POST",
        "share": "REPOST",
        "follow": "FOLLOW",
        "view": "READ_POST",
        "watch": "READ_POST",
        "synthesis": "CREATE_POST",
        "prediction_card": "CREATE_POST",
    }.get(action_type, "CREATE_COMMENT")


def _active_room_agents(
    *,
    room: DebateRoom,
    speakers: set[str],
    forecasts_by_agent: dict[str, Forecast],
    rng: random.Random,
) -> list[str]:
    candidates = [agent_id for agent_id in room.participant_ids if agent_id not in speakers]
    if not candidates:
        return []
    scored = [
        (_activation_score(forecasts_by_agent.get(agent_id), room.evidence_focus, rng), agent_id)
        for agent_id in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    avg_activity = sum(score for score, _agent_id in scored) / max(len(scored), 1)
    target_count = int(len(scored) * min(max(avg_activity, 0.18), 0.72) * 0.65)
    target_count = min(len(scored), max(6, target_count, len(scored) // 3))
    return [agent_id for _score, agent_id in scored[:target_count]]


def _activation_score(forecast: Forecast | None, topic: str, rng: random.Random) -> float:
    if forecast is None:
        return 0.15 + rng.random() * 0.08
    base = ACTIVITY_RATE.get(forecast.activity_level, 0.35)
    influence = INFLUENCE_BONUS.get(forecast.influence_weight, 0.0)
    window_bonus = _window_bonus(forecast.active_windows, topic)
    risk_bonus = 0.1 if forecast.risk_profile == "risky" else 0.0
    delay_penalty = {"fast": 0.0, "normal": 0.04, "slow": 0.1}.get(forecast.response_delay, 0.04)
    jitter = rng.random() * 0.08
    return max(0.02, base + influence + window_bonus + risk_bonus + jitter - delay_penalty)


def _window_bonus(active_windows: str, topic: str) -> float:
    windows = {item.strip() for item in active_windows.split(",") if item.strip()}
    if topic == "market_pricing" and "market_move_window" in windows:
        return 0.18
    if topic in {"team_form", "source_audit", "stats_form"} and "pre_match" in windows:
        return 0.08
    if topic in {"source_audit", "uncertainty"} and "lineup_window" in windows:
        return 0.14
    if "late_room_replies" in windows:
        return 0.06
    return 0.0


def _room_crowd_actions(
    *,
    match: MatchContext,
    room: DebateRoom,
    room_index: int,
    room_actions: list[SocialAction],
    forecasts_by_agent: dict[str, Forecast],
    rng: random.Random,
) -> list[SocialAction]:
    if not room.claims:
        return []
    local_actions = [action for action in room_actions if action.room_id == room.room_id and action.phase == "room"]
    if not local_actions:
        return []
    speakers = {claim.speaker_id for claim in room.claims}
    listeners = _active_room_agents(
        room=room,
        speakers=speakers,
        forecasts_by_agent=forecasts_by_agent,
        rng=rng,
    )
    reactions: list[SocialAction] = []
    for index, agent_id in enumerate(listeners, start=1):
        forecast = forecasts_by_agent.get(agent_id)
        target, score = _recommended_target(local_actions, forecast, rng)
        forecast = forecasts_by_agent.get(agent_id)
        action_type = _crowd_action_type(index, forecast, target)
        reactions.append(
            SocialAction(
                action_id=f"social:{room.claims[0].round_id}:{room.room_id}:crowd:{index:02d}:{agent_id}",
                round_id=room.claims[0].round_id,
                room_id=room.room_id,
                phase="room",
                action_type=action_type,
                actor_id=agent_id,
                actor_name=agent_id.replace("_", "-"),
                role="listener",
                stance=_stance_from_forecast(forecast),
                target_action_id=target.action_id,
                target_actor_id=target.actor_id,
                topic=room.evidence_focus,
                text=_crowd_text(
                    action_type=action_type,
                    actor_id=agent_id,
                    target=target,
                    forecast=forecast,
                    match=match,
                ),
                grounded_elements=target.grounded_elements[:3],
                tags=sorted({*target.tags, action_type}),
                weight=_crowd_weight(forecast, target),
                metadata={
                    "platform": "colony_room",
                    "simulated_hour": _simulated_hour(room_index, index + len(room.claims)),
                    "round_index": room_index,
                    "activation_reason": _activation_reason(forecast),
                    "recommendation_score": score,
                    "target_hot_score": _hot_score(target, recency_index=index),
                    "oasis_action": _oasis_action_name(action_type),
                },
            )
        )
    return reactions


def _activation_reason(forecast: Forecast | None) -> str:
    if forecast is None:
        return "ambient_reader"
    parts = [forecast.activity_level, forecast.influence_weight, forecast.response_delay]
    if forecast.risk_profile == "risky":
        parts.append("risk_seeking")
    elif forecast.risk_profile == "secure":
        parts.append("risk_control")
    return "_".join(parts)


def _is_opposing_stance(forecast: Forecast, target: SocialAction) -> bool:
    return (
        (forecast.side == "home" and target.stance == "leans_away")
        or (forecast.side == "away" and target.stance == "leans_home")
        or (forecast.side == "draw" and target.stance in {"leans_home", "leans_away"})
    )


def _hot_score(action: SocialAction, *, recency_index: int) -> float:
    action_bonus = {
        "post": 0.12,
        "challenge": 0.16,
        "audit": 0.12,
        "reply": 0.08,
    }.get(action.action_type, 0.04)
    recency = max(0.01, 0.11 - recency_index * 0.012)
    evidence = min(len(action.grounded_elements) * 0.025, 0.09)
    return round(min(0.96, action.weight * 0.58 + action_bonus + recency + evidence), 4)


def _recommendation_score(action: SocialAction, forecast: Forecast | None, *, recency_index: int) -> float:
    score = _hot_score(action, recency_index=recency_index)
    if forecast is None:
        return score
    if _is_opposing_stance(forecast, action):
        score += 0.09
    elif (
        (forecast.side == "home" and action.stance == "leans_home")
        or (forecast.side == "away" and action.stance == "leans_away")
        or (forecast.side == "draw" and action.stance in {"neutral", "leans_draw"})
    ):
        score += 0.07
    score += INFLUENCE_BONUS.get(forecast.influence_weight, 0.0) * 0.22
    return round(min(score, 0.99), 4)


def _final_prediction_cards(
    *,
    match: MatchContext,
    claim: DebateClaim,
    forecasts_by_agent: dict[str, Forecast],
    rng: random.Random,
) -> list[SocialAction]:
    forecasts = list(forecasts_by_agent.values())
    if not forecasts:
        return []
    forecasts.sort(key=lambda forecast: (forecast.side, abs(forecast.edge), forecast.stake, forecast.agent_id), reverse=True)
    selected = forecasts
    actions = []
    for index, forecast in enumerate(selected, start=1):
        actions.append(
            SocialAction(
                action_id=f"social:{claim.round_id}:prediction:{index:02d}:{forecast.agent_id}",
                round_id=claim.round_id,
                room_id="prediction_cards",
                phase="prediction",
                action_type="prediction_card",
                actor_id=forecast.agent_id,
                actor_name=forecast.agent_id.replace("_", "-"),
                role="predictor",
                stance=_stance_from_forecast(forecast),
                target_action_id=f"social:{claim.round_id}:final:01:{claim.speaker_id}",
                target_actor_id=claim.speaker_id,
                topic="group_stage_outcome",
                text=_prediction_card_text(forecast, match),
                grounded_elements=_grounded_elements(claim)[:3],
                tags=["prediction_card", forecast.side, forecast.risk_profile],
                weight=round(min(1.0, 0.35 + abs(forecast.edge) * 8.0), 4),
                metadata={
                    "platform": "prediction_cards",
                    "simulated_hour": _simulated_hour(9, index),
                    "round_index": 9,
                    "activation_reason": "mandatory_final_pick",
                    "recommendation_score": 1.0,
                    "oasis_action": "CREATE_POST",
                },
            )
        )
    rng.shuffle(actions)
    return actions


def _recommended_target(
    local_actions: list[SocialAction],
    forecast: Forecast | None,
    rng: random.Random,
    *,
    recency_index: int = 1,
) -> tuple[SocialAction, float]:
    candidates = list(local_actions)
    if forecast is not None and forecast.side != "pass":
        aligned = [
            action
            for action in candidates
            if (forecast.side == "home" and action.stance == "leans_home")
            or (forecast.side == "away" and action.stance == "leans_away")
            or (forecast.side == "draw" and action.stance in {"neutral", "leans_draw"})
        ]
        if aligned:
            candidates = aligned
    scored = [
        (_recommendation_score(action, forecast, recency_index=recency_index + index - 1), action)
        for index, action in enumerate(candidates, start=1)
    ]
    scored.sort(key=lambda item: (item[0], item[1].weight), reverse=True)
    top_score = scored[0][0]
    top = [item for item in scored if abs(item[0] - top_score) < 0.04]
    score, action = rng.choice(top[: min(3, len(top))])
    return action, round(score, 4)


def _crowd_action_type(index: int, forecast: Forecast | None, target: SocialAction) -> str:
    if forecast is None:
        return "view"
    if _is_opposing_stance(forecast, target):
        return "comment_challenge" if index % 2 else "quote_reply"
    if forecast.influence_weight == "high" and index % 5 == 0:
        return "follow"
    if forecast.risk_profile == "risky" and index % 4 == 0:
        return "share"
    if forecast.side != "pass":
        return "like" if index % 3 else "comment_support"
    return "view"


def _crowd_text(
    *,
    action_type: str,
    actor_id: str,
    target: SocialAction,
    forecast: Forecast | None,
    match: MatchContext,
) -> str:
    subject = _primary_subject(target)
    if action_type in {"endorse", "like"}:
        return f"{actor_id.replace('_', '-')} backs {target.actor_name} on {subject}. Short version: that point is live."
    if action_type in {"quote_reply", "share"}:
        side = _side_name(forecast.side if forecast else "pass", match)
        if forecast is not None and (_is_opposing_stance(forecast, target) or forecast.side == "draw"):
            return f"{actor_id.replace('_', '-')} quote-replies: {subject} is the risk, but the pick stays {side}."
        return f"{actor_id.replace('_', '-')} quote-replies: {side} is the pick if {subject} holds up."
    if action_type == "comment_challenge":
        side = _side_name(forecast.side if forecast else "pass", match)
        return f"{actor_id.replace('_', '-')} pushes back on {subject}; their room pick is still {side}."
    if action_type == "comment_support":
        side = _side_name(forecast.side if forecast else "pass", match)
        return f"{actor_id.replace('_', '-')} comments in support: {subject} keeps the {side} case alive."
    if action_type == "follow":
        return f"{actor_id.replace('_', '-')} follows {target.actor_name}'s thread for the next room."
    return f"{actor_id.replace('_', '-')} is in the room and flags {subject} for the final vote."


def _prediction_card_text(forecast: Forecast, match: MatchContext) -> str:
    side = _side_name(forecast.side, match)
    value = _value_label(forecast.edge)
    if forecast.side == "pass":
        return f"{forecast.agent_id.replace('_', '-')} prediction card: no clean bet; keep watching the evidence board."
    total_goals = _total_goals_call(forecast.home_probability)
    risk_phrase = {
        "secure": "plays it safe",
        "balanced": "keeps it balanced",
        "risky": "takes the swing",
    }.get(forecast.risk_profile, "locks a pick")
    return (
        f"{forecast.agent_id.replace('_', '-')} {risk_phrase}: {side}. "
        f"Edge feels {value}; score shape: {total_goals}."
    )


def _stance_from_forecast(forecast: Forecast | None) -> str:
    if forecast is None:
        return "neutral"
    if forecast.side == "home":
        return "leans_home"
    if forecast.side == "away":
        return "leans_away"
    if forecast.side == "draw":
        return "leans_draw"
    side = forecast_side_for_probability(forecast.home_probability)
    if side == "home":
        return "leans_home"
    if side == "away":
        return "leans_away"
    if side == "draw":
        return "leans_draw"
    return "neutral"


def _side_name(side: str, match: MatchContext) -> str:
    if side == "home":
        return match.home_team
    if side == "away":
        return match.away_team
    if side == "draw":
        return "draw"
    return "no-bet"


def _primary_subject(action: SocialAction) -> str:
    if action.grounded_elements:
        return str(action.grounded_elements[0].get("subject") or "the evidence")
    return "the evidence"


def _crowd_weight(forecast: Forecast | None, target: SocialAction) -> float:
    if forecast is None:
        return round(max(0.1, target.weight * 0.45), 4)
    return round(min(1.0, 0.2 + abs(forecast.edge) * 5.0 + target.weight * 0.35), 4)


def _value_label(edge: float) -> str:
    value = abs(edge)
    if value >= 0.055:
        return "strong"
    if value >= 0.025:
        return "medium"
    if value > 0:
        return "thin"
    return "no"


def _total_goals_call(home_probability: float) -> str:
    side = forecast_side_for_probability(home_probability)
    if side == "draw":
        return "tight scoreline"
    return "open scoreline" if abs(home_probability - 0.5) > 0.04 else "controlled scoreline"
