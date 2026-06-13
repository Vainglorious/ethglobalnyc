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
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .models import Finding, MatchContext
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
        }


def public_match_context_from_tournament_match(
    match_entity: dict,
    *,
    cache_dir: str | Path,
    refresh: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    include_x: bool = False,
    include_camel: bool = False,
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
    match_news = fetch_news_query(
        cache_key=f"match_news_{_slug(home_team)}_{_slug(away_team)}",
        query=f"{home_team} {away_team} World Cup football",
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
        ),
        away_team: fetch_team_scout_news(
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
    )
    x_claims = extract_evidence_claims(
        items=x_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
    )
    camel_claims = extract_evidence_claims(
        items=camel_items,
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
    )
    team_form_claims = extract_evidence_claims(
        items=_team_scout_items(team_scout_news, "recent_form", max_per_team=3),
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
    )
    player_form_claims = extract_evidence_claims(
        items=_team_scout_items(team_scout_news, "player_form", max_per_team=3),
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
    )
    squad_depth_claims = extract_evidence_claims(
        items=_team_scout_items(team_scout_news, "squad_depth", max_per_team=3),
        home_team=home_team,
        away_team=away_team,
        cache_dir=cache_path,
        refresh=refresh,
        timeout_seconds=timeout_seconds,
        max_articles=4,
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
        include_x=include_x,
        include_camel=include_camel,
    )
    return MatchContext(
        round_id=round_id,
        home_team=home_team,
        away_team=away_team,
        market_home_probability=market,
        stats_home_signal=stats,
        odds_home_signal=odds,
        news_home_signal=news,
        findings=findings,
    )


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
) -> dict[str, list[NewsItem]]:
    """Fetch small team-targeted bundles for form, players, and squad depth."""
    queries = {
        "recent_form": (
            f"{team} national football team results fixtures last five matches 2025 2026 "
            "-prediction -predictions -odds -picks -betting"
        ),
        "player_form": (
            f"{team} football key players 2025-26 season goals assists club form stats "
            "-prediction -odds -betting"
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
                        query=f"{player} 2025-26 season goals assists club form stats",
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
        filtered = _filter_topic_items(items, topic, team=team)
        if topic in {"recent_form", "player_form"}:
            bundles[topic] = filtered[:5]
        else:
            bundles[topic] = (filtered or items)[:5]
    return bundles


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


def _filter_topic_items(items: list[NewsItem], topic: str, *, team: str) -> list[NewsItem]:
    filtered: list[NewsItem] = []
    for item in items:
        text = f"{item.title} {item.source} {item.link}".lower()
        if _is_noisy_public_item(text):
            continue
        if topic == "recent_form":
            if any(noisy in text for noisy in ("prediction", "predictions", "odds", "pick", "betting", "tips")):
                continue
            if not _item_mentions_team_or_player(text, team):
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
            if not _item_mentions_team_or_player(text, team):
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
        filtered.append(item)
    return filtered


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


def _item_mentions_team_or_player(lowered_text: str, team: str) -> bool:
    if team.lower() in lowered_text:
        return True
    return any(player in lowered_text for player in STAR_PLAYERS.get(team, []))


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
                    home_team=home_team,
                    away_team=away_team,
                )
            )
    return _dedupe_claims(claims)[:12]


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
) -> tuple[float, float, float, float]:
    market, stats, odds, news = synthetic_probabilities(home_team, away_team)
    profile_shift = _profile_trophy_signal(home_profile.extract) - _profile_trophy_signal(away_profile.extract)
    stats = _clamp(stats + profile_shift * 0.018)

    home_form = _form_signal(recent_results_news.get(home_team, []), home_team)
    away_form = _form_signal(recent_results_news.get(away_team, []), away_team)
    home_form += _form_signal(team_scout_news.get(home_team, {}).get("recent_form", []), home_team)
    away_form += _form_signal(team_scout_news.get(away_team, {}).get("recent_form", []), away_team)
    stats = _clamp(stats + (home_form - away_form) * 0.006)

    home_mentions = _mention_count(match_news, home_team)
    away_mentions = _mention_count(match_news, away_team)
    if home_mentions or away_mentions:
        news += (home_mentions - away_mentions) * 0.004

    home_availability_hits = _availability_hits(availability_news, home_team)
    away_availability_hits = _availability_hits(availability_news, away_team)
    news += (away_availability_hits - home_availability_hits) * 0.006

    home_x_hits = _availability_hits(x_items, home_team)
    away_x_hits = _availability_hits(x_items, away_team)
    news += (away_x_hits - home_x_hits) * 0.008

    home_research_mentions = _mention_count(camel_items, home_team)
    away_research_mentions = _mention_count(camel_items, away_team)
    news += (home_research_mentions - away_research_mentions) * 0.002
    news += _claim_signal(
        claims=availability_claims + x_claims + camel_claims + team_form_claims + player_form_claims + squad_depth_claims,
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
    availability_titles = _titles(availability_news, count=4)
    availability_citations = _citations(availability_news)
    x_titles = _titles(x_items, count=4)
    x_citations = _citations(x_items)
    camel_titles = _titles(camel_items, count=4)
    camel_citations = _citations(camel_items)

    findings = [
        _finding(
            round_id=round_id,
            key="public_baseline",
            scout_name="public_baseline_scout",
            access_level="public",
            source_type="market",
            finding_name="public_data_baseline",
            home_probability=market,
            market=market,
            confidence=0.52,
            summary=(
                f"Public-data baseline for {home_team} vs {away_team}. It uses the KG match identity plus "
                "public team profiles and news visibility; it is not a bookmaker odds feed."
            ),
            citations=[home_profile.page_url, away_profile.page_url],
        ),
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
    ]

    if include_x:
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
                    if x_items
                    else "X availability scout was enabled, but SCRAPECREATORS_X_SEARCH_URL/COLONY_X_SEARCH_URL "
                    "and SCRAPECREATORS_API_KEY/COLONY_X_API_KEY are not configured or returned no items."
                ),
                citations=x_citations if x_items else ["local://colony/x-scout-not-configured"],
                cost=0.0,
                evidence_claims=[claim.to_dict() for claim in x_claims],
            )
        )

    if include_camel:
        native_requested = os.environ.get("COLONY_CAMEL_USE_NATIVE", "").strip() == "1"
        native_returned_items = any(item.source.startswith("CAMEL:") for item in camel_items)
        if native_requested and native_returned_items:
            native_status = "native CAMEL ChatAgent + SearchToolkit returned research items"
        elif native_requested and _camel_available():
            native_status = "native CAMEL was requested but returned no usable structured items; used direct DDGS/web fallback"
        elif _camel_available():
            native_status = "CAMEL package detected, but native mode is disabled; used direct DDGS/web fallback"
        else:
            native_status = "CAMEL package not installed; used direct DDGS/web fallback"
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
            key="odds_unavailable",
            scout_name="odds_availability_scout",
            access_level="public",
            source_type="odds",
            finding_name="odds_unavailable_public_test",
            home_probability=odds,
            market=market,
            confidence=0.22,
            summary=(
                "No real odds provider is configured for this public-data test. "
                "This finding carries a low-confidence calibrated placeholder until an odds API is attached."
            ),
            citations=["local://colony/public-data-mode"],
        ),
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
    return findings


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
    home_team: str,
    away_team: str,
) -> list[EvidenceClaim]:
    claims: list[EvidenceClaim] = []
    for sentence in _sentences(text):
        lowered = sentence.lower()
        claim_type = _claim_type(lowered)
        if claim_type is None:
            continue
        subject, team, player = _claim_subject(sentence, home_team=home_team, away_team=away_team)
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
            "recent form",
            "last match",
            "last matches",
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
    if any(word in lowered_sentence for word in ("lineup", "line-up", "starting 11", "starting xi", "predicted xi", "bench", "formation")):
        return "lineup"
    if any(word in lowered_sentence for word in ("tactical", "pressing", "counterattack", "counter-attack", "low block", "set piece", "set-piece")):
        return "tactical"
    if any(word in lowered_sentence for word in ("prediction", "preview", "odds", "pick", "favorite", "favourite")):
        return "market_preview"
    return None


