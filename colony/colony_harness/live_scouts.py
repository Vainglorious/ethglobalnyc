"""Public-data scouts for one-match Colony tests.

They fetch lightweight public sources and turn them into normalized findings
for the existing harness. X/social and CAMEL-style research scouts are optional
so their value can be compared explicitly in logs.
"""

from __future__ import annotations

import json
import os
import re
import hashlib
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Finding, MatchContext, SourceType
from .scout_adapters.polygun import polygun_findings_for_match
from .scout_adapters.telegram import telegram_findings_for_match
from .scouts import synthetic_probabilities


DEFAULT_TIMEOUT_SECONDS = 15
USER_AGENT = "ColonyHarness/0.1 (public football scout; no social scraping)"

STAR_PLAYERS = {
    "Brazil": [
        "neymar",
        "vinicius",
        "vinicius jr",
        "vinicius junior",
        "raphinha",
        "alisson",
        "rodrygo",
        "endrick",
        "bruno guimaraes",
        "gabriel",
        "marquinhos",
    ],
    "Morocco": [
        "hakimi",
        "achraf hakimi",
        "ziyech",
        "hakim ziyech",
        "bounou",
        "yassine bounou",
        "brahim diaz",
        "amrabat",
        "sofyan amrabat",
        "nayef aguerd",
        "aguerd",
        "ez abde",
        "abde",
        "en-nesyri",
        "youssef en-nesyri",
        "mazraoui",
    ],
    "France": ["mbappe", "kylian mbappe", "griezmann", "dembele", "camavinga", "maignan", "tchouameni"],
    "Senegal": ["mane", "sadio mane", "koulibaly", "mendy", "gueye", "jackson", "nicolas jackson", "sarr"],
    "Scotland": ["mctominay", "mcginn", "robertson", "tierney", "gilmour", "che adams"],
    "Haiti": ["nazon", "ducken nazon", "pierrot", "frantzdy pierrot", "placide"],
    "Qatar": ["akram afif", "afif", "almoez ali", "al-haydos", "barsham"],
    "Switzerland": ["xhaka", "granit xhaka", "akanji", "embolo", "sommer", "ndoye", "zakaria"],
}


@dataclass(frozen=True)
class TeamProfile:
    team: str
    title: str
    extract: str
    page_url: str


@dataclass(frozen=True)
class NewsItem:
    title: str
    source: str
    link: str
    published: str


@dataclass(frozen=True)
class SquadPlayer:
    team: str
    name: str
    position: str
    club: str
    caps: int | None
    goals: int | None
    source_title: str
    source_url: str


@dataclass(frozen=True)
class EvidenceClaim:
    claim_type: str
    subject: str
    claim: str
    team: str | None
    player: str | None
    impact: str
    confidence: float
    source_title: str
    source_url: str
    source_published: str = ""
    source_published_date: str = ""
    source_recency_days: int | None = None
    source_recency_bucket: str = ""
    source_domain: str = ""
    source_kind: str = ""
    source_quality: str = "medium"
    extraction_method: str = "heuristic_sentence"
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "claim_type": self.claim_type,
            "subject": self.subject,
            "claim": self.claim,
            "team": self.team,
            "player": self.player,
            "impact": self.impact,
            "confidence": self.confidence,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "source_published": self.source_published,
            "source_published_date": self.source_published_date,
            "source_recency_days": self.source_recency_days,
            "source_recency_bucket": self.source_recency_bucket,
            "source_domain": self.source_domain,
            "source_kind": self.source_kind,
            "source_quality": self.source_quality,
            "extraction_method": self.extraction_method,
            "metrics": self.metrics,
        }


