"""PolyGun snapshot scout adapter.

This adapter never places trades. It reads a local snapshot exported from
``polygun/pg.py snapshot`` or another JSON source and turns only match-specific
market panel text into Colony findings for scouting provenance.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from ..models import Finding


def polygun_findings_for_match(
    *,
    round_id: str,
    home_team: str,
    away_team: str,
    market: float,
    cache_dir: Path,
) -> list[Finding]:
    snapshot = _load_snapshot(cache_dir)
    claims = _claims_from_snapshot(snapshot, home_team=home_team, away_team=away_team)
    if not claims:
        return []
    probability = _probability_from_snapshot(snapshot, home_team=home_team, away_team=away_team)
    summary = "Read a match-specific PolyGun Telegram-bot market snapshot. This is read-only and does not send orders."
    citations = ["telegram://PolyGunSniperBot"]
    confidence = 0.28
    if snapshot:
        summary = (
            "Read a match-specific PolyGun Telegram-bot snapshot for visible market panel text. "
            "This is read-only and does not send orders."
        )
        citations = ["telegram://PolyGunSniperBot"]
        confidence = 0.32

    return [
        _finding(
            round_id=round_id,
            key="polygun_snapshot",
            scout_name="polygun_snapshot_scout",
            access_level="private",
            source_type="market",
            finding_name="polygun_market_snapshot",
            home_probability=probability,
            market=market,
            confidence=confidence,
            summary=summary,
            citations=citations,
            evidence_claims=claims,
        )
    ]


def _load_snapshot(cache_dir: Path) -> dict:
    candidates = [
        os.environ.get("COLONY_POLYGUN_SNAPSHOT_JSON", "").strip(),
        os.environ.get("POLYGUN_SCOUT_SNAPSHOT_JSON", "").strip(),
        "polygun/snapshots/latest.json",
        str(cache_dir / "polygun_snapshot.json"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _claims_from_snapshot(snapshot: dict, *, home_team: str, away_team: str) -> list[dict]:
    if not snapshot:
        return []
    messages = _snapshot_messages(snapshot)
    claims: list[dict] = []
    for message in messages:
        text = _message_text(message)
        lowered = text.lower()
        if not text:
            continue
        source_url = f"telegram://PolyGunSniperBot/{message.get('id') or message.get('message_id') or ''}"
        if any(token in lowered for token in ("position", "positions", "shares", "yes", "no")) and (
            home_team.lower() in lowered or away_team.lower() in lowered or "world cup" in lowered
        ):
            team = home_team if home_team.lower() in lowered else away_team if away_team.lower() in lowered else ""
            if not team:
                continue
            claims.append(
                _claim(
                    claim_type="market_snapshot",
                    subject="PolyGun visible position",
                    team=team,
                    claim=_shorten(text, 260),
                    impact="context_home" if team == home_team else "context_away",
                    confidence=0.4,
                    source_url=source_url,
                )
            )
        if any(token in lowered for token in ("buy yes", "buy no", "price", "odds", "market")) and (
            home_team.lower() in lowered or away_team.lower() in lowered
        ):
            team = home_team if home_team.lower() in lowered else away_team
            claims.append(
                _claim(
                    claim_type="market_snapshot",
                    subject=f"PolyGun market panel for {team}",
                    team=team,
                    claim=_shorten(text, 260),
                    impact="context_home" if team == home_team else "context_away",
                    confidence=0.34,
                    source_url=source_url,
                )
            )
    return _dedupe_claims(claims)[:10]


def _probability_from_snapshot(snapshot: dict, *, home_team: str, away_team: str) -> float | None:
    if not snapshot:
        return None
    text = " ".join(_message_text(message) for message in _snapshot_messages(snapshot)).lower()
    if not text:
        return None
    for team, side in ((home_team, "home"), (away_team, "away")):
        if team.lower() not in text:
            continue
        probability = _price_probability(text)
        if probability is None:
            continue
        return probability if side == "home" else round(1.0 - probability, 4)
    return None


def _snapshot_messages(snapshot: dict) -> list[dict]:
    raw = snapshot.get("messages") or snapshot.get("items") or snapshot.get("data") or []
    return [item for item in raw if isinstance(item, dict)]


def _message_text(message: dict) -> str:
    buttons = message.get("buttons") or []
    button_text = " ".join(str(button.get("text") or "") for button in buttons if isinstance(button, dict))
    return _clean_text(f"{message.get('text') or message.get('message') or ''} {button_text}")


def _claim(
    *,
    claim_type: str,
    subject: str,
    team: str,
    claim: str,
    impact: str,
    confidence: float,
    source_url: str,
) -> dict:
    return {
        "claim_type": claim_type,
        "subject": subject,
        "team": team,
        "player": "",
        "claim": claim,
        "impact": impact,
        "confidence": confidence,
        "source_title": "PolyGun Telegram bot snapshot",
        "source_url": source_url,
        "source_published": "",
        "source_domain": "telegram",
        "source_kind": "market_snapshot",
        "source_quality": "medium",
        "extraction_method": "polygun_snapshot_parse",
        "metrics": _claim_metrics(claim),
    }


def _claim_metrics(text: str) -> dict:
    lowered = text.lower()
    metrics: dict[str, object] = {}
    match = re.search(r"\b(\d+(?:\.\d+)?)\s+pusd\b", lowered)
    if match:
        metrics["pusd_amount"] = float(match.group(1))
    if "buy yes" in lowered:
        metrics["visible_side"] = "yes"
    elif "buy no" in lowered:
        metrics["visible_side"] = "no"
    probability = _price_probability(lowered)
    if probability is not None:
        metrics["visible_price_probability"] = probability
    return metrics


def _price_probability(text: str) -> float | None:
    lowered = text.lower()
    pct_match = re.search(r"\b(\d+(?:\.\d+)?)\s*%\b", lowered)
    if pct_match:
        value = float(pct_match.group(1)) / 100.0
        if 0.01 <= value <= 0.99:
            return round(value, 4)
    price_match = re.search(r"\b(?:price|odds)\D{0,12}(0?\.\d{1,4})\b", lowered)
    if price_match:
        value = float(price_match.group(1))
        if 0.01 <= value <= 0.99:
            return round(value, 4)
    cent_match = re.search(r"\b(\d{1,2})\s*c(?:ents?)?\b", lowered)
    if cent_match:
        value = float(cent_match.group(1)) / 100.0
        if 0.01 <= value <= 0.99:
            return round(value, 4)
    return None


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
    ]


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


def _shorten(text: str, limit: int) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _clean_text(text: str) -> str:
    return " ".join(text.split())