def _claim_subject(sentence: str, *, home_team: str, away_team: str) -> tuple[str, str | None, str | None]:
    lowered = sentence.lower()
    for team in (home_team, away_team):
        players = STAR_PLAYERS.get(team, [])
        for player in players:
            if player in lowered:
                return player.title(), team, player.title()
    inferred_player = _infer_player_from_availability_sentence(sentence, home_team=home_team, away_team=away_team)
    if inferred_player:
        team = _team_from_sentence(sentence, home_team=home_team, away_team=away_team)
        return inferred_player, team, inferred_player
    team = _team_from_sentence(sentence, home_team=home_team, away_team=away_team)
    if team:
        return team, team, None
    return "unknown", None, None


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
    if claim_type in {"lineup", "tactical", "market_preview", "recent_form", "player_form"}:
        return "context_home" if team == home_team else "context_away"
    return "unknown"


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
        "lineup": 0.58,
        "tactical": 0.45,
        "market_preview": 0.35,
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
        evidence_claims=evidence_claims or [],
    )


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


def _availability_hits(items: list[NewsItem], team: str) -> int:
    players = STAR_PLAYERS.get(team, [])
    hits = 0
    for item in items:
        title = item.title.lower()
        has_availability_signal = any(word in title for word in ("injury", "injured", "withdraw", "sidelined", "doubt", "miss"))
        mentions_team = team.lower() in title
        mentions_player = any(player in title for player in players)
        if has_availability_signal and (mentions_team or mentions_player):
            hits += 1
    return hits


def _titles(items: list[NewsItem], count: int = 3) -> str:
    return "; ".join(item.title for item in items[:count]) or "No Google News RSS items returned."


def _citations(items: list[NewsItem], count: int = 4) -> list[str]:
    citations = [item.link for item in items[:count] if item.link]
    return citations or ["https://news.google.com/"]


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
