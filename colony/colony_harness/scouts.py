"""Mock scout findings for local Colony simulations."""

from __future__ import annotations

from .models import Finding, MatchContext


TEAM_STRENGTHS = {
    "Argentina": 0.78,
    "Brazil": 0.77,
    "France": 0.76,
    "England": 0.74,
    "Spain": 0.74,
    "Portugal": 0.72,
    "Netherlands": 0.71,
    "Germany": 0.7,
    "Morocco": 0.66,
    "Switzerland": 0.64,
    "Scotland": 0.58,
    "Qatar": 0.5,
    "Haiti": 0.46,
    "Senegal": 0.63,
}


def mock_findings_from_config(data: dict) -> list[Finding]:
    """Build deterministic fake scout findings until real data sources are connected."""
    match = data["match"]
    round_id = data["round_id"]
    home_team = str(match["home_team"])
    away_team = str(match["away_team"])
    market = float(match["market_home_probability"])
    stats = float(match["stats_home_signal"])
    odds = float(match["odds_home_signal"])
    news = float(match["news_home_signal"])

    return mock_findings_for_match(
        round_id=round_id,
        home_team=home_team,
        away_team=away_team,
        market=market,
        stats=stats,
        odds=odds,
        news=news,
        include_social=True,
    )


def mock_match_context_from_tournament_match(match_entity: dict) -> MatchContext:
    """Create a match context from a tournament KG match entity with no X/social findings."""
    attrs = match_entity["attributes"]
    home_team = str(attrs["team1"])
    away_team = str(attrs["team2"])
    market, stats, odds, news = synthetic_probabilities(home_team, away_team)
    round_id = str(match_entity["entity_id"]).replace("match:", "round:")
    return MatchContext(
        round_id=round_id,
        home_team=home_team,
        away_team=away_team,
        market_home_probability=market,
        stats_home_signal=stats,
        odds_home_signal=odds,
        news_home_signal=news,
        findings=mock_findings_for_match(
            round_id=round_id,
            home_team=home_team,
            away_team=away_team,
            market=market,
            stats=stats,
            odds=odds,
            news=news,
            include_social=False,
        ),
    )


def synthetic_probabilities(home_team: str, away_team: str) -> tuple[float, float, float, float]:
    """Derive deterministic mock market/stats/odds/news probabilities from team ratings."""
    home_strength = _team_strength(home_team)
    away_strength = _team_strength(away_team)
    edge = (home_strength - away_strength) * 0.42
    market = _clamp(0.5 + edge * 0.9)
    stats = _clamp(0.5 + edge * 1.12)
    odds = _clamp((market * 0.75) + (0.5 * 0.25))
    news = _clamp(0.5 + edge * 0.72)
    return tuple(round(value, 4) for value in (market, stats, odds, news))  # type: ignore[return-value]