def public_match_context_from_tournament_match(
    match_entity: dict,
    *,
    cache_dir: str | Path,
    refresh: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    include_x: bool = False,
    include_camel: bool = False,
    include_telegram: bool = False,
    include_polygun: bool = False,
    rescout_targets: list[dict] | None = None,
) -> MatchContext:
    """Create a match context from real public sources and optional research scouts."""
    attrs = match_entity["attributes"]
    home_team = str(attrs["team1"])
    away_team = str(attrs["team2"])
    round_id = str(match_entity["entity_id"]).replace("match:", "round:")

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    home_profile = fetch_team_profile(home_team, cache_path, refresh=refresh, timeout_seconds=timeout_seconds)
    away_profile = fetch_team_profile(away_team, cache_path, refresh=refresh, timeout_seconds=timeout_seconds)
    squad_rosters = {
        home_team: fetch_team_roster(home_team, cache_path, refresh=refresh, timeout_seconds=timeout_seconds),
        away_team: fetch_team_roster(away_team, cache_path, refresh=refresh, timeout_seconds=timeout_seconds),
    }
    known_players = _known_players_by_team(squad_rosters)
    match_news = fetch_news_query(
        cache_key=f"match_news_{_slug(home_team)}_{_slug(away_team)}",
        query=f"{home_team} {away_team} World Cup football",
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    match_history_items = fetch_match_history_news(
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    tactical_items = fetch_tactical_matchup_news(
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    recent_results_news = {
        home_team: fetch_news_query(
            cache_key=f"recent_results_{_slug(home_team)}",
            query=f"{home_team} national football team recent results 2026",
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        ),
        away_team: fetch_news_query(
            cache_key=f"recent_results_{_slug(away_team)}",
            query=f"{away_team} national football team recent results 2026",
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        ),
    }
    team_scout_news = {
        home_team: fetch_team_scout_news(
            home_team,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
            known_players=known_players,
        ),
        away_team: fetch_team_scout_news(
            away_team,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
            known_players=known_players,
        ),
    }
    official_squad_items = {
        home_team: fetch_official_squad_news(
            home_team,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        ),
        away_team: fetch_official_squad_news(
            away_team,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        ),
    }
    availability_news = fetch_news_query(
        cache_key=f"availability_{_slug(home_team)}_{_slug(away_team)}",
        query=f"{home_team} {away_team} World Cup squad injuries players Neymar",
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    x_items = (
        fetch_x_availability(
            home_team=home_team,
            away_team=away_team,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
        if include_x
        else []
    )
    camel_items = (
        fetch_camel_research(
            home_team=home_team,
            away_team=away_team,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
        if include_camel
        else []
    )
    availability_claims = extract_evidence_claims(
        items=availability_news,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=2,
        known_players=known_players,
    )
    x_claims = extract_evidence_claims(
        items=x_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    camel_claims = extract_evidence_claims(
        items=camel_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    result_archive_items = _team_scout_items(team_scout_news, "recent_form", max_per_team=3)
    tactical_lineup_items = _tactical_items_from_team_scouts(
        team_scout_news,
        home_team=home_team,
        away_team=away_team,
    )
    all_tactical_items = _dedupe_items(tactical_items + tactical_lineup_items)
    team_form_claims = extract_evidence_claims(
        items=result_archive_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    player_form_claims = extract_evidence_claims(
        items=_team_scout_items(team_scout_news, "player_form", max_per_team=3),
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    squad_depth_claims = extract_evidence_claims(
        items=_team_scout_items(team_scout_news, "squad_depth", max_per_team=3),
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    match_history_claims = extract_evidence_claims(
        items=match_history_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    tactical_claims = extract_evidence_claims(
        items=all_tactical_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
        known_players=known_players,
    )
    official_squad_claims = extract_evidence_claims(
        items=_team_items(official_squad_items, max_per_team=4),
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
    )
    official_squad_claims = _dedupe_claims(
        official_squad_claims
        + _topic_claims_from_items(
            items=_team_items(official_squad_items, max_per_team=4),
            claim_type="lineup",
            home_team=home_team,
            away_team=away_team,
            confidence=0.54,
            known_players=known_players,
        )
    )
    squad_roster_claims = _squad_roster_claims(squad_rosters, home_team=home_team, away_team=away_team)
    match_history_claims = _dedupe_claims(
        match_history_claims
        + _topic_claims_from_items(
            items=match_history_items + result_archive_items,
            claim_type="match_history",
            home_team=home_team,
            away_team=away_team,
            confidence=0.48,
            known_players=known_players,
        )
    )
    tactical_claims = _dedupe_claims(
        tactical_claims
        + _topic_claims_from_items(
            items=all_tactical_items,
            claim_type="tactical",
            home_team=home_team,
            away_team=away_team,
            confidence=0.48,
            known_players=known_players,
        )
    )

    market, stats, odds, news = public_probabilities(
        home_team=home_team,
        away_team=away_team,
        home_profile=home_profile,
        away_profile=away_profile,
        match_news=match_news,
        recent_results_news=recent_results_news,
        team_scout_news=team_scout_news,
        availability_news=availability_news,
        x_items=x_items,
        camel_items=camel_items,
        availability_claims=availability_claims,
        x_claims=x_claims,
        camel_claims=camel_claims,
        team_form_claims=team_form_claims,
        player_form_claims=player_form_claims,
        squad_depth_claims=squad_depth_claims,
        match_history_items=match_history_items,
        match_history_claims=match_history_claims,
        tactical_items=all_tactical_items,
        tactical_claims=tactical_claims,
        official_squad_claims=official_squad_claims,
        known_players=known_players,
    )
    findings = public_findings_for_match(
        round_id=round_id,
        home_team=home_team,
        away_team=away_team,
        market=market,
        stats=stats,
        odds=odds,
        news=news,
        home_profile=home_profile,
        away_profile=away_profile,
        match_news=match_news,
        recent_results_news=recent_results_news,
        team_scout_news=team_scout_news,
        availability_news=availability_news,
        x_items=x_items,
        camel_items=camel_items,
        availability_claims=availability_claims,
        x_claims=x_claims,
        camel_claims=camel_claims,
        team_form_claims=team_form_claims,
        player_form_claims=player_form_claims,
        squad_depth_claims=squad_depth_claims,
        match_history_items=match_history_items,
        match_history_claims=match_history_claims,
        tactical_items=all_tactical_items,
        official_squad_items=official_squad_items,
        squad_rosters=squad_rosters,
        tactical_claims=tactical_claims,
        official_squad_claims=official_squad_claims,
        squad_roster_claims=squad_roster_claims,
        include_x=include_x,
        include_camel=include_camel,
    )
    if include_telegram:
        findings.extend(
            telegram_findings_for_match(
                round_id=round_id,
                home_team=home_team,
                away_team=away_team,
                market=market,
                news_probability=news,
                cache_dir=cache_path,
                refresh=refresh,
                timeout_seconds=timeout_seconds,
            )
        )
    if include_polygun:
        findings.extend(
            polygun_findings_for_match(
                round_id=round_id,
                home_team=home_team,
                away_team=away_team,
                market=market,
                cache_dir=cache_path,
            )
        )
    findings.extend(
        _focused_rescout_findings(
            round_id=round_id,
            home_team=home_team,
            away_team=away_team,
            market=market,
            stats=stats,
            news=news,
            targets=rescout_targets or [],
            home_profile=home_profile,
            away_profile=away_profile,
            team_scout_news=team_scout_news,
            availability_claims=availability_claims,
            team_form_claims=team_form_claims,
            player_form_claims=player_form_claims,
            squad_depth_claims=squad_depth_claims,
            match_history_claims=match_history_claims,
            tactical_claims=tactical_claims,
            official_squad_claims=official_squad_claims,
            squad_roster_claims=squad_roster_claims,
            match_history_items=match_history_items,
            tactical_items=all_tactical_items,
            known_players=known_players,
            cache_dir=cache_path,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
    )
    return MatchContext(
        round_id=round_id,
        home_team=home_team,
        away_team=away_team,
        market_home_probability=market,
        stats_home_signal=stats,
        odds_home_signal=odds,
        news_home_signal=news,
        match_date=str(attrs.get("date") or ""),
        match_time=str(attrs.get("time") or ""),
        group_name=str(attrs.get("group") or ""),
        stage_name=str(attrs.get("round") or attrs.get("stage") or ""),
        venue_name=str(attrs.get("ground") or attrs.get("venue") or ""),
        score=str(attrs.get("score") or ""),
        findings=findings,
    )


def _focused_rescout_findings(
    *,
    round_id: str,
    home_team: str,
    away_team: str,
    market: float,
    stats: float,
    news: float,
    targets: list[dict],
    home_profile: TeamProfile,
    away_profile: TeamProfile,
    team_scout_news: dict[str, dict[str, list[NewsItem]]],
    availability_claims: list[EvidenceClaim],
    team_form_claims: list[EvidenceClaim],
    player_form_claims: list[EvidenceClaim],
    squad_depth_claims: list[EvidenceClaim],
    match_history_claims: list[EvidenceClaim],
    tactical_claims: list[EvidenceClaim],
    official_squad_claims: list[EvidenceClaim],
    squad_roster_claims: list[EvidenceClaim],
    match_history_items: list[NewsItem],
    tactical_items: list[NewsItem],
    known_players: dict[str, list[str]],
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[Finding]:
    findings: list[Finding] = []
    for target in targets:
        team = _match_team_name(str(target.get("team") or ""), home_team=home_team, away_team=away_team)
        claim_type = _clean_text(str(target.get("claim_type") or ""))
        if not team or not claim_type:
            continue
        claims = _focused_claims_for_target(
            team=team,
            claim_type=claim_type,
            home_team=home_team,
            away_team=away_team,
            home_profile=home_profile,
            away_profile=away_profile,
            team_scout_news=team_scout_news,
            availability_claims=availability_claims,
            team_form_claims=team_form_claims,
            player_form_claims=player_form_claims,
            squad_depth_claims=squad_depth_claims,
            match_history_claims=match_history_claims,
            tactical_claims=tactical_claims,
            official_squad_claims=official_squad_claims,
            squad_roster_claims=squad_roster_claims,
            match_history_items=match_history_items,
            tactical_items=tactical_items,
            known_players=known_players,
            cache_dir=cache_dir,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
        claim_dicts = _admissible_evidence_claims([claim.to_dict() for claim in _dedupe_claims(claims)])
        if not claim_dicts:
            continue
        finding_key = f"rescout_{_slug(team)}_{_slug(claim_type)}"
        findings.append(
            _finding(
                round_id=round_id,
                key=finding_key,
                scout_name=f"focused_{claim_type}_scout",
                access_level="public",
                source_type=_focused_source_type(claim_type),
                finding_name=f"focused_{claim_type}_rescout",
                home_probability=stats if claim_type in {"recent_form", "player_form", "match_history", "tactical"} else news,
                market=market,
                confidence=0.5,
                summary=(
                    f"Focused re-scout for {team} {claim_type}. "
                    "Only admissible, sourced claims are attached; empty focus results are not written."
                ),
                citations=list(dict.fromkeys(str(claim.get("source_url") or "") for claim in claim_dicts if claim.get("source_url")))[:6],
                evidence_claims=claim_dicts,
            )
        )
    return findings


def _focused_claims_for_target(
    *,
    team: str,
    claim_type: str,
    home_team: str,
    away_team: str,
    home_profile: TeamProfile,
    away_profile: TeamProfile,
    team_scout_news: dict[str, dict[str, list[NewsItem]]],
    availability_claims: list[EvidenceClaim],
    team_form_claims: list[EvidenceClaim],
    player_form_claims: list[EvidenceClaim],
    squad_depth_claims: list[EvidenceClaim],
    match_history_claims: list[EvidenceClaim],
    tactical_claims: list[EvidenceClaim],
    official_squad_claims: list[EvidenceClaim],
    squad_roster_claims: list[EvidenceClaim],
    match_history_items: list[NewsItem],
    tactical_items: list[NewsItem],
    known_players: dict[str, list[str]],
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    focused_items = _fetch_focused_rescout_items(
        team=team,
        claim_type=claim_type,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_dir,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        known_players=known_players,
    )
    if claim_type in {"team_profile", "team_history"}:
        claims.extend(_team_profile_claims(home_profile, away_profile))
    elif claim_type == "recent_form":
        claims.extend(team_form_claims)
        claims.extend(
            _topic_claims_from_items(
                items=team_scout_news.get(team, {}).get("recent_form", []) + focused_items,
                claim_type="recent_form",
                home_team=home_team,
                away_team=away_team,
                confidence=0.5,
                known_players=known_players,
            )
        )
    elif claim_type == "player_form":
        claims.extend(player_form_claims)
        claims.extend(
            _topic_claims_from_items(
                items=team_scout_news.get(team, {}).get("player_form", []) + focused_items,
                claim_type="player_form",
                home_team=home_team,
                away_team=away_team,
                confidence=0.5,
                known_players=known_players,
            )
        )
    elif claim_type == "squad_roster":
        claims.extend(squad_roster_claims)
    elif claim_type == "injury_availability":
        claims.extend(availability_claims)
    elif claim_type == "lineup":
        claims.extend(squad_depth_claims)
        claims.extend(official_squad_claims)
        claims.extend(
            _topic_claims_from_items(
                items=team_scout_news.get(team, {}).get("squad_depth", []) + focused_items,
                claim_type="lineup",
                home_team=home_team,
                away_team=away_team,
                confidence=0.5,
                known_players=known_players,
            )
        )
    elif claim_type == "match_history":
        claims.extend(match_history_claims)
        claims.extend(
            _topic_claims_from_items(
                items=match_history_items + team_scout_news.get(team, {}).get("recent_form", []) + focused_items,
                claim_type="match_history",
                home_team=home_team,
                away_team=away_team,
                confidence=0.5,
                known_players=known_players,
            )
        )
    elif claim_type == "tactical":
        claims.extend(tactical_claims)
        claims.extend(
            _topic_claims_from_items(
                items=tactical_items + team_scout_news.get(team, {}).get("squad_depth", []) + focused_items,
                claim_type="tactical",
                home_team=home_team,
                away_team=away_team,
                confidence=0.5,
                known_players=known_players,
            )
        )
    return [claim for claim in claims if claim.claim_type == claim_type and _claim_matches_team(claim, team)]


def _fetch_focused_rescout_items(
    *,
    team: str,
    claim_type: str,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
    known_players: dict[str, list[str]],
) -> list[NewsItem]:
    queries = _focused_rescout_queries(team=team, claim_type=claim_type)
    if not queries:
        return []
    items: list[NewsItem] = []
    for index, query in enumerate(queries):
        items.extend(
            _fetch_ddgs_query(
                query=query,
                cache_file=cache_dir / f"ddgs_rescout_{_slug(claim_type)}_{index}_{_slug(team)}.json",
                refresh=refresh,
                timeout_seconds=timeout_seconds,
                max_results=5,
            )
        )
    items = _dedupe_items(items)
    if claim_type == "match_history":
        match_items = _filter_match_history_items(items, home_team=home_team, away_team=away_team)
        form_items = _filter_topic_items(items, "recent_form", team=team, known_players=known_players)
        return _dedupe_items(match_items + form_items)[:8]
    if claim_type == "recent_form":
        return _filter_topic_items(items, "recent_form", team=team, known_players=known_players)[:8]
    if claim_type == "player_form":
        return _filter_topic_items(items, "player_form", team=team, known_players=known_players)[:8]
    if claim_type in {"lineup", "injury_availability", "squad_roster"}:
        return _filter_topic_items(items, "squad_depth", team=team, known_players=known_players)[:8]
    if claim_type == "tactical":
        tactical = _filter_tactical_items(items, home_team=home_team, away_team=away_team)
        squad_depth = _filter_topic_items(items, "squad_depth", team=team, known_players=known_players)
        return _dedupe_items(tactical + squad_depth)[:8]
    return items[:8]


def _focused_rescout_queries(*, team: str, claim_type: str) -> list[str]:
    common_suffix = "-prediction -predictions -odds -picks -betting"
    if claim_type == "recent_form":
        return [
            f"{team} national football team recent results fixtures last matches 2025 2026 {common_suffix}",
            f"{team} football results archive fixtures scores form 2026 {common_suffix}",
        ]
    if claim_type == "player_form":
        return [
            f"{team} football key players season stats goals assists appearances 2025 2026",
            f"{team} national team player form club season stats FBref SofaScore Transfermarkt",
        ]
    if claim_type == "injury_availability":
        return [
            f"{team} national football team injury report squad availability suspension 2026",
            f"{team} World Cup team news injuries doubtful ruled out squad",
        ]
    if claim_type == "lineup":
        return [
            f"{team} predicted lineup starting XI squad depth World Cup 2026",
            f"{team} football lineup squad roles key players 2026",
        ]
    if claim_type == "match_history":
        return [
            f"{team} national football team results fixtures scores 2025 2026 {common_suffix}",
            f"{team} national football team last 10 matches results form archive {common_suffix}",
            f"{team} football results archive match history fixtures scores {common_suffix}",
        ]
    if claim_type == "tactical":
        return [
            f"{team} football tactics formation pressing transition set pieces 2026",
            f"{team} national football team tactical analysis formation key players",
        ]
    if claim_type == "squad_roster":
        return [
            f"{team} national football team current squad roster players clubs positions 2026",
            f"{team} football federation squad players official roster",
        ]
    return []


def _claim_matches_team(claim: EvidenceClaim, team: str) -> bool:
    candidates = [claim.team, claim.subject]
    team_key = _fold_text(team)
    return any(_fold_text(str(candidate or "")) == team_key for candidate in candidates)


def _match_team_name(value: str, *, home_team: str, away_team: str) -> str:
    target = _fold_text(value)
    for team in (home_team, away_team):
        if _fold_text(team) == target:
            return team
    return ""


def _focused_source_type(claim_type: str) -> SourceType:
    if claim_type in {"recent_form", "player_form", "match_history", "tactical", "team_history"}:
        return "stats"
    if claim_type in {"squad_roster", "injury_availability", "lineup"}:
        return "lineup"
    return "news"


def fetch_team_profile(
    team: str,
    cache_dir: Path,
    *,
    refresh: bool,
    timeout_seconds: int,
) -> TeamProfile:
    title = f"{team} national football team"
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
    payload = _cached_json(
        cache_dir / f"wikipedia_{_slug(team)}.json",
        url,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    return TeamProfile(
        team=team,
        title=str(payload.get("title") or title),
        extract=_clean_text(str(payload.get("extract") or "")),
        page_url=str(payload.get("content_urls", {}).get("desktop", {}).get("page") or url),
    )


def fetch_team_roster(
    team: str,
    cache_dir: Path,
    *,
    refresh: bool,
    timeout_seconds: int,
) -> list[SquadPlayer]:
    """Fetch a structured current-squad table from Wikipedia wikitext."""
    title = f"{team} national football team"
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "parse",
            "page": title,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        }
    )
    try:
        payload = _cached_json(
            cache_dir / f"wikipedia_roster_{_slug(team)}.json",
            url,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return []
    wikitext = str(payload.get("parse", {}).get("wikitext") or "")
    source_title = str(payload.get("parse", {}).get("title") or title)
    source_url = f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    return _parse_wikipedia_squad_players(
        wikitext,
        team=team,
        source_title=source_title,
        source_url=source_url,
    )


def _parse_wikipedia_squad_players(
    wikitext: str,
    *,
    team: str,
    source_title: str,
    source_url: str,
) -> list[SquadPlayer]:
    players: list[SquadPlayer] = []
    current_section = _current_squad_wikitext_section(wikitext)
    for template_name, template in _extract_wiki_templates(
        current_section,
        names={"nat fs player", "nat fs g player", "football squad player"},
    ):
        fields = _template_fields(template)
        name = _clean_wiki_value(fields.get("name") or fields.get("player") or fields.get("p") or "")
        if not name:
            continue
        position = _clean_wiki_value(fields.get("pos") or fields.get("position") or "")
        club = _clean_wiki_value(fields.get("club") or fields.get("currentclub") or "")
        players.append(
            SquadPlayer(
                team=team,
                name=name,
                position=position,
                club=club,
                caps=_int_field(fields.get("caps")),
                goals=_int_field(fields.get("goals")),
                source_title=source_title,
                source_url=source_url,
            )
        )
    return _dedupe_squad_players(players)[:32]


def _extract_wiki_templates(wikitext: str, *, names: set[str]) -> list[tuple[str, str]]:
    templates: list[tuple[str, str]] = []
    lowered = wikitext.lower()
    index = 0
    while True:
        start = lowered.find("{{", index)
        if start < 0:
            break
        name_start = start + 2
        name_end = name_start
        while name_end < len(wikitext) and wikitext[name_end] not in "|}\n":
            name_end += 1
        template_name = _clean_text(wikitext[name_start:name_end]).lower()
        if template_name not in names:
            index = start + 2
            continue
        depth = 0
        cursor = start
        end = -1
        while cursor < len(wikitext) - 1:
            pair = wikitext[cursor : cursor + 2]
            if pair == "{{":
                depth += 1
                cursor += 2
                continue
            if pair == "}}":
                depth -= 1
                cursor += 2
                if depth == 0:
                    end = cursor
                    break
                continue
            cursor += 1
        if end < 0:
            break
        body = wikitext[name_end + 1 : end - 2] if name_end < end else ""
        templates.append((template_name, body))
        index = end
    return templates


def _current_squad_wikitext_section(wikitext: str) -> str:
    match = re.search(r"==+\s*(?:current\s+squad|players|squad)\s*==+([\s\S]*?)(?:\n\s*==[^=]|\Z)", wikitext, re.I)
    return match.group(1) if match else wikitext


def _template_fields(template_body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    positional: list[str] = []
    for raw_part in _split_template_parts(template_body):
        part = raw_part.strip()
        if not part:
            continue
        if "=" not in part:
            positional.append(part)
            continue
        key, value = part.split("=", 1)
        fields[key.strip().lower()] = value.strip()
    if positional and "pos" not in fields:
        fields["pos"] = positional[0]
    return fields


def _split_template_parts(template_body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    brace_depth = 0
    link_depth = 0
    index = 0
    while index < len(template_body):
        pair = template_body[index : index + 2]
        if pair == "{{":
            brace_depth += 1
            current.append(pair)
            index += 2
            continue
        if pair == "}}" and brace_depth:
            brace_depth -= 1
            current.append(pair)
            index += 2
            continue
        if pair == "[[":
            link_depth += 1
            current.append(pair)
            index += 2
            continue
        if pair == "]]" and link_depth:
            link_depth -= 1
            current.append(pair)
            index += 2
            continue
        char = template_body[index]
        if char == "|" and brace_depth == 0 and link_depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return parts


def _clean_wiki_value(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\{\{[^{}]*\}\}", " ", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    text = text.replace("&nbsp;", " ")
    return _clean_text(text.strip(" '\""))


def _int_field(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", value.replace(",", ""))
    return int(match.group(0)) if match else None


def _dedupe_squad_players(players: list[SquadPlayer]) -> list[SquadPlayer]:
    seen: set[str] = set()
    deduped: list[SquadPlayer] = []
    for player in players:
        key = player.name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(player)
    return deduped


def _known_players_by_team(squad_rosters: dict[str, list[SquadPlayer]]) -> dict[str, list[str]]:
    known: dict[str, list[str]] = {}
    for team, players in squad_rosters.items():
        aliases = [player.name for player in players if player.name]
        aliases.extend(STAR_PLAYERS.get(team, []))
        known[team] = _dedupe_aliases(aliases)
    return known


def _dedupe_aliases(values: list[str]) -> list[str]:
    seen: set[str] = set()
    aliases: list[str] = []
    for value in values:
        alias = _clean_text(value).lower()
        alias_key = _fold_text(alias)
        if len(alias_key) < 3 or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)
        parts = [part for part in re.split(r"\s+", alias) if len(part) >= 4]
        part_key = _fold_text(parts[-1]) if parts else ""
        if len(parts) >= 2 and part_key not in seen:
            seen.add(part_key)
            aliases.append(parts[-1])
    return aliases


def fetch_news_query(
    *,
    cache_key: str,
    query: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    )
    cache_file = cache_dir / f"google_news_{cache_key}.xml"
    text = _cached_text(cache_file, url, refresh=refresh, timeout_seconds=timeout_seconds)
    root = ET.fromstring(text)
    items: list[NewsItem] = []
    for item in root.findall(".//item")[:8]:
        source = item.find("source")
        items.append(
            NewsItem(
                title=_clean_text(item.findtext("title", default="")),
                source=_clean_text(source.text if source is not None and source.text else "Google News"),
                link=item.findtext("link", default=url),
                published=item.findtext("pubDate", default=""),
            )
        )
    return items


def fetch_team_scout_news(
    team: str,
    *,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
    known_players: dict[str, list[str]] | None = None,
) -> dict[str, list[NewsItem]]:
    """Fetch small team-targeted bundles for form, players, and squad depth."""
    queries = {
        "recent_form": (
            f"{team} national football team results fixtures last five matches 2025 2026 "
            "-prediction -predictions -odds -picks -betting"
        ),
        "player_form": (
            f"{team} football key players 2025-26 season goals assists minutes club form stats "
            "ratings FBref SofaScore Transfermarkt -prediction -odds -betting"
        ),
        "squad_depth": f"{team} World Cup squad depth predicted lineup injuries key players 2026",
    }
    bundles: dict[str, list[NewsItem]] = {}
    for topic, query in queries.items():
        items = _fetch_ddgs_query(
            query=query,
            cache_file=cache_dir / f"ddgs_team_{topic}_{_slug(team)}.json",
            refresh=refresh,
            timeout_seconds=timeout_seconds,
            max_results=5,
        )
        if topic == "player_form":
            for player in STAR_PLAYERS.get(team, [])[:3]:
                items.extend(
                    _fetch_ddgs_query(
                        query=(
                            f"{player} 2025-26 season goals assists minutes appearances club form "
                            "ratings FBref SofaScore Transfermarkt"
                        ),
                        cache_file=cache_dir / f"ddgs_player_form_{_slug(team)}_{_slug(player)}.json",
                        refresh=refresh,
                        timeout_seconds=timeout_seconds,
                        max_results=2,
                    )
                )
        try:
            news_items = fetch_news_query(
                cache_key=f"team_{topic}_{_slug(team)}",
                query=query.replace(" -prediction -predictions -odds -picks -betting", ""),
                cache_dir=cache_dir,
                refresh=refresh,
                timeout_seconds=timeout_seconds,
            )
        except Exception:
            news_items = []
        items = _dedupe_items(items + news_items)
        filtered = _filter_topic_items(items, topic, team=team, known_players=known_players)
        if topic in {"recent_form", "player_form"}:
            bundles[topic] = filtered[:5]
        else:
            bundles[topic] = filtered[:5]
    return bundles


def fetch_official_squad_news(
    team: str,
    *,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    """Fetch official-ish squad, player, and federation sources for one team."""
    queries = [
        f"{team} national football team official squad FIFA World Cup 2026",
        f"{team} football federation squad players injuries official",
        f"site:fifa.com {team} national football team squad players",
    ]
    items: list[NewsItem] = []
    for index, query in enumerate(queries):
        items.extend(
            _fetch_ddgs_query(
                query=query,
                cache_file=cache_dir / f"ddgs_official_squad_{index}_{_slug(team)}.json",
                refresh=refresh,
                timeout_seconds=timeout_seconds,
                max_results=4,
            )
        )
        try:
            items.extend(
                fetch_news_query(
                    cache_key=f"official_squad_{index}_{_slug(team)}",
                    query=query.replace("site:fifa.com ", ""),
                    cache_dir=cache_dir,
                    refresh=refresh,
                    timeout_seconds=timeout_seconds,
                )[:2]
            )
        except Exception:
            continue
    return _filter_official_squad_items(_dedupe_items(items), team=team)[:8]


def fetch_match_history_news(
    *,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    """Fetch head-to-head and recent historical match context for both sides."""
    queries = [
        (
            f"{home_team} {away_team} head to head results previous meetings football "
            "World Cup history last matches"
        ),
        f"{home_team} national football team last 10 matches results form 2025 2026",
        f"{away_team} national football team last 10 matches results form 2025 2026",
    ]
    items: list[NewsItem] = []
    for index, query in enumerate(queries):
        items.extend(
            _fetch_ddgs_query(
                query=query,
                cache_file=cache_dir
                / f"ddgs_match_history_{index}_{_slug(home_team)}_{_slug(away_team)}.json",
                refresh=refresh,
                timeout_seconds=timeout_seconds,
                max_results=5,
            )
        )
        try:
            items.extend(
                fetch_news_query(
                    cache_key=f"match_history_{index}_{_slug(home_team)}_{_slug(away_team)}",
                    query=query,
                    cache_dir=cache_dir,
                    refresh=refresh,
                    timeout_seconds=timeout_seconds,
                )[:3]
            )
        except Exception:
            continue
    return _filter_match_history_items(_dedupe_items(items), home_team=home_team, away_team=away_team)[:10]


def fetch_tactical_matchup_news(
    *,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    """Fetch tactical, formation, set-piece, and style-of-play matchup context."""
    queries = [
        f"{home_team} {away_team} tactical preview formations pressing set pieces football",
        f"{home_team} football tactics formation pressing transition set pieces 2026",
        f"{away_team} football tactics formation pressing transition set pieces 2026",
        f"{home_team} {away_team} predicted lineup tactical analysis key matchups World Cup",
    ]
    items: list[NewsItem] = []
    for index, query in enumerate(queries):
        items.extend(
            _fetch_ddgs_query(
                query=query,
                cache_file=cache_dir / f"ddgs_tactical_{index}_{_slug(home_team)}_{_slug(away_team)}.json",
                refresh=refresh,
                timeout_seconds=timeout_seconds,
                max_results=5,
            )
        )
        try:
            items.extend(
                fetch_news_query(
                    cache_key=f"tactical_{index}_{_slug(home_team)}_{_slug(away_team)}",
                    query=query,
                    cache_dir=cache_dir,
                    refresh=refresh,
                    timeout_seconds=timeout_seconds,
                )[:2]
            )
        except Exception:
            continue
    return _filter_tactical_items(_dedupe_items(items), home_team=home_team, away_team=away_team)[:10]


def _team_items(items_by_team: dict[str, list[NewsItem]], *, max_per_team: int) -> list[NewsItem]:
    items: list[NewsItem] = []
    for items_for_team in items_by_team.values():
        items.extend(items_for_team[:max_per_team])
    return _dedupe_items(items)


def _team_scout_items(
    team_scout_news: dict[str, dict[str, list[NewsItem]]],
    topic: str,
    *,
    max_per_team: int,
) -> list[NewsItem]:
    items: list[NewsItem] = []
    for bundles in team_scout_news.values():
        items.extend(bundles.get(topic, [])[:max_per_team])
    return _dedupe_items(items)


def _tactical_items_from_team_scouts(
    team_scout_news: dict[str, dict[str, list[NewsItem]]],
    *,
    home_team: str,
    away_team: str,
) -> list[NewsItem]:
    candidates = _team_scout_items(team_scout_news, "squad_depth", max_per_team=4)
    tactical_items: list[NewsItem] = []
    markers = (
        "lineup",
        "line-up",
        "predicted xi",
        "starting xi",
        "formation",
        "tactic",
        "tactics",
        "key players",
    )
    for item in candidates:
        text = f"{item.title} {item.source} {item.link}".lower()
        if _is_noisy_public_item(text) or _is_weak_scouting_source_text(text):
            continue
        if not (home_team.lower() in text or away_team.lower() in text):
            continue
        if any(marker in text for marker in markers):
            tactical_items.append(item)
    return _dedupe_items(tactical_items)


def _filter_topic_items(
    items: list[NewsItem],
    topic: str,
    *,
    team: str,
    known_players: dict[str, list[str]] | None = None,
) -> list[NewsItem]:
    filtered: list[NewsItem] = []
    for item in items:
        text = f"{item.title} {item.source} {item.link}".lower()
        if _is_noisy_public_item(text):
            continue
        if topic == "recent_form":
            if any(noisy in text for noisy in ("prediction", "predictions", "odds", "pick", "betting", "tips")):
                continue
            if not _item_mentions_team_or_player(text, team, known_players=known_players):
                continue
            if not any(
                marker in text
                for marker in (
                    "result",
                    "results",
                    "fixture",
                    "fixtures",
                    "flashscore",
                    "recent form",
                    "last five",
                    "last matches",
                    "matches",
                    "schedule",
                )
            ):
                continue
        elif topic == "player_form":
            if any(noisy in text for noisy in ("prediction", "odds", "pick", "betting", "tips")):
                continue
            if not _item_mentions_team_or_player(text, team, known_players=known_players):
                continue
            if not any(
                marker in text
                for marker in (
                    "goals",
                    "assists",
                    "season",
                    "stats",
                    "form",
                    "club",
                    "minutes",
                    "scored",
                    "player",
                )
            ):
                continue
        elif topic == "squad_depth":
            if _is_weak_scouting_source_text(text):
                continue
            if not _item_mentions_team_or_player(text, team, known_players=known_players):
                continue
            if not any(
                marker in text
                for marker in (
                    "squad",
                    "roster",
                    "lineup",
                    "line-up",
                    "starting xi",
                    "predicted xi",
                    "injury",
                    "injuries",
                    "availability",
                    "called up",
                    "call-up",
                    "players",
                    "fifa",
                    "federation",
                )
            ):
                continue
        filtered.append(item)
    return filtered


def _filter_official_squad_items(items: list[NewsItem], *, team: str) -> list[NewsItem]:
    filtered: list[NewsItem] = []
    for item in items:
        text = f"{item.title} {item.source} {item.link}".lower()
        if _is_noisy_public_item(text):
            continue
        if not _item_mentions_team_or_player(text, team):
            continue
        if _is_weak_scouting_source_text(text):
            continue
        if not any(
            marker in text
            for marker in (
                "official",
                "fifa",
                "federation",
                "squad",
                "roster",
                "players",
                "called up",
                "call-up",
                "injury",
                "injuries",
                "lineup",
                "line-up",
            )
        ):
            continue
        filtered.append(item)
    return filtered


def _filter_match_history_items(items: list[NewsItem], *, home_team: str, away_team: str) -> list[NewsItem]:
    filtered: list[NewsItem] = []
    for item in items:
        text = f"{item.title} {item.source} {item.link}".lower()
        if _is_noisy_public_item(text):
            continue
        if home_team.lower() not in text and away_team.lower() not in text:
            continue
        if not any(
            marker in text
            for marker in (
                "head to head",
                "head-to-head",
                "h2h",
                "previous meeting",
                "previous meetings",
                "last 10",
                "last five",
                "last matches",
                "results",
                "fixtures",
                "flashscore",
                "soccerway",
                "11v11",
                "worldfootball.net",
            )
        ):
            continue
        if _is_weak_scouting_source_text(text):
            continue
        filtered.append(item)
    return filtered


def _filter_tactical_items(items: list[NewsItem], *, home_team: str, away_team: str) -> list[NewsItem]:
    filtered: list[NewsItem] = []
    for item in items:
        text = f"{item.title} {item.source} {item.link}".lower()
        if _is_noisy_public_item(text):
            continue
        if home_team.lower() not in text and away_team.lower() not in text:
            continue
        if _is_weak_scouting_source_text(text):
            continue
        if not any(
            marker in text
            for marker in (
                "tactical",
                "tactics",
                "formation",
                "lineup",
                "line-up",
                "predicted xi",
                "pressing",
                "counter",
                "transition",
                "set piece",
                "set-piece",
                "analysis",
                "key matchups",
                "preview",
            )
        ):
            continue
        filtered.append(item)
    return filtered


def _is_weak_scouting_source_text(lowered_text: str) -> bool:
    weak_markers = (
        "boostmatch",
        "wc26lineups",
        "score prediction",
        "predictions",
        "best bets",
        "betting",
        "tips",
        "picks",
        "odds",
    )
    return any(marker in lowered_text for marker in weak_markers)


def _is_noisy_public_item(lowered_text: str) -> bool:
    noisy_sources = (
        "tiktok",
        "youtube",
        "reddit",
        "pinterest",
        "facebook",
        "instagram",
    )
    return any(source in lowered_text for source in noisy_sources)


def _item_mentions_team_or_player(
    lowered_text: str,
    team: str,
    *,
    known_players: dict[str, list[str]] | None = None,
) -> bool:
    if team.lower() in lowered_text:
        return True
    return any(_alias_in_text(player, lowered_text) for player in _player_aliases_for_team(team, known_players=known_players))


def fetch_x_availability(
    *,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    """Fetch X-like availability signals through a configurable external endpoint.

    ScrapeCreators can be wired here by setting:
    - SCRAPECREATORS_API_KEY
    - SCRAPECREATORS_X_SEARCH_URL

    If the URL contains "{query}", it is called as a templated GET URL. Otherwise
    it is called as POST JSON {"query": "..."}.
    """
    query = f'{home_team} {away_team} World Cup injury squad lineup Neymar'
    endpoint = os.environ.get("SCRAPECREATORS_X_SEARCH_URL", "").strip() or os.environ.get("COLONY_X_SEARCH_URL", "").strip()
    api_key = os.environ.get("SCRAPECREATORS_API_KEY", "").strip() or os.environ.get("COLONY_X_API_KEY", "").strip()
    if not endpoint or not api_key:
        return []

    cache_file = cache_dir / f"x_search_{_slug(home_team)}_{_slug(away_team)}.json"
    try:
        payload = _cached_scrapecreators_search(
            cache_file,
            endpoint=endpoint,
            api_key=api_key,
            query=query,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return []
    return _news_items_from_any_payload(payload, default_source="X")


def fetch_camel_research(
    *,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    """Fetch deeper research items.

    The native CAMEL integration is intentionally optional because it adds a
    heavy dependency. Until the package is installed and configured, this uses
    the same normalized output shape with focused web/news research queries.
    """
    native_mode = os.environ.get("COLONY_CAMEL_USE_NATIVE", "").strip() == "1"
    if native_mode and _camel_available():
        native_items = _fetch_native_camel_research(
            home_team=home_team,
            away_team=away_team,
            timeout_seconds=timeout_seconds,
        )
        if native_items:
            return native_items

    ddgs_items = _fetch_ddgs_research(
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_dir,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
    )
    if ddgs_items:
        return ddgs_items

    queries = [
        f"{home_team} {away_team} predicted lineups World Cup injuries",
        f"{home_team} {away_team} tactical preview World Cup",
        f"{home_team} recent form key players season form World Cup",
        f"{away_team} recent form key players season form World Cup",
    ]
    items: list[NewsItem] = []
    for index, query in enumerate(queries):
        try:
            items.extend(
                fetch_news_query(
                    cache_key=f"camel_research_{index}_{_slug(home_team)}_{_slug(away_team)}",
                    query=query,
                    cache_dir=cache_dir,
                    refresh=refresh,
                    timeout_seconds=timeout_seconds,
                )[:3]
            )
        except Exception:
            continue
    return _dedupe_items(items)[:8]


def extract_evidence_claims(
    *,
    items: list[NewsItem],
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
    max_articles: int,
    known_players: dict[str, list[str]] | None = None,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    for item in items[:max_articles]:
        article_text = _fetch_article_text(
            item.link,
            cache_dir=cache_dir,
            refresh=refresh,
            timeout_seconds=timeout_seconds,
        )
        source_texts = [item.title]
        if article_text:
            source_texts.append(article_text)
        for source_text in source_texts:
            claims.extend(
                _extract_claims_from_text(
                    text=source_text,
                    source_title=item.title,
                    source_url=item.link,
                    source_published=item.published,
                    home_team=home_team,
                    away_team=away_team,
                    known_players=known_players,
                )
            )
    return _dedupe_claims(claims)[:12]


def _topic_claims_from_items(
    *,
    items: list[NewsItem],
    claim_type: str,
    home_team: str,
    away_team: str,
    confidence: float,
    known_players: dict[str, list[str]] | None = None,
) -> list[EvidenceClaim]:
    """Create structured claims from already-filtered source titles/snippets."""
    claims: list[EvidenceClaim] = []
    for item in items[:8]:
        text = _clean_text(item.title)
        if not text:
            continue
        subject, team, player = _claim_subject(
            text,
            home_team=home_team,
            away_team=away_team,
            known_players=known_players,
        )
        if team is None and player is None:
            continue
        claims.append(
            EvidenceClaim(
                claim_type=claim_type,
                subject=subject,
                claim=_shorten(text, limit=260),
                team=team,
                player=player,
                impact=_claim_impact(claim_type, team=team, home_team=home_team, away_team=away_team),
                confidence=round(
                    max(
                        min(
                            confidence
                            + _source_quality_adjustment(source_title=item.source, source_url=item.link),
                            0.8,
                        ),
                        0.12,
                    ),
                    2,
                ),
                source_title=item.title,
                source_url=item.link,
                **_source_metadata(
                    source_title=item.title,
                    source_url=item.link,
                    source_published=item.published,
                    extraction_method="filtered_title",
                ),
                metrics=_claim_metrics_for_match(
                    claim_type,
                    text,
                    home_team=home_team,
                    away_team=away_team,
                ),
            )
        )
    return _dedupe_claims(claims)


def _claim_citations(claims: list[EvidenceClaim]) -> list[str]:
    citations = [claim.source_url for claim in claims if claim.source_url]
    return list(dict.fromkeys(citations))[:8]


def _claim_titles(claims: list[EvidenceClaim], *, count: int = 4) -> str:
    titles = [claim.source_title for claim in claims if claim.source_title]
    return "; ".join(list(dict.fromkeys(titles))[:count])


def _team_profile_claims(home_profile: TeamProfile, away_profile: TeamProfile) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    for profile, impact in ((home_profile, "context_home"), (away_profile, "context_away")):
        extract = _clean_text(profile.extract)
        if not extract:
            continue
        confidence = 0.46 + _source_quality_adjustment(source_title=profile.title, source_url=profile.page_url)
        claims.append(
            EvidenceClaim(
                claim_type="team_profile",
                subject=profile.team,
                claim=_shorten(extract, limit=300),
                team=profile.team,
                player=None,
                impact=impact,
                confidence=round(max(min(confidence, 0.72), 0.18), 2),
                source_title=profile.title,
                source_url=profile.page_url,
                **_source_metadata(
                    source_title=profile.title,
                    source_url=profile.page_url,
                    extraction_method="wikipedia_summary",
                ),
            )
        )
        history_metrics = _claim_metrics("team_history", extract)
        if history_metrics:
            claims.append(
                EvidenceClaim(
                    claim_type="team_history",
                    subject=profile.team,
                    claim=_shorten(extract, limit=300),
                    team=profile.team,
                    player=None,
                    impact=impact,
                    confidence=round(max(min(confidence + 0.04, 0.76), 0.18), 2),
                    source_title=profile.title,
                    source_url=profile.page_url,
                    **_source_metadata(
                        source_title=profile.title,
                        source_url=profile.page_url,
                        extraction_method="wikipedia_history_summary",
                    ),
                    metrics=history_metrics,
                )
            )
    return _dedupe_claims(claims)


def _squad_roster_claims(
    squad_rosters: dict[str, list[SquadPlayer]],
    *,
    home_team: str,
    away_team: str,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    for team, impact in ((home_team, "context_home"), (away_team, "context_away")):
        for player in squad_rosters.get(team, [])[:18]:
            metrics: dict[str, Any] = {"roster_signal": "current_squad"}
            if player.position:
                metrics["position"] = player.position
            if player.club:
                metrics["club"] = player.club
            if player.caps is not None:
                metrics["international_caps"] = player.caps
            if player.goals is not None:
                metrics["international_goals"] = player.goals
            descriptors = [player.position, player.club]
            if player.caps is not None:
                descriptors.append(f"{player.caps} caps")
            if player.goals is not None:
                descriptors.append(f"{player.goals} international goals")
            detail = ", ".join(part for part in descriptors if part)
            claim_text = f"{player.name} is listed in the current {team} squad"
            if detail:
                claim_text = f"{claim_text}: {detail}"
            claims.append(
                EvidenceClaim(
                    claim_type="squad_roster",
                    subject=player.name,
                    claim=claim_text,
                    team=team,
                    player=player.name,
                    impact=impact,
                    confidence=0.52,
                    source_title=player.source_title,
                    source_url=player.source_url,
                    **_source_metadata(
                        source_title=player.source_title,
                        source_url=player.source_url,
                        extraction_method="wikipedia_current_squad_template",
                    ),
                    metrics=metrics,
                )
            )
    return _dedupe_claims(claims)


def public_probabilities(
    *,
    home_team: str,
    away_team: str,
    home_profile: TeamProfile,
    away_profile: TeamProfile,
    match_news: list[NewsItem],
    recent_results_news: dict[str, list[NewsItem]],
    team_scout_news: dict[str, dict[str, list[NewsItem]]],
    availability_news: list[NewsItem],
    x_items: list[NewsItem],
    camel_items: list[NewsItem],
    availability_claims: list[EvidenceClaim],
    x_claims: list[EvidenceClaim],
    camel_claims: list[EvidenceClaim],
    team_form_claims: list[EvidenceClaim],
    player_form_claims: list[EvidenceClaim],
    squad_depth_claims: list[EvidenceClaim],
    match_history_items: list[NewsItem],
    match_history_claims: list[EvidenceClaim],
    tactical_items: list[NewsItem],
    tactical_claims: list[EvidenceClaim],
    official_squad_claims: list[EvidenceClaim],
    known_players: dict[str, list[str]] | None = None,
) -> tuple[float, float, float, float]:
    market, stats, odds, news = synthetic_probabilities(home_team, away_team)
    profile_shift = _profile_trophy_signal(home_profile.extract) - _profile_trophy_signal(away_profile.extract)
    stats = _clamp(stats + profile_shift * 0.018)

    home_form = _form_signal(recent_results_news.get(home_team, []), home_team)
    away_form = _form_signal(recent_results_news.get(away_team, []), away_team)
    home_form += _form_signal(team_scout_news.get(home_team, {}).get("recent_form", []), home_team)
    away_form += _form_signal(team_scout_news.get(away_team, {}).get("recent_form", []), away_team)
    home_form += _form_signal(match_history_items, home_team)
    away_form += _form_signal(match_history_items, away_team)
    stats = _clamp(stats + (home_form - away_form) * 0.006)

    home_mentions = _mention_count(match_news, home_team)
    away_mentions = _mention_count(match_news, away_team)
    if home_mentions or away_mentions:
        news += (home_mentions - away_mentions) * 0.004

    home_availability_hits = _availability_hits(availability_news, home_team, known_players=known_players)
    away_availability_hits = _availability_hits(availability_news, away_team, known_players=known_players)
    news += (away_availability_hits - home_availability_hits) * 0.006

    home_x_hits = _availability_hits(x_items, home_team, known_players=known_players)
    away_x_hits = _availability_hits(x_items, away_team, known_players=known_players)
    news += (away_x_hits - home_x_hits) * 0.008

    home_research_mentions = _mention_count(camel_items, home_team)
    away_research_mentions = _mention_count(camel_items, away_team)
    home_tactical_mentions = _mention_count(tactical_items, home_team)
    away_tactical_mentions = _mention_count(tactical_items, away_team)
    news += (home_research_mentions - away_research_mentions) * 0.002
    news += (home_tactical_mentions - away_tactical_mentions) * 0.0015
    news += _claim_signal(
        claims=(
            availability_claims
            + x_claims
            + camel_claims
            + team_form_claims
            + player_form_claims
            + squad_depth_claims
            + match_history_claims
            + tactical_claims
            + official_squad_claims
        ),
        home_team=home_team,
        away_team=away_team,
    )

    market = _clamp((market * 0.65) + (stats * 0.2) + (news * 0.15))
    odds = _clamp((market * 0.85) + 0.075)
    return tuple(round(value, 4) for value in (market, stats, odds, _clamp(news)))  # type: ignore[return-value]


def public_findings_for_match(
    *,
    round_id: str,
    home_team: str,
    away_team: str,
    market: float,
    stats: float,
    odds: float,
    news: float,
    home_profile: TeamProfile,
    away_profile: TeamProfile,
    match_news: list[NewsItem],
    recent_results_news: dict[str, list[NewsItem]],
    team_scout_news: dict[str, dict[str, list[NewsItem]]],
    availability_news: list[NewsItem],
    x_items: list[NewsItem],
    camel_items: list[NewsItem],
    availability_claims: list[EvidenceClaim],
    x_claims: list[EvidenceClaim],
    camel_claims: list[EvidenceClaim],
    team_form_claims: list[EvidenceClaim],
    player_form_claims: list[EvidenceClaim],
    squad_depth_claims: list[EvidenceClaim],
    match_history_items: list[NewsItem],
    match_history_claims: list[EvidenceClaim],
    tactical_items: list[NewsItem],
    official_squad_items: dict[str, list[NewsItem]],
    squad_rosters: dict[str, list[SquadPlayer]],
    tactical_claims: list[EvidenceClaim],
    official_squad_claims: list[EvidenceClaim],
    squad_roster_claims: list[EvidenceClaim],
    include_x: bool,
    include_camel: bool,
) -> list[Finding]:
    match_titles = _titles(match_news)
    match_citations = _citations(match_news)
    recent_titles = (
        f"{home_team}: {_titles(recent_results_news.get(home_team, []), count=2)} "
        f"{away_team}: {_titles(recent_results_news.get(away_team, []), count=2)}"
    )
    recent_citations = _citations(
        recent_results_news.get(home_team, [])[:2] + recent_results_news.get(away_team, [])[:2]
    )
    form_items = _team_scout_items(team_scout_news, "recent_form", max_per_team=3)
    player_form_items = _team_scout_items(team_scout_news, "player_form", max_per_team=3)
    squad_depth_items = _team_scout_items(team_scout_news, "squad_depth", max_per_team=3)
    form_titles = (
        f"{home_team}: {_titles(team_scout_news.get(home_team, {}).get('recent_form', []), count=2)} "
        f"{away_team}: {_titles(team_scout_news.get(away_team, {}).get('recent_form', []), count=2)}"
    )
    player_form_titles = (
        f"{home_team}: {_titles(team_scout_news.get(home_team, {}).get('player_form', []), count=2)} "
        f"{away_team}: {_titles(team_scout_news.get(away_team, {}).get('player_form', []), count=2)}"
    )
    squad_depth_titles = (
        f"{home_team}: {_titles(team_scout_news.get(home_team, {}).get('squad_depth', []), count=2)} "
        f"{away_team}: {_titles(team_scout_news.get(away_team, {}).get('squad_depth', []), count=2)}"
    )
    match_history_titles = (
        _titles(match_history_items, count=4) if match_history_items else _claim_titles(match_history_claims, count=4)
    )
    match_history_citations = _claim_citations(match_history_claims) or _citations(match_history_items)
    tactical_titles = _titles(tactical_items, count=4)
    tactical_citations = _citations(tactical_items)
    official_items = _team_items(official_squad_items, max_per_team=3)
    official_titles = (
        f"{home_team}: {_titles(official_squad_items.get(home_team, []), count=2)} "
        f"{away_team}: {_titles(official_squad_items.get(away_team, []), count=2)}"
    )
    roster_players = squad_rosters.get(home_team, []) + squad_rosters.get(away_team, [])
    roster_titles = (
        f"{home_team}: {_squad_roster_titles(squad_rosters.get(home_team, []), count=4)} "
        f"{away_team}: {_squad_roster_titles(squad_rosters.get(away_team, []), count=4)}"
    )
    roster_citations = list(dict.fromkeys(player.source_url for player in roster_players if player.source_url))[:4]
    availability_titles = _titles(availability_news, count=4)
    availability_citations = _citations(availability_news)
    x_titles = _titles(x_items, count=4)
    x_citations = _citations(x_items)
    camel_titles = _titles(camel_items, count=4)
    camel_citations = _citations(camel_items)
    profile_claims = _team_profile_claims(home_profile, away_profile)

    findings = [
        _finding(
            round_id=round_id,
            key="team_profiles_recent_results",
            scout_name="recent_results_scout",
            access_level="public",
            source_type="stats",
            finding_name="recent_results_and_profile_read",
            home_probability=stats,
            market=market,
            confidence=0.58,
            summary=(
                f"Fetched public team profiles and Google News result headlines for recent form. "
                f"{home_team}: {_shorten(home_profile.extract, limit=140)} "
                f"{away_team}: {_shorten(away_profile.extract, limit=140)} "
                f"Recent-result headlines: {recent_titles}"
            ),
            citations=[home_profile.page_url, away_profile.page_url] + recent_citations,
            evidence_claims=[claim.to_dict() for claim in profile_claims],
        ),
        _finding(
            round_id=round_id,
            key="squad_availability",
            scout_name="squad_availability_scout",
            access_level="public",
            source_type="lineup",
            finding_name="injury_and_player_availability_read",
            home_probability=news,
            market=market,
            confidence=0.5 if availability_news else 0.18,
            summary=(
                "Fetched Google News RSS for squad, injury, and player availability signals. "
                f"Top items: {availability_titles}"
            ),
            citations=availability_citations,
            evidence_claims=[claim.to_dict() for claim in availability_claims],
        ),
        _finding(
            round_id=round_id,
            key="team_form",
            scout_name="team_form_scout",
            access_level="public",
            source_type="stats",
            finding_name="recent_match_form_read",
            home_probability=stats,
            market=market,
            confidence=0.55 if form_items else 0.16,
            summary=(
                "Fetched team-targeted recent-match and form searches for both sides. "
                f"Top items: {form_titles}"
            ),
            citations=_citations(form_items),
            evidence_claims=[claim.to_dict() for claim in team_form_claims],
        ),
        _finding(
            round_id=round_id,
            key="player_form",
            scout_name="player_form_scout",
            access_level="public",
            source_type="stats",
            finding_name="key_player_season_form_read",
            home_probability=stats,
            market=market,
            confidence=0.5 if player_form_items else 0.14,
            summary=(
                "Fetched key-player season-form searches: club form, goals, assists, minutes, and role signals. "
                f"Top items: {player_form_titles}"
            ),
            citations=_citations(player_form_items),
            evidence_claims=[claim.to_dict() for claim in player_form_claims],
        ),
        _finding(
            round_id=round_id,
            key="squad_depth",
            scout_name="squad_depth_scout",
            access_level="public",
            source_type="lineup",
            finding_name="squad_depth_and_predicted_xi_read",
            home_probability=news,
            market=market,
            confidence=0.5 if squad_depth_items else 0.14,
            summary=(
                "Fetched team-targeted squad-depth searches: predicted XI, key players, absences, and role depth. "
                f"Top items: {squad_depth_titles}"
            ),
            citations=_citations(squad_depth_items),
            evidence_claims=[claim.to_dict() for claim in squad_depth_claims],
        ),
        _finding(
            round_id=round_id,
            key="official_squad_sources",
            scout_name="official_squad_scout",
            access_level="public",
            source_type="lineup",
            finding_name="official_squad_and_roster_read",
            home_probability=news,
            market=market,
            confidence=0.56 if official_items else 0.12,
            summary=(
                "Fetched official-ish squad, roster, federation, FIFA, call-up, and availability sources. "
                f"Top items: {official_titles}"
            ),
            citations=_citations(official_items),
            evidence_claims=[claim.to_dict() for claim in official_squad_claims],
        ),
        _finding(
            round_id=round_id,
            key="squad_roster",
            scout_name="squad_roster_scout",
            access_level="public",
            source_type="lineup",
            finding_name="structured_current_squad_roster_read",
            home_probability=None,
            market=market,
            confidence=0.52 if roster_players else 0.0,
            summary=(
                "Fetched structured current-squad roster templates for both teams. "
                f"Top players: {roster_titles}"
            ),
            citations=roster_citations,
            evidence_claims=[claim.to_dict() for claim in squad_roster_claims],
        ),
        _finding(
            round_id=round_id,
            key="match_history",
            scout_name="match_history_scout",
            access_level="public",
            source_type="stats",
            finding_name="head_to_head_and_match_history_read",
            home_probability=stats,
            market=market,
            confidence=0.52 if match_history_items or match_history_claims else 0.14,
            summary=(
                "Fetched head-to-head, previous meetings, recent match-history, and result archive sources. "
                f"Top items: {match_history_titles}"
            ),
            citations=match_history_citations,
            evidence_claims=[claim.to_dict() for claim in match_history_claims],
        ),
        _finding(
            round_id=round_id,
            key="tactical_matchup",
            scout_name="tactical_matchup_scout",
            access_level="public",
            source_type="stats",
            finding_name="tactical_style_and_key_matchups_read",
            home_probability=stats,
            market=market,
            confidence=0.48 if tactical_items else 0.12,
            summary=(
                "Fetched tactical, lineup, key-player, formation, pressing, transition, set-piece, and matchup sources. "
                f"Top items: {tactical_titles}"
            ),
            citations=tactical_citations,
            evidence_claims=[claim.to_dict() for claim in tactical_claims],
        ),
    ]
    findings = _drop_empty_specialized_findings(
        findings,
        {
            "official_squad_sources": bool(official_items or official_squad_claims),
            "squad_roster": bool(roster_players or squad_roster_claims),
            "match_history": bool(match_history_items or match_history_claims),
            "tactical_matchup": bool(tactical_items or tactical_claims),
        },
    )

    if include_x and (x_items or x_claims):
        findings.append(
            _finding(
                round_id=round_id,
                key="x_availability",
                scout_name="x_availability_scout",
                access_level="shared",
                source_type="social",
                finding_name="x_injury_and_lineup_read",
                home_probability=news if x_items else None,
                market=market,
                confidence=0.46 if x_items else 0.05,
                summary=(
                    "Fetched X/social availability signals through the configured external endpoint. "
                    f"Top items: {x_titles}"
                ),
                citations=x_citations,
                cost=0.0,
                evidence_claims=[claim.to_dict() for claim in x_claims],
            )
        )

    if include_camel and (camel_items or camel_claims):
        native_requested = os.environ.get("COLONY_CAMEL_USE_NATIVE", "").strip() == "1"
        native_returned_items = any(item.source.startswith("CAMEL:") for item in camel_items)
        if native_requested and native_returned_items:
            native_status = "native CAMEL ChatAgent + SearchToolkit returned research items"
        elif native_requested and _camel_available():
            native_status = "native CAMEL was requested but returned no usable structured items; direct DDGS/web collector produced the usable items"
        elif _camel_available():
            native_status = "CAMEL package detected, but native mode is disabled; direct DDGS/web collector produced the usable items"
        else:
            native_status = "CAMEL package not installed; direct DDGS/web collector produced the usable items"
        findings.append(
            _finding(
                round_id=round_id,
                key="camel_research",
                scout_name="camel_research_scout",
                access_level="shared",
                source_type="retrieval",
                finding_name="deep_research_read",
                home_probability=news if camel_items else None,
                market=market,
                confidence=0.5 if camel_items else 0.08,
                summary=(
                    f"{native_status}. Research focus: predicted lineups, key players, injuries, and tactical preview. "
                    f"Top items: {camel_titles}"
                ),
                citations=camel_citations,
                cost=0.0,
                evidence_claims=[claim.to_dict() for claim in camel_claims],
            )
        )

    findings.extend(
        [
            _finding(
                round_id=round_id,
                key="google_news",
                scout_name="google_news_scout",
                access_level="public",
                source_type="news",
                finding_name="news_visibility_read",
                home_probability=news,
                market=market,
                confidence=0.48 if match_news else 0.2,
                summary=f"Fetched Google News RSS titles for the match query. Top items: {match_titles}",
                citations=match_citations,
                evidence_claims=[
                    claim.to_dict()
                    for claim in _extract_claims_from_text(
                        text=match_titles,
                        source_title="Google News match query",
                        source_url="https://news.google.com/",
                        home_team=home_team,
                        away_team=away_team,
                    )
                ],
            ),
        ]
    )
    return [finding for finding in findings if finding.evidence_claims]


def _cached_json(path: Path, url: str, *, refresh: bool, timeout_seconds: int) -> dict[str, Any]:
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    text = _fetch_text(url, timeout_seconds=timeout_seconds)
    path.write_text(text, encoding="utf-8")
    return json.loads(text)


def _cached_text(path: Path, url: str, *, refresh: bool, timeout_seconds: int) -> str:
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8")
    text = _fetch_text(url, timeout_seconds=timeout_seconds)
    path.write_text(text, encoding="utf-8")
    return text


def _cached_scrapecreators_search(
    path: Path,
    *,
    endpoint: str,
    api_key: str,
    query: str,
    refresh: bool,
    timeout_seconds: int,
) -> Any:
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
    }
    if "{query}" in endpoint:
        url = endpoint.replace("{query}", urllib.parse.quote(query))
        request = urllib.request.Request(url, headers=headers)
    else:
        data = json.dumps({"query": query}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=data,
            headers={**headers, "Content-Type": "application/json"},
            method="POST",
        )

    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload


def _fetch_text(url: str, *, timeout_seconds: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read().decode("utf-8")


def _fetch_article_text(
    url: str,
    *,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> str:
    if not url.startswith("http"):
        return ""
    if "news.google.com/rss/articles" in url:
        return ""

    key = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    cache_file = cache_dir / f"article_{key}.txt"
    if cache_file.exists() and not refresh:
        return cache_file.read_text(encoding="utf-8")
    try:
        html = _fetch_text(url, timeout_seconds=timeout_seconds)
    except Exception:
        return ""
    text = _ArticleTextParser.extract(html)
    if text:
        cache_file.write_text(text, encoding="utf-8")
    return text


class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._capture = False
        self._parts: list[str] = []
        self._current: list[str] = []

    @classmethod
    def extract(cls, html: str) -> str:
        parser = cls()
        parser.feed(html)
        parser.close()
        return _clean_text(" ".join(parser._parts))[:6000]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
        if tag in {"p", "li", "h1", "h2", "h3"}:
            self._capture = True
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
        if tag in {"p", "li", "h1", "h2", "h3"} and self._capture:
            text = _clean_text(" ".join(self._current))
            if len(text) >= 40:
                self._parts.append(text)
            self._capture = False
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._skip or not self._capture:
            return
        self._current.append(data)


def _extract_claims_from_text(
    *,
    text: str,
    source_title: str,
    source_url: str,
    source_published: str = "",
    home_team: str,
    away_team: str,
    known_players: dict[str, list[str]] | None = None,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    for sentence in _sentences(text):
        lowered = sentence.lower()
        claim_type = _claim_type(lowered)
        if claim_type is None:
            continue
        subject, team, player = _claim_subject(
            sentence,
            home_team=home_team,
            away_team=away_team,
            known_players=known_players,
        )
        if team is None and player is None:
            continue
        if claim_type == "injury_availability" and not _has_negative_availability_signal(lowered):
            continue
        if claim_type == "player_form" and not _has_player_form_signal(lowered):
            continue
        claims.append(
            EvidenceClaim(
                claim_type=claim_type,
                subject=subject,
                claim=_shorten(
                    _trim_claim_sentence(sentence, claim_type=claim_type, team=team),
                    limit=260,
                ),
                team=team,
                player=player,
                impact=_claim_impact(claim_type, team=team, home_team=home_team, away_team=away_team),
                confidence=_claim_confidence(claim_type, lowered, source_title=source_title, source_url=source_url),
                source_title=source_title,
                source_url=source_url,
                **_source_metadata(
                    source_title=source_title,
                    source_url=source_url,
                    source_published=source_published,
                    extraction_method="heuristic_sentence",
                ),
                metrics=_claim_metrics_for_match(
                    claim_type,
                    sentence,
                    home_team=home_team,
                    away_team=away_team,
                ),
            )
        )
    return claims


def _trim_claim_sentence(sentence: str, *, claim_type: str, team: str | None) -> str:
    cleaned = sentence.strip()
    if claim_type != "injury_availability" or not team:
        return cleaned
    lowered = cleaned.lower()
    team_key = team.lower()
    for match in re.finditer(rf"\b{re.escape(team_key)}\b", lowered):
        window = lowered[match.start() : match.start() + 140]
        if _has_negative_availability_signal(window):
            return cleaned[match.start() :].strip(" -:|")
    return cleaned


def _sentences(text: str) -> list[str]:
    cleaned = _clean_text(text)
    chunks = re.split(r"(?<=[.!?])\s+|;\s+", cleaned)
    return [chunk.strip(" -") for chunk in chunks if 35 <= len(chunk.strip()) <= 420]


def _claim_type(lowered_sentence: str) -> str | None:
    if _has_negative_availability_signal(lowered_sentence):
        return "injury_availability"
    if any(
        word in lowered_sentence
        for word in (
            "head-to-head",
            "head to head",
            "h2h",
            "previous meeting",
            "previous meetings",
            "met previously",
            "last meeting",
        )
    ):
        return "match_history"
    if any(
        word in lowered_sentence
        for word in (
            "recent form",
            "last match",
            "last matches",
            "last five",
            "last 10",
            "unbeaten",
            "winning streak",
            "form guide",
            "qualifying run",
            "results",
        )
    ):
        return "recent_form"
    if _has_player_form_signal(lowered_sentence):
        return "player_form"
    if any(
        word in lowered_sentence
        for word in (
            "tactical",
            "tactics",
            "pressing",
            "counterattack",
            "counter-attack",
            "transition",
            "low block",
            "high line",
            "set piece",
            "set-piece",
            "key matchup",
            "key matchups",
        )
    ):
        return "tactical"
    if any(word in lowered_sentence for word in ("lineup", "line-up", "starting 11", "starting xi", "predicted xi", "bench", "formation")):
        return "lineup"
    if any(word in lowered_sentence for word in ("prediction", "preview", "odds", "pick", "favorite", "favourite")):
        return "market_preview"
    return None


def _claim_subject(
    sentence: str,
    *,
    home_team: str,
    away_team: str,
    known_players: dict[str, list[str]] | None = None,
) -> tuple[str, str | None, str | None]:
    lowered = sentence.lower()
    for team in (home_team, away_team):
        players = sorted(_player_aliases_for_team(team, known_players=known_players), key=len, reverse=True)
        for player in players:
            if _alias_in_text(player, lowered):
                canonical = _canonical_player_name(player, team=team, known_players=known_players)
                return canonical, team, canonical
    inferred_player = _infer_player_from_availability_sentence(sentence, home_team=home_team, away_team=away_team)
    if inferred_player:
        team = _team_from_sentence(sentence, home_team=home_team, away_team=away_team)
        return inferred_player, team, inferred_player
    team = _team_from_sentence(sentence, home_team=home_team, away_team=away_team)
    if team:
        return team, team, None
    return "unknown", None, None


def _player_aliases_for_team(team: str, *, known_players: dict[str, list[str]] | None = None) -> list[str]:
    if known_players and team in known_players:
        return known_players[team]
    return STAR_PLAYERS.get(team, [])


def _alias_in_text(alias: str, lowered_text: str) -> bool:
    if not alias:
        return False
    folded_alias = _fold_text(alias)
    folded_text = _fold_text(lowered_text)
    return re.search(rf"(?<![\w-]){re.escape(folded_alias)}(?![\w-])", folded_text) is not None


def _canonical_player_name(alias: str, *, team: str, known_players: dict[str, list[str]] | None = None) -> str:
    alias_key = _fold_text(alias)
    candidates: list[str] = []
    if known_players and team in known_players:
        candidates.extend(known_players[team])
    candidates.extend(STAR_PLAYERS.get(team, []))
    for candidate in candidates:
        candidate_key = _fold_text(candidate)
        if " " in candidate_key and candidate_key.endswith(f" {alias_key}"):
            return candidate.title()
    for candidate in candidates:
        candidate_key = _fold_text(candidate)
        if candidate_key == alias_key:
            return candidate.title()
    return alias.title()


def _fold_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _team_from_sentence(sentence: str, *, home_team: str, away_team: str) -> str | None:
    lowered = sentence.lower()
    locally_signaled_team = _team_with_local_availability_signal(lowered, home_team=home_team, away_team=away_team)
    if locally_signaled_team:
        return locally_signaled_team
    home_index = lowered.find(home_team.lower())
    away_index = lowered.find(away_team.lower())
    has_home = home_index >= 0
    has_away = away_index >= 0
    if has_home and has_away:
        # When both teams appear, the sentence subject usually appears first:
        # "Morocco have suffered ... against Brazil" should be about Morocco.
        return home_team if home_index < away_index else away_team
    if has_home:
        return home_team
    if has_away:
        return away_team
    return None


def _team_with_local_availability_signal(lowered_sentence: str, *, home_team: str, away_team: str) -> str | None:
    if not _has_negative_availability_signal(lowered_sentence):
        return None
    availability_words = (
        "injury",
        "injured",
        "suffered",
        "ruled out",
        "out of",
        "unavailable",
        "doubtful",
        "headaches",
        "blow",
        "absences",
    )
    candidates: list[tuple[int, str]] = []
    for team in (home_team, away_team):
        team_key = team.lower()
        for match in re.finditer(rf"\b{re.escape(team_key)}\b", lowered_sentence):
            window = lowered_sentence[match.start() : match.start() + 120]
            if any(word in window for word in availability_words):
                candidates.append((match.start(), team))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _infer_player_from_availability_sentence(sentence: str, *, home_team: str, away_team: str) -> str:
    ignored = {
        home_team.lower(),
        away_team.lower(),
        "world cup",
        "team news",
        "injury news",
    }
    patterns = [
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+(?:is|has|was)\s+(?:listed|ruled|sidelined|injured|out|recovering|doubtful)",
        r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s+\([^)]*\)\s+is\s+out",
        r"\bright-back\s+([A-Z][a-z]+)\s+has\s+been\s+ruled\s+out",
    ]
    for pattern in patterns:
        match = re.search(pattern, sentence)
        if not match:
            continue
        candidate = match.group(1).strip()
        candidate_key = candidate.lower()
        if candidate_key not in ignored and not any(word in candidate_key for word in ("injury", "news", "preview")):
            return candidate
    return ""


def _claim_impact(claim_type: str, *, team: str | None, home_team: str, away_team: str) -> str:
    if team is None:
        return "unknown"
    if claim_type == "injury_availability":
        return "negative_home" if team == home_team else "negative_away"
    if claim_type in {
        "lineup",
        "tactical",
        "market_preview",
        "recent_form",
        "player_form",
        "squad_roster",
        "match_history",
        "team_profile",
        "team_history",
    }:
        return "context_home" if team == home_team else "context_away"
    return "unknown"


def _claim_metrics(claim_type: str, text: str) -> dict[str, Any]:
    lowered = text.lower()
    metrics: dict[str, Any] = {}
    if claim_type == "injury_availability":
        status = _availability_status(lowered)
        if status:
            metrics["availability_status"] = status
        body_part = _injury_body_part(lowered)
        if body_part:
            metrics["injury_body_part"] = body_part
    if claim_type in {"player_form", "recent_form"}:
        for key, pattern in (
            ("goals", r"\b(\d+(?:\.\d+)?)\s+goals?\b"),
            ("assists", r"\b(\d+(?:\.\d+)?)\s+assists?\b"),
            ("appearances", r"\b(\d+(?:\.\d+)?)\s+(?:appearances?|matches|games)\b"),
            ("minutes", r"\b(\d+(?:,\d{3})*(?:\.\d+)?)\s+minutes?\b"),
            ("clean_sheets", r"\b(\d+(?:\.\d+)?)\s+clean sheets?\b"),
            ("blocked_shots", r"\b(\d+(?:\.\d+)?)\s+blocked shots?\b"),
            ("key_passes_per_game", r"\b(\d+(?:\.\d+)?)\s+key passes?\s+(?:each|per)\s+game\b"),
            ("pass_completion_pct", r"\b(\d+(?:\.\d+)?)%\s+pass completion\b"),
            ("xg", r"\bxg\s*(?:of|output is|=|:)?\s*(\d+(?:\.\d+)?)\b"),
            ("xa", r"\bxa\s*(?:of|output is|=|:)?\s*(\d+(?:\.\d+)?)\b"),
        ):
            value = _metric_number(pattern, lowered)
            if value is not None:
                metrics[key] = value
        if "top scorer" in lowered or "leading goalscorer" in lowered:
            metrics["role_signal"] = "top_scorer"
    if claim_type == "match_history":
        value = _metric_number(r"\blast\s+(\d+)\b", lowered)
        if value is not None:
            metrics["sample_matches"] = int(value)
        season = _metric_number(r"\b(20\d{2})\s+results?\b", lowered)
        if season is not None:
            metrics["results_season_year"] = int(season)
        if any(marker in lowered for marker in ("results", "scores", "fixtures", "schedule")):
            metrics["archive_signal"] = "results_archive"
    if claim_type in {"tactical", "lineup"}:
        formation = _formation_pattern(lowered)
        if formation:
            metrics["formation"] = formation
    if claim_type == "tactical":
        if any(marker in lowered for marker in ("lineup", "line-up", "predicted xi", "starting xi")):
            metrics["tactical_signal"] = "lineup"
        elif "formation" in lowered:
            metrics["tactical_signal"] = "formation"
        elif "tactic" in lowered or "tactics" in lowered:
            metrics["tactical_signal"] = "tactics"
        elif "key players" in lowered:
            metrics["tactical_signal"] = "key_players"
    if claim_type == "team_history":
        fifa_year = _metric_number(r"\bfifa since\s+(\d{4})\b", lowered)
        if fifa_year is not None:
            metrics["fifa_member_since_year"] = int(fifa_year)
        confederation_year = _metric_number(
            r"\b(?:conmebol|confederation of african football|caf)\s+since\s+(\d{4})\b",
            lowered,
        )
        if confederation_year is None:
            confederation_year = _metric_number(r"\bfounding member of [a-z ,]+ in\s+(\d{4})\b", lowered)
        if confederation_year is not None:
            metrics["confederation_member_since_year"] = int(confederation_year)
    return metrics


def _claim_metrics_for_match(
    claim_type: str,
    text: str,
    *,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    metrics = _claim_metrics(claim_type, text)
    if claim_type == "match_history":
        metrics.update(_historical_score_metrics(text, home_team=home_team, away_team=away_team))
    return metrics


def _historical_score_metrics(text: str, *, home_team: str, away_team: str) -> dict[str, Any]:
    cleaned = _clean_text(text)
    folded = _fold_text(cleaned)
    home = _fold_text(home_team)
    away = _fold_text(away_team)
    patterns = (
        (home_team, away_team, rf"\b{re.escape(home)}\b\D{{0,50}}\b(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\b\D{{0,50}}\b{re.escape(away)}\b"),
        (away_team, home_team, rf"\b{re.escape(away)}\b\D{{0,50}}\b(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\b\D{{0,50}}\b{re.escape(home)}\b"),
        (home_team, away_team, rf"\b{re.escape(home)}\b\D{{0,24}}\b(?:beat|defeated|won|lost|drew|draw)\b\D{{0,24}}\b{re.escape(away)}\b\D{{0,24}}\b(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\b"),
        (away_team, home_team, rf"\b{re.escape(away)}\b\D{{0,24}}\b(?:beat|defeated|won|lost|drew|draw)\b\D{{0,24}}\b{re.escape(home)}\b\D{{0,24}}\b(\d{{1,2}})\s*[-–]\s*(\d{{1,2}})\b"),
    )
    for team_a, team_b, pattern in patterns:
        match = re.search(pattern, folded)
        if not match:
            continue
        score_a = int(match.group(1))
        score_b = int(match.group(2))
        return {
            "historical_team_a": team_a,
            "historical_team_b": team_b,
            "historical_team_a_score": score_a,
            "historical_team_b_score": score_b,
            "historical_result_label": f"{team_a} {score_a}-{score_b} {team_b}",
            "historical_result_signal": "explicit_score",
        }
    return {}


def _availability_status(lowered_text: str) -> str:
    if any(marker in lowered_text for marker in ("ruled out", "to miss", "misses", "unavailable", "withdrawn")):
        return "out"
    if any(marker in lowered_text for marker in ("doubtful", "doubt", "game-time")):
        return "doubtful"
    if any(marker in lowered_text for marker in ("injured", "injury", "sidelined")):
        return "injured"
    return ""


def _injury_body_part(lowered_text: str) -> str:
    body_parts = (
        ("hamstring", "hamstring"),
        ("calf", "calf"),
        ("knee ligament", "knee_ligament"),
        ("acl", "acl"),
        ("knee", "knee"),
        ("groin", "groin"),
        ("ankle", "ankle"),
        ("thigh", "thigh"),
        ("foot", "foot"),
        ("shoulder", "shoulder"),
        ("pubalgia", "pubalgia"),
        ("muscle", "muscle"),
    )
    for marker, label in body_parts:
        if marker in lowered_text:
            return label
    return ""


def _formation_pattern(lowered_text: str) -> str:
    match = re.search(r"\b([1-5](?:-[1-5]){2,4})\b", lowered_text)
    if not match:
        return ""
    parts = [int(part) for part in match.group(1).split("-")]
    if not 8 <= sum(parts) <= 11:
        return ""
    return match.group(1)


def _metric_number(pattern: str, lowered_text: str) -> float | int | None:
    match = re.search(pattern, lowered_text)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    if value.is_integer():
        return int(value)
    return round(value, 4)


def _has_negative_availability_signal(lowered_sentence: str) -> bool:
    if _is_roster_omission_context(lowered_sentence) or _is_historical_injury_context(lowered_sentence):
        return False
    negative_pattern = re.compile(
        r"\b("
        r"injured|injury|sidelined|doubtful|doubt|miss|misses|"
        r"ruled out|out for|out of|withdrawn|unavailable|"
        r"calf|hamstring|knee ligament|groin|pubalgia|acl"
        r")\b"
    )
    false_positive_context = (
        "injury time",
        "without injury",
        "no injury",
        "injury-free",
        "returned from injury",
        "back from injury",
    )
    return bool(negative_pattern.search(lowered_sentence)) and not any(
        marker in lowered_sentence for marker in false_positive_context
    )


def _is_roster_omission_context(lowered_sentence: str) -> bool:
    roster_patterns = (
        r"\bwho was left out\b",
        r"\bleft out of\b",
        r"\bleaving out\b",
        r"\bnot included in\b",
        r"\bexcluded from\b",
    )
    if not any(re.search(pattern, lowered_sentence) for pattern in roster_patterns):
        return False
    current_injury_markers = (
        "injured",
        "injury blow",
        "injury doubt",
        "doubtful",
        "unavailable",
        "sidelined",
        "ruled out",
        "withdrawn",
    )
    return not any(marker in lowered_sentence for marker in current_injury_markers)


def _is_historical_injury_context(lowered_sentence: str) -> bool:
    historical_patterns = (
        r"\breturning (?:to|from)\b.{0,80}\binjury\b",
        r"\breturned (?:to|from)\b.{0,80}\binjury\b",
        r"\bback (?:from|after)\b.{0,80}\binjury\b",
        r"\bafter (?:a |an )?.{0,40}\binjury\b",
        r"\bsince [a-z]+ \d{1,2},? \d{4}\b.{0,80}\binjury\b",
        r"\b\d+(?:\.\d+)?\s*(?:years?|months?) out with\b.{0,50}\binjury\b",
        r"\binternational absence\b",
    )
    if not any(re.search(pattern, lowered_sentence) for pattern in historical_patterns):
        return False
    current_markers = (
        "will miss",
        "to miss",
        "miss opener",
        "misses",
        "ruled out",
        "sidelined",
        "doubtful",
        "unavailable",
        "injury blow",
        "injury doubt",
        "game-time",
    )
    return not any(marker in lowered_sentence for marker in current_markers)


def _has_player_form_signal(lowered_sentence: str) -> bool:
    performance_markers = (
        "season form",
        "club form",
        "goals",
        "assists",
        "scored",
        "minutes",
        "appearances",
        "starter",
        "starts",
        "in form",
        "top scorer",
        "leading goalscorer",
        "performance",
        "performances",
        "rating",
        "ratings",
        "xg",
        "xa",
        "shots",
        "chances created",
        "progressive passes",
    )
    generic_only = (
        "key player",
        "key players",
        "squad list",
        "squad roster",
        "player breakdown",
        "projected squad",
    )
    if any(marker in lowered_sentence for marker in performance_markers):
        return True
    return any(marker in lowered_sentence for marker in generic_only) and any(
        detail in lowered_sentence for detail in ("goals", "assists", "minutes", "scored", "appearances")
    )


def _claim_confidence(claim_type: str, lowered_sentence: str, *, source_title: str = "", source_url: str = "") -> float:
    confidence = {
        "injury_availability": 0.72,
        "recent_form": 0.56,
        "player_form": 0.54,
        "match_history": 0.5,
        "lineup": 0.58,
        "tactical": 0.45,
        "market_preview": 0.35,
        "team_profile": 0.46,
        "team_history": 0.5,
    }.get(claim_type, 0.3)
    if "confirmed" in lowered_sentence:
        confidence += 0.08
    if "predicted" in lowered_sentence or "possible" in lowered_sentence:
        confidence -= 0.05
    confidence += _source_quality_adjustment(source_title=source_title, source_url=source_url)
    return round(max(min(confidence, 0.9), 0.1), 2)


def _source_quality_adjustment(*, source_title: str, source_url: str) -> float:
    source = f"{source_title} {source_url}".lower()
    trusted = (
        "bbc",
        "espn",
        "rotowire",
        "fifa",
        "the athletic",
        "reuters",
        "associated press",
        "apnews",
        "sports illustrated",
        "sports mole",
        "flashscore",
    )
    weak = (
        "tiktok",
        "youtube",
        "reddit",
        "pinterest",
        "prediction",
        "predictions",
        "odds",
        "pick",
        "betting",
        "tips",
    )
    adjustment = 0.0
    if any(marker in source for marker in trusted):
        adjustment += 0.05
    if any(marker in source for marker in weak):
        adjustment -= 0.08
    return adjustment


def _source_metadata(
    *,
    source_title: str,
    source_url: str,
    source_published: str = "",
    extraction_method: str,
) -> dict[str, Any]:
    domain = _source_domain(source_url)
    recency = _source_recency_metadata(source_published)
    return {
        "source_published": source_published,
        **recency,
        "source_domain": domain,
        "source_kind": _source_kind(source_title=source_title, source_url=source_url, domain=domain),
        "source_quality": _source_quality_label(source_title=source_title, source_url=source_url, domain=domain),
        "extraction_method": extraction_method,
    }


def _source_recency_metadata(source_published: str, *, today: date | None = None) -> dict[str, Any]:
    published_date = _parse_source_date(source_published)
    if published_date is None:
        return {
            "source_published_date": "",
            "source_recency_days": None,
            "source_recency_bucket": "",
        }
    today_value = today or date.today()
    recency_days = max((today_value - published_date).days, 0)
    return {
        "source_published_date": published_date.isoformat(),
        "source_recency_days": recency_days,
        "source_recency_bucket": _source_recency_bucket(recency_days),
    }


def _parse_source_date(source_published: str) -> date | None:
    raw = _clean_text(source_published)
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.date()
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(raw[:32], pattern).date()
        except ValueError:
            continue
    iso_match = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", raw)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return None
    return None


def _source_recency_bucket(recency_days: int) -> str:
    if recency_days <= 7:
        return "last_7_days"
    if recency_days <= 30:
        return "last_30_days"
    if recency_days <= 180:
        return "last_180_days"
    if recency_days <= 365:
        return "last_year"
    return "older"


def _source_domain(source_url: str) -> str:
    if not source_url:
        return ""
    parsed = urllib.parse.urlparse(source_url)
    return parsed.netloc.lower().removeprefix("www.")


def _source_kind(*, source_title: str, source_url: str, domain: str) -> str:
    source = f"{source_title} {source_url} {domain}".lower()
    if source_url.startswith("telegram://"):
        return "social"
    if any(marker in source for marker in ("fifa.com", "federation", "official", ".ma", ".br")):
        return "official"
    if "wikipedia" in source:
        return "reference"
    if any(marker in source for marker in ("espn", "bbc", "reuters", "apnews", "associated press", "the athletic")):
        return "news"
    if any(marker in source for marker in ("fbref", "transfermarkt", "sofascore", "flashscore", "statbunker", "opta")):
        return "stats"
    if "google" in source or "duckduckgo" in source or "ddgs" in source:
        return "search"
    return "web"


def _source_quality_label(*, source_title: str, source_url: str, domain: str) -> str:
    source = f"{source_title} {source_url} {domain}".lower()
    strong = (
        "fifa.com",
        "bbc",
        "espn",
        "reuters",
        "apnews",
        "associated press",
        "the athletic",
        "rotowire",
        "flashscore",
        "fbref",
        "transfermarkt",
        "sofascore",
        "opta",
    )
    weak = (
        "tiktok",
        "youtube",
        "reddit",
        "pinterest",
        "prediction",
        "predictions",
        "boostmatch",
        "tips",
        "betting",
        "pick",
        "wc26lineups",
    )
    if any(marker in source for marker in weak):
        return "weak"
    if any(marker in source for marker in strong):
        return "strong"
    return "medium"


def _claim_signal(*, claims: list[EvidenceClaim], home_team: str, away_team: str) -> float:
    signal = 0.0
    for claim in claims:
        if claim.impact == "negative_home":
            signal -= 0.008 * claim.confidence
        elif claim.impact == "negative_away":
            signal += 0.008 * claim.confidence
    return max(min(signal, 0.025), -0.025)


def _dedupe_claims(claims: list[EvidenceClaim]) -> list[EvidenceClaim]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[EvidenceClaim] = []
    for claim in claims:
        key = (claim.claim_type, claim.subject.lower(), claim.claim[:120].lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def _news_items_from_any_payload(payload: Any, *, default_source: str) -> list[NewsItem]:
    raw_items = _extract_items(payload)
    items: list[NewsItem] = []
    for raw in raw_items[:12]:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        snippet = str(raw.get("body") or raw.get("snippet") or raw.get("description") or "").strip()
        combined_search_text = " - ".join(part for part in (title, snippet) if part)
        text = _clean_text(
            str(
                raw.get("text")
                or raw.get("full_text")
                or raw.get("content")
                or combined_search_text
                or raw.get("body")
                or ""
            )
        )
        if not text:
            continue
        author = raw.get("author") or raw.get("username") or raw.get("user") or raw.get("source") or default_source
        link = raw.get("url") or raw.get("link") or raw.get("href") or raw.get("tweet_url") or raw.get("permalink") or ""
        published = raw.get("created_at") or raw.get("published") or raw.get("date") or ""
        items.append(
            NewsItem(
                title=text,
                source=_clean_text(str(author)),
                link=str(link),
                published=str(published),
            )
        )
    return _dedupe_items(items)


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "items", "results", "tweets", "posts"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = _extract_items(value)
            if nested:
                return nested
    return []


def _dedupe_items(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    deduped: list[NewsItem] = []
    for item in items:
        key = item.link or item.title.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _fetch_ddgs_query(
    *,
    query: str,
    cache_file: Path,
    refresh: bool,
    timeout_seconds: int,
    max_results: int,
) -> list[NewsItem]:
    if cache_file.exists() and not refresh:
        return _news_items_from_any_payload(json.loads(cache_file.read_text(encoding="utf-8")), default_source="DDGS")

    raw_results: list[dict] = []
    try:
        from ddgs import DDGS

        with DDGS(timeout=timeout_seconds) as ddgs:
            for result in ddgs.text(query, max_results=max_results):
                raw_results.append(dict(result))
    except Exception:
        return []

    cache_file.write_text(json.dumps(raw_results, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return _news_items_from_any_payload(raw_results, default_source="DDGS")[:max_results]


def _fetch_ddgs_research(
    *,
    home_team: str,
    away_team: str,
    cache_dir: Path,
    refresh: bool,
    timeout_seconds: int,
) -> list[NewsItem]:
    cache_file = cache_dir / f"ddgs_research_{_slug(home_team)}_{_slug(away_team)}.json"
    if cache_file.exists() and not refresh:
        return _news_items_from_any_payload(json.loads(cache_file.read_text(encoding="utf-8")), default_source="DDGS")

    queries = [
        f"{home_team} {away_team} predicted lineups injuries team news World Cup",
        f"{home_team} {away_team} tactical preview key players World Cup",
        f"{home_team} recent form key players season form World Cup",
        f"{away_team} recent form key players season form World Cup",
    ]
    raw_results: list[dict] = []
    for query in queries:
        items = _fetch_ddgs_query(
            query=query,
            cache_file=cache_dir / f"ddgs_query_{_stable_hash(query)}.json",
            refresh=refresh,
            timeout_seconds=timeout_seconds,
            max_results=4,
        )
        for item in items:
            raw_results.append(
                {
                    "title": item.title,
                    "source": item.source,
                    "href": item.link,
                    "published": item.published,
                }
            )

    cache_file.write_text(json.dumps(raw_results, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return _news_items_from_any_payload(raw_results, default_source="DDGS")[:8]


def _fetch_native_camel_research(
    *,
    home_team: str,
    away_team: str,
    timeout_seconds: int,
) -> list[NewsItem]:
    api_key = (
        os.environ.get("COLONY_CAMEL_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
        or os.environ.get("COLONY_LLM_API_KEY", "").strip()
    )
    if not api_key:
        return []

    try:
        from camel.agents import ChatAgent
        from camel.models import ModelFactory
        from camel.toolkits import SearchToolkit
        from camel.types import ModelPlatformType
    except Exception:
        return []

    platform_name = os.environ.get("COLONY_CAMEL_MODEL_PLATFORM", "OPENROUTER").strip().upper()
    platform = getattr(ModelPlatformType, platform_name, platform_name.lower())
    model_type = os.environ.get("COLONY_CAMEL_MODEL", "").strip() or os.environ.get("COLONY_LLM_MODEL", "").strip()
    if not model_type:
        model_type = "deepseek/deepseek-v4-flash"
    base_url = os.environ.get("COLONY_CAMEL_BASE_URL", "").strip() or os.environ.get("COLONY_LLM_BASE_URL", "").strip()

    try:
        model = ModelFactory.create(
            model_platform=platform,
            model_type=model_type,
            model_config_dict={"temperature": 0.0},
            api_key=api_key,
            url=base_url or None,
            timeout=timeout_seconds,
            max_retries=1,
        )
        agent = ChatAgent(
            system_message=(
                "You are a football data scout. Search the web, then return only compact JSON. "
                "Do not include prose outside JSON."
            ),
            model=model,
            tools=[SearchToolkit().search_duckduckgo],
            max_iteration=4,
            step_timeout=timeout_seconds,
        )
        response = agent.step(
            f"Search for current {home_team} vs {away_team} World Cup predicted lineups, injury news, "
            "key player availability, recent team form, player season form, and tactical preview. "
            "Return JSON array of up to 6 objects with keys title, source, link, published."
        )
    except Exception:
        return []

    content = ""
    try:
        content = response.msgs[0].content
    except Exception:
        content = str(response)
    return [
        NewsItem(
            title=item.title,
            source=f"CAMEL:{item.source}" if item.source else "CAMEL",
            link=item.link,
            published=item.published,
        )
        for item in _items_from_llm_json(content)
    ]


def _items_from_llm_json(content: str) -> list[NewsItem]:
    text = content.strip()
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        text = match.group(0)
    try:
        payload = json.loads(text)
    except Exception:
        return [
            NewsItem(title=_clean_text(line.strip("- ")), source="CAMEL", link="", published="")
            for line in text.splitlines()
            if line.strip()
        ][:6]
    return _news_items_from_any_payload(payload, default_source="CAMEL")


def _camel_available() -> bool:
    try:
        import camel  # noqa: F401
    except Exception:
        return False
    return True


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
    admissible_claims = _admissible_evidence_claims(evidence_claims or [])
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
        evidence_claims=admissible_claims,
    )


def _admissible_evidence_claims(claims: list[dict]) -> list[dict]:
    admissible: list[dict] = []
    for claim in claims:
        if not claim.get("claim_type") or not claim.get("claim"):
            continue
        if not claim.get("source_url") and not claim.get("source_title"):
            continue
        if str(claim.get("source_quality") or "").lower() == "weak":
            continue
        if str(claim.get("source_kind") or "").lower() == "search" and str(
            claim.get("source_quality") or ""
        ).lower() != "strong":
            continue
        if str(claim.get("impact") or "").lower() == "unknown":
            continue
        admissible.append(claim)
    return admissible


def _drop_empty_specialized_findings(findings: list[Finding], keep_by_key: dict[str, bool]) -> list[Finding]:
    kept: list[Finding] = []
    for finding in findings:
        key = finding.finding_id.rsplit(":", 1)[-1]
        if key in keep_by_key and not keep_by_key[key]:
            continue
        kept.append(finding)
    return kept


def _profile_trophy_signal(text: str) -> float:
    lowered = text.lower()
    score = 0.0
    score += lowered.count("world cup") * 0.12
    score += lowered.count("champion") * 0.08
    score += lowered.count("won") * 0.04
    return min(score, 1.0)


def _mention_count(items: list[NewsItem], team: str) -> int:
    pattern = re.compile(rf"\b{re.escape(team.lower())}\b")
    return sum(1 for item in items if pattern.search(item.title.lower()))


def _form_signal(items: list[NewsItem], team: str) -> float:
    signal = 0.0
    team_pattern = re.compile(rf"\b{re.escape(team.lower())}\b")
    positive = ("win", "wins", "beat", "beats", "defeat", "defeats", "qualify", "streak")
    negative = ("loss", "lost", "loses", "injury", "injured", "struggle", "defeat to")
    for item in items:
        title = item.title.lower()
        if not team_pattern.search(title):
            continue
        signal += sum(1 for word in positive if word in title)
        signal -= sum(1 for word in negative if word in title)
    return max(min(signal, 4.0), -4.0)


def _availability_hits(
    items: list[NewsItem],
    team: str,
    *,
    known_players: dict[str, list[str]] | None = None,
) -> int:
    players = _player_aliases_for_team(team, known_players=known_players)
    hits = 0
    for item in items:
        title = item.title.lower()
        has_availability_signal = any(word in title for word in ("injury", "injured", "withdraw", "sidelined", "doubt", "miss"))
        mentions_team = team.lower() in title
        mentions_player = any(_alias_in_text(player, title) for player in players)
        if has_availability_signal and (mentions_team or mentions_player):
            hits += 1
    return hits


def _titles(items: list[NewsItem], count: int = 3) -> str:
    return "; ".join(item.title for item in items[:count])


def _squad_roster_titles(players: list[SquadPlayer], count: int = 4) -> str:
    return "; ".join(
        " ".join(part for part in (player.name, f"({player.position})" if player.position else "") if part)
        for player in players[:count]
    )


def _citations(items: list[NewsItem], count: int = 4) -> list[str]:
    citations = [item.link for item in items[:count] if item.link]
    return citations


def _shorten(text: str, limit: int = 220) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _clamp(value: float) -> float:
    return min(max(value, 0.01), 0.99)


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().split() if part)


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
