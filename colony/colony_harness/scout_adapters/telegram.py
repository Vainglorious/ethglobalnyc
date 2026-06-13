"""Telegram-backed social/news scout adapter.

The adapter is deliberately optional. It can read a local JSON export, or, when
enabled, fetch recent messages from whitelisted Telegram chats via Telethon. In
both cases it normalizes messages into Colony ``Finding`` objects without making
Telegram a hard dependency of the core harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import Finding


@dataclass(frozen=True)
class TelegramItem:
    text: str
    chat: str
    message_id: str
    link: str
    published: str
    views: int | None = None
    forwards: int | None = None
    replies: int | None = None
    reactions: int | None = None


def telegram_findings_for_match(
    *,
    round_id: str,
    home_team: str,
    away_team: str,
    market: float,
    news_probability: float,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[Finding]:
    items = fetch_telegram_items(
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_dir,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    claims = _claims_from_items(items, home_team=home_team, away_team=away_team)
    if not claims:
        return []
    probability = _probability_from_claims(
        claims,
        market=market,
        news_anchor=news_probability,
    )
    summary = "Fetched Telegram/social messages from configured chats or a local export."
    citations = ["telegram://configured-chats"]
    confidence = 0.34
    if items:
        summary = (
            "Fetched Telegram/social messages from configured chats or a local export. "
            f"Top signals: {_titles(items)}"
        )
        citations = [item.link for item in items[:6] if item.link] or ["telegram://configured-chats"]
        confidence = 0.38

    return [
        _finding(
            round_id=round_id,
            key="telegram_social",
            scout_name="telegram_social_scout",
            access_level="shared",
            source_type="social",
            finding_name="telegram_social_and_news_read",
            home_probability=probability,
            market=market,
            confidence=confidence,
            summary=summary,
            citations=citations,
            evidence_claims=claims,
        )
    ]


def fetch_telegram_items(
    *,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[TelegramItem]:
    export_path = os.environ.get("COLONY_TELEGRAM_SCOUT_JSON", "").strip() or os.environ.get(
        "TELEGRAM_SCOUT_JSON", ""
    ).strip()
    if export_path:
        return _items_from_export(Path(export_path), home_team=home_team, away_team=away_team)

    if os.environ.get("COLONY_TELEGRAM_ENABLE_LIVE", "").strip() != "1":
        return []

    cache_file = cache_dir / f"telegram_{_slug(home_team)}_{_slug(away_team)}.json"
    if cache_file.exists() and not refresh:
        return _items_from_payload(json.loads(cache_file.read_text(encoding="utf-8")), home_team, away_team)

    try:
        payload = asyncio.run(
            _fetch_live_telegram_payload(
                home_team=home_team,
                away_team=away_team,
                timeout_seconds=timeout_seconds,
            )
        )
    except Exception:
        return []

    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return _items_from_payload(payload, home_team, away_team)


async def _fetch_live_telegram_payload(*, home_team: str, away_team: str, timeout_seconds: int) -> list[dict]:
    _load_env_file(Path(os.environ.get("COLONY_TELEGRAM_ENV", "polygun/.env")))
    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    chats = [chat.strip().lstrip("@") for chat in os.environ.get("COLONY_TELEGRAM_CHATS", "").split(",") if chat.strip()]
    if not api_id or not api_hash or not chats:
        return []

    from telethon import TelegramClient

    session_name = os.environ.get("COLONY_TELEGRAM_SESSION", "polygun/pg")
    client = TelegramClient(session_name, int(api_id), api_hash)
    await asyncio.wait_for(client.connect(), timeout=timeout_seconds)
    try:
        if not await client.is_user_authorized():
            return []
        payload: list[dict] = []
        for chat in chats:
            messages = await client.get_messages(chat, limit=25)
            for message in messages:
                text = getattr(message, "text", "") or ""
                if not _mentions_match(text, home_team=home_team, away_team=away_team):
                    continue
                payload.append(
                    {
                        "text": text,
                        "chat": chat,
                        "message_id": str(getattr(message, "id", "")),
                        "published": str(getattr(message, "date", "")),
                        "link": f"telegram://{chat}/{getattr(message, 'id', '')}",
                        "views": getattr(message, "views", None),
                        "forwards": getattr(message, "forwards", None),
                    }
                )
        return payload
    finally:
        await client.disconnect()


def _items_from_export(path: Path, *, home_team: str, away_team: str) -> list[TelegramItem]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return _items_from_payload(payload, home_team, away_team)


def _items_from_payload(payload: Any, home_team: str, away_team: str) -> list[TelegramItem]:
    if isinstance(payload, dict):
        raw_items = payload.get("messages") or payload.get("items") or payload.get("data") or []
    elif isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = []

    items: list[TelegramItem] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        text = _clean_text(str(raw.get("text") or raw.get("message") or raw.get("title") or ""))
        if not text or not _mentions_match(text, home_team=home_team, away_team=away_team):
            continue
        chat = str(raw.get("chat") or raw.get("source") or raw.get("channel") or "telegram")
        message_id = str(raw.get("message_id") or raw.get("id") or "")
        link = str(raw.get("link") or raw.get("url") or f"telegram://{chat}/{message_id}")
        published = str(raw.get("published") or raw.get("date") or raw.get("created_at") or "")
        items.append(
            TelegramItem(
                text=text,
                chat=chat,
                message_id=message_id,
                link=link,
                published=published,
                views=_int_or_none(raw.get("views") or raw.get("view_count")),
                forwards=_int_or_none(raw.get("forwards") or raw.get("forward_count")),
                replies=_int_or_none(raw.get("replies") or raw.get("reply_count")),
                reactions=_reaction_count(raw.get("reactions") or raw.get("reaction_count")),
            )
        )
    return _dedupe(items)[:20]


def _claims_from_items(items: list[TelegramItem], *, home_team: str, away_team: str) -> list[dict]:
    claims: list[dict] = []
    for item in items[:10]:
        for sentence in _sentences(item.text):
            lowered = sentence.lower()
            claim_type = _claim_type(lowered)
            if claim_type is None:
                continue
            team = _team_from_sentence(sentence, home_team=home_team, away_team=away_team)
            if not team:
                continue
            player = _player_from_sentence(sentence, team=team, home_team=home_team, away_team=away_team)
            claims.append(
                {
                    "claim_type": claim_type,
                    "subject": player or team,
                    "team": team,
                    "player": player,
                    "claim": _shorten(sentence, 260),
                    "impact": _claim_impact(claim_type, team=team, home_team=home_team),
                    "confidence": _claim_confidence(claim_type, lowered),
                    "source_title": f"Telegram:{item.chat}",
                    "source_url": item.link,
                    "source_published": item.published,
                    "source_domain": "telegram",
                    "source_kind": "social",
                    "source_quality": "medium",
                    "extraction_method": "telegram_message_heuristic",
                    "metrics": {
                        **_claim_metrics(claim_type, sentence),
                        **_telegram_item_metrics(item, sentence),
                    },
                }
            )
    return _dedupe_claims(claims)[:12]


def _probability_from_claims(claims: list[dict], *, market: float, news_anchor: float) -> float:
    shift = 0.0
    for claim in claims:
        confidence = float(claim.get("confidence") or 0.35)
        impact = str(claim.get("impact") or "")
        if impact == "negative_home":
            shift -= 0.008 * confidence
        elif impact == "negative_away":
            shift += 0.008 * confidence
        elif impact == "context_home":
            shift += 0.003 * confidence
        elif impact == "context_away":
            shift -= 0.003 * confidence
    anchor = (news_anchor * 0.7) + (market * 0.3)
    return round(min(max(anchor + shift, 0.01), 0.99), 4)


def _claim_type(lowered_sentence: str) -> str | None:
    if any(word in lowered_sentence for word in ("injury", "injured", "doubt", "ruled out", "misses", "unavailable")):
        return "injury_availability"
    if any(word in lowered_sentence for word in ("lineup", "line-up", "starting xi", "starting 11", "bench")):
        return "lineup"
    if any(word in lowered_sentence for word in ("goals", "assists", "minutes", "scored", "season form", "club form")):
        return "player_form"
    if any(word in lowered_sentence for word in ("last matches", "recent form", "unbeaten", "winning streak", "results")):
        return "recent_form"
    if any(word in lowered_sentence for word in ("odds", "price", "market", "favorite", "favourite", "sharp")):
        return "market_preview"
    return None


def _claim_impact(claim_type: str, *, team: str, home_team: str) -> str:
    if claim_type == "injury_availability":
        return "negative_home" if team == home_team else "negative_away"
    return "context_home" if team == home_team else "context_away"


def _claim_confidence(claim_type: str, lowered_sentence: str) -> float:
    confidence = {
        "injury_availability": 0.52,
        "lineup": 0.44,
        "player_form": 0.42,
        "recent_form": 0.4,
        "market_preview": 0.34,
    }.get(claim_type, 0.3)
    if any(marker in lowered_sentence for marker in ("confirmed", "official", "reported")):
        confidence += 0.08
    if any(marker in lowered_sentence for marker in ("rumor", "rumour", "unconfirmed", "maybe")):
        confidence -= 0.08
    return round(max(min(confidence, 0.75), 0.12), 2)


def _claim_metrics(claim_type: str, text: str) -> dict:
    lowered = text.lower()
    metrics: dict[str, object] = {}
    if claim_type == "injury_availability":
        if any(marker in lowered for marker in ("ruled out", "misses", "unavailable")):
            metrics["availability_status"] = "out"
        elif "doubt" in lowered:
            metrics["availability_status"] = "doubtful"
        elif "injur" in lowered:
            metrics["availability_status"] = "injured"
    for key, pattern in (
        ("goals", r"\b(\d+(?:\.\d+)?)\s+goals?\b"),
        ("assists", r"\b(\d+(?:\.\d+)?)\s+assists?\b"),
        ("minutes", r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\s+minutes?\b"),
    ):
        match = re.search(pattern, lowered)
        if match:
            raw = match.group(1).replace(",", "")
            value = float(raw)
            metrics[key] = int(value) if value.is_integer() else round(value, 4)
    return metrics


def _telegram_item_metrics(item: TelegramItem, sentence: str) -> dict:
    lowered = sentence.lower()
    metrics: dict[str, object] = {
        "telegram_chat": item.chat,
        "telegram_message_id": item.message_id,
    }
    for key, value in (
        ("telegram_views", item.views),
        ("telegram_forwards", item.forwards),
        ("telegram_replies", item.replies),
        ("telegram_reactions", item.reactions),
    ):
        if value is not None:
            metrics[key] = value
    if any(marker in lowered for marker in ("official", "confirmed", "club statement", "federation statement")):
        metrics["verification_signal"] = "official"
    elif any(marker in lowered for marker in ("reported", "according to", "sources say")):
        metrics["verification_signal"] = "reported"
    if any(marker in lowered for marker in ("rumor", "rumour", "unconfirmed", "maybe", "could miss")):
        metrics["rumor_signal"] = "unconfirmed"
    if any(marker in lowered for marker in ("fan reaction", "fans", "supporters", "sentiment")):
        metrics["social_context"] = "crowd_reaction"
    return {key: value for key, value in metrics.items() if value not in {None, ""}}


def _mentions_match(text: str, *, home_team: str, away_team: str) -> bool:
    lowered = text.lower()
    return home_team.lower() in lowered or away_team.lower() in lowered


def _team_from_sentence(sentence: str, *, home_team: str, away_team: str) -> str:
    lowered = sentence.lower()
    home_index = lowered.find(home_team.lower())
    away_index = lowered.find(away_team.lower())
    if home_index >= 0 and away_index >= 0:
        return home_team if home_index < away_index else away_team
    if home_index >= 0:
        return home_team
    if away_index >= 0:
        return away_team
    return ""


def _player_from_sentence(sentence: str, *, team: str, home_team: str, away_team: str) -> str:
    ignored = {
        team.lower(),
        home_team.lower(),
        away_team.lower(),
        "world cup",
        "team news",
        "breaking",
        "official",
        "reported",
    }
    patterns = [
        r"\b(?:official|confirmed|reported|breaking)[:\s-]+([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]+){0,2})\s+(?:is|has|was|will|could)",
        r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]+){0,2})\s+(?:is|has|was|will|could)\s+(?:ruled out|injured|unavailable|doubtful|miss|misses|start|starts|bench)",
        r"\b([A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]+(?:\s+[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'’-]+){0,2})\s+(?:out|doubtful|injured)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, sentence)
        if not match:
            continue
        candidate = match.group(1).strip(" :,-")
        key = candidate.lower()
        if key not in ignored and not any(word in key for word in ("injury", "news", "lineup", "squad")):
            return candidate
    return ""


def _int_or_none(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _reaction_count(value: Any) -> int | None:
    if isinstance(value, list):
        total = 0
        for item in value:
            if isinstance(item, dict):
                total += _int_or_none(item.get("count")) or 0
            else:
                total += 1
        return total or None
    if isinstance(value, dict):
        return sum(_int_or_none(count) or 0 for count in value.values()) or None
    return _int_or_none(value)


def _finding(
    *,
    round_id: str,
    key: str,
    scout_name: str,
    access_level: str,
    source_type: str,
    finding_name: str,
    home_probability: float | None,
    market: float,
    confidence: float,
    summary: str,
    citations: list[str],
    cost: float = 0.0,
    evidence_claims: list[dict] | None = None,
) -> Finding:
    clean_claims = _admissible_claims(evidence_claims or [])
    return Finding(
        finding_id=f"{round_id}:{key}",
        scout_name=scout_name,
        access_level=access_level,  # type: ignore[arg-type]
        source_type=source_type,  # type: ignore[arg-type]
        finding_name=finding_name,
        home_probability=round(home_probability, 4) if home_probability is not None else None,
        home_delta=round(home_probability - market, 4) if home_probability is not None else None,
        confidence=confidence,
        cost=cost,
        citations=citations,
        summary=summary,
        evidence_claims=clean_claims,
    )


def _admissible_claims(claims: list[dict]) -> list[dict]:
    return [
        claim
        for claim in claims
        if claim.get("claim_type")
        and claim.get("claim")
        and claim.get("team")
        and claim.get("source_url")
        and str(claim.get("impact") or "") != "unknown"
        and str(claim.get("source_quality") or "").lower() != "weak"
    ]


def _sentences(text: str) -> list[str]:
    chunks = re.split(r"(?<=[.!?])\s+|;\s+", _clean_text(text))
    return [chunk.strip(" -") for chunk in chunks if 28 <= len(chunk.strip()) <= 420]


def _dedupe(items: list[TelegramItem]) -> list[TelegramItem]:
    seen: set[str] = set()
    deduped: list[TelegramItem] = []
    for item in items:
        key = item.link or item.text.lower()[:160]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _dedupe_claims(claims: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for claim in claims:
        key = (
            str(claim.get("claim_type") or ""),
            str(claim.get("subject") or "").lower(),
            str(claim.get("claim") or "").lower()[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def _titles(items: list[TelegramItem]) -> str:
    return "; ".join(_shorten(item.text, 90) for item in items[:4])


def _shorten(text: str, limit: int) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().split() if part)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