def mock_findings_for_match(
    *,
    round_id: str,
    home_team: str,
    away_team: str,
    market: float,
    stats: float,
    odds: float,
    news: float,
    include_social: bool = True,
) -> list[Finding]:
    """Build deterministic match findings, optionally excluding social/X-like findings."""
    lineup = _clamp((stats + news) / 2.0 - 0.015)
    weather = _clamp(market - 0.005)
    findings = [
        _finding(
            round_id=round_id,
            key="market",
            scout_name="market_baseline_scout",
            access_level="public",
            source_type="market",
            finding_name="market_home_probability",
            home_probability=market,
            market=market,
            confidence=0.8,
            summary=f"Consensus market baseline for {home_team} vs {away_team}.",
            citations=["mock://market/closing-consensus"],
            evidence_claims=[
                _mock_claim(
                    claim_type="market_preview",
                    subject=f"{home_team} market baseline",
                    team=home_team,
                    claim=(
                        f"Synthetic market baseline keeps {home_team} near the consensus price "
                        f"against {away_team}."
                    ),
                    impact="context_home",
                    confidence=0.65,
                    source_title="Synthetic market baseline",
                    source_url="mock://market/closing-consensus",
                )
            ],
        ),
        _finding(
            round_id=round_id,
            key="stats",
            scout_name="team_form_scout",
            access_level="public",
            source_type="stats",
            finding_name="team_form_rating_read",
            home_probability=stats,
            market=market,
            confidence=0.68,
            summary=(
                f"Synthetic team-form scout comparing {home_team} and {away_team}. "
                "No web or X/social data is used in this test."
            ),
            citations=[f"mock://ratings/{_slug(home_team)}", f"mock://ratings/{_slug(away_team)}"],
            evidence_claims=[
                _mock_claim(
                    claim_type="recent_form",
                    subject=f"{home_team} rating form",
                    team=home_team,
                    claim=(
                        f"Synthetic ratings put {home_team}'s recent-form baseline "
                        f"{'above' if stats >= market else 'below'} the market anchor."
                    ),
                    impact=_mock_impact(stats, market),
                    confidence=0.62,
                    source_title="Synthetic team-form scout",
                    source_url=f"mock://ratings/{_slug(home_team)}",
                )
            ],
        ),
        _finding(
            round_id=round_id,
            key="odds",
            scout_name="odds_scout",
            access_level="public",
            source_type="odds",
            finding_name="odds_home_signal",
            home_probability=odds,
            market=market,
            confidence=0.7,
            summary="Synthetic odds scout normalizing a second market view into home-win probability.",
            citations=["mock://odds/exchange-book", "mock://odds/bookmaker-consensus"],
            evidence_claims=[
                _mock_claim(
                    claim_type="market_preview",
                    subject="secondary odds view",
                    team=home_team if odds >= market else away_team,
                    claim=(
                        "Synthetic odds scout sees the secondary book "
                        f"{'above' if odds >= market else 'below'} the consensus home price."
                    ),
                    impact=_mock_impact(odds, market),
                    confidence=0.58,
                    source_title="Synthetic secondary odds scout",
                    source_url="mock://odds/exchange-book",
                )
            ],
        ),
        _finding(
            round_id=round_id,
            key="news",
            scout_name="team_news_scout",
            access_level="public",
            source_type="news",
            finding_name="team_news_read",
            home_probability=news,
            market=market,
            confidence=0.55,
            summary=(
                "Synthetic team-news scout placeholder for future ScrapeCreators web/news. "
                "X/social is intentionally excluded from this run."
            ),
            citations=[f"mock://news/{_slug(home_team)}", f"mock://news/{_slug(away_team)}"],
            evidence_claims=[
                _mock_claim(
                    claim_type="lineup",
                    subject=f"{home_team} team-news test signal",
                    team=home_team,
                    claim=(
                        f"Synthetic team-news signal gives {home_team} "
                        f"{'a cleaner' if news >= market else 'a less stable'} lineup read."
                    ),
                    impact=_mock_impact(news, market),
                    confidence=0.5,
                    source_title="Synthetic team-news scout",
                    source_url=f"mock://news/{_slug(home_team)}",
                )
            ],
        ),
        _finding(
            round_id=round_id,
            key="lineup",
            scout_name="lineup_scout",
            access_level="shared",
            source_type="lineup",
            finding_name="lineup_availability_read",
            home_probability=lineup,
            market=market,
            confidence=0.5,
            summary="Shared mock lineup read. This is the paid/premium placeholder, not an X/social scrape.",
            citations=["mock://lineup/projected-xi"],
            evidence_claims=[
                _mock_claim(
                    claim_type="lineup",
                    subject="shared projected XI",
                    team=home_team if lineup >= market else away_team,
                    claim=(
                        "Synthetic shared lineup read gives paid agents a small "
                        f"{home_team if lineup >= market else away_team} adjustment."
                    ),
                    impact=_mock_impact(lineup, market),
                    confidence=0.48,
                    source_title="Synthetic projected XI scout",
                    source_url="mock://lineup/projected-xi",
                )
            ],
        ),
        _finding(
            round_id=round_id,
            key="weather",
            scout_name="weather_scout",
            access_level="private",
            source_type="weather",
            finding_name="weather_disruption_read",
            home_probability=weather,
            market=market,
            confidence=0.35,
            cost=0.02,
            summary="Private mock weather read. This is a placeholder for a venue/date weather API later.",
            citations=["mock://weather/matchday-forecast"],
        ),
    ]

    if include_social:
        social = _clamp((market + news) / 2.0 + 0.01)
        findings.insert(
            -1,
            _finding(
                round_id=round_id,
                key="social",
                scout_name="social_scout",
                access_level="shared",
                source_type="social",
                finding_name="public_sentiment_read",
                home_probability=social,
                market=market,
                confidence=0.42,
                summary="Shared mock social sentiment read. Useful later for debate pressure and noise testing.",
                citations=["mock://social/reddit-twitter-sample"],
                evidence_claims=[
                    _mock_claim(
                        claim_type="market_preview",
                        subject="public sentiment test signal",
                        team=home_team if social >= market else away_team,
                        claim=(
                            "Synthetic public sentiment is noisy, but it gives the room "
                            f"a small {'home' if social >= market else 'away'} pressure test."
                        ),
                        impact=_mock_impact(social, market),
                        confidence=0.38,
                        source_title="Synthetic social sentiment scout",
                        source_url="mock://social/reddit-twitter-sample",
                    )
                ],
            ),
        )
    return findings


def _team_strength(team: str) -> float:
    if team in TEAM_STRENGTHS:
        return TEAM_STRENGTHS[team]
    checksum = sum(ord(char) for char in team)
    return 0.48 + (checksum % 24) / 100.0


def _finding(
    *,
    round_id: str,
    key: str,
    scout_name: str,
    access_level: str,
    source_type: str,
    finding_name: str,
    home_probability: float,
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
        home_probability=round(home_probability, 4),
        home_delta=round(home_probability - market, 4),
        confidence=confidence,
        cost=cost,
        citations=citations,
        summary=summary,
        evidence_claims=evidence_claims or [],
    )


def _mock_claim(
    *,
    claim_type: str,
    subject: str,
    team: str,
    claim: str,
    impact: str,
    confidence: float,
    source_title: str,
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
        "source_title": source_title,
        "source_url": source_url,
    }


def _mock_impact(probability: float, market: float) -> str:
    if probability >= market + 0.006:
        return "negative_away"
    if probability <= market - 0.006:
        return "negative_home"
    return "context_home"


def _clamp(value: float) -> float:
    return min(max(value, 0.01), 0.99)


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().split() if part)
