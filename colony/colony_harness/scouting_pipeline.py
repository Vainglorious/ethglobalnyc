"""Standalone scouting-to-KG pipeline helpers.

This module keeps local KG generation separate from the full Colony debate
harness. It turns pluggable dataset sources into normalized findings, builds a
round world graph, writes the same ingestion artifacts as normal runs, and
keeps a small progress log for scout runs.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shlex
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .artifacts import (
    _kg_manifest,
    _write_scouting_audit,
)
from .kg_ingestion import validate_scouting_kg_run
from .live_scouts import (
    DEFAULT_TIMEOUT_SECONDS,
    _extract_claims_from_text,
    public_match_context_from_tournament_match,
)
from .models import Finding, MatchContext, SourceType, WorldEntity, WorldGraph, WorldRelationship
from .scouts import openfootball_match_context_from_tournament_match, synthetic_probabilities
from .scouting_views import (
    build_domain_graph_payload,
    build_knowledge_views_payload,
    build_scouting_run_summary_payload,
)
from .tournament_graph import build_tournament_graph, load_openfootball_schedule
from .world_graph import KG_SCHEMA_VERSION, build_world_graph


DEFAULT_LOCAL_RUNS_DIR = Path(__file__).resolve().parents[1] / "runs" / "scouting_kg"

KG_CATEGORY_ENTITY_TYPES: dict[str, tuple[str, ...]] = {
    "games": (
        "match",
        "match_result",
        "formation",
    ),
    "teams": (
        "team",
        "team_match_profile",
    ),
    "players": (
        "player",
        "player_match_profile",
        "player_stat_line",
        "availability_event",
        "availability_status",
        "club",
        "position",
    ),
    "scouting": (
        "scouting_topic",
        "team_scouting_topic",
        "scouting_gap",
    ),
    "context": (
        "tournament",
        "group",
        "stage",
        "venue",
        "country",
        "body_part",
    ),
    "evidence": (
        "evidence_claim",
        "claim_type",
        "claim_impact",
        "claim_quality",
    ),
    "provenance": (
        "finding",
        "source",
        "source_domain",
        "source_domain_profile",
        "source_kind",
        "source_quality",
        "source_recency",
        "scout",
        "scout_match_profile",
    ),
    "raw_data": (
        "metric",
    ),
}

LEGACY_KG_CATEGORY_ENTITY_TYPES: dict[str, tuple[str, ...]] = {
    "players": (
        "player",
        "player_match_profile",
        "player_stat_line",
        "availability_event",
        "club",
        "position",
    ),
    "teams": (
        "team",
        "team_match_profile",
        "team_scouting_topic",
    ),
    "games": (
        "match",
        "match_result",
        "formation",
        "scouting_topic",
        "scouting_gap",
    ),
    "context": (
        "tournament",
        "group",
        "stage",
        "venue",
        "finding",
        "evidence_claim",
        "source",
        "source_domain",
        "source_domain_profile",
        "source_kind",
        "source_quality",
        "source_recency",
        "scout",
        "scout_match_profile",
        "claim_type",
        "claim_impact",
        "claim_quality",
        "metric",
    ),
}

ENV_REF_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
TEMPLATE_REF_RE = re.compile(r"\{([^{}]+)\}")


class ScoutingSourceError(ValueError):
    """Raised when a configured dataset source cannot return scout data."""


SOURCE_FAILURE_EXCEPTIONS = (
    ScoutingSourceError,
    TimeoutError,
    urllib.error.HTTPError,
    urllib.error.URLError,
    subprocess.TimeoutExpired,
    json.JSONDecodeError,
    OSError,
)


@dataclass(frozen=True)
class SourceSpec:
    """A local source plugin declaration.

    Supported forms are:
    - ``fixture``
    - ``public`` / ``public:/cache/dir``
    - ``deep-fixture``
    - ``json:/path/to/payload.json``
    - ``mcp:/path/to/exported_payload.json``
    - ``mcp-stdio:/path/to/mcp_source_config.json``
    - ``cli:command --that --prints-json``
    - ``api:https://example.test/payload.json``
    - ``{"kind": "api", "url": "...", "headers": {...}, "adapter": "txline_fixtures"}``
    - ``url:https://example.test/article.html`` or a plain ``https://...``
    """

    kind: str
    locator: str = ""
    raw: str = ""
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.kind == "mcp-stdio" and (self.config.get("tool") or self.config.get("tool_name")):
            return f"mcp-stdio:{self.config.get('tool') or self.config.get('tool_name')}"
        if self.locator:
            return f"{self.kind}:{self.locator}"
        return self.kind


@dataclass
class ScoutingRunLogger:
    """Collect JSONL-compatible progress events and optionally print them."""

    verbose: bool = True
    events: list[dict[str, Any]] = field(default_factory=list)

    def event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "event_type": event_type,
            **fields,
        }
        self.events.append(row)
        if self.verbose:
            details = " ".join(
                f"{key}={value}"
                for key, value in fields.items()
                if not isinstance(value, (dict, list, tuple)) and value not in {None, ""}
            )
            print(f"[scout-kg] {event_type}" + (f" {details}" if details else ""))
        return row


@dataclass(frozen=True)
class LocalScoutingResult:
    match: MatchContext
    findings: list[Finding]
    graph: WorldGraph
    source_summaries: list[dict[str, Any]]
    scout_targets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RawScoutingDocument:
    title: str
    text: str
    url: str = ""
    published: str = ""


@dataclass(frozen=True)
class ApiSourceResponse:
    url: str
    content_type: str
    raw: str
    payload: Any | None = None


@dataclass(frozen=True)
class ClaimQualityGateResult:
    findings: list[Finding]
    input_claim_count: int
    kept_claim_count: int
    rejected_claim_count: int
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    rejection_samples: list[dict[str, Any]] = field(default_factory=list)


def _stage_metrics_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    metrics: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") != "public_stage_complete":
            continue
        row = {
            "stage": event.get("stage"),
            "duration_seconds": event.get("duration_seconds"),
            "item_count": event.get("item_count"),
        }
        metrics.append({key: value for key, value in row.items() if value not in {None, ""}})
    return metrics


def default_sources_for_mode(mode: str) -> list[SourceSpec]:
    if mode == "deep":
        return [SourceSpec("fixture", raw="fixture"), SourceSpec("public", raw="public")]
    return [SourceSpec("fixture", raw="fixture")]


def parse_source_spec(raw: str | dict[str, Any]) -> SourceSpec:
    if isinstance(raw, dict):
        return _source_spec_from_object(raw)
    value = raw.strip()
    if not value:
        raise ScoutingSourceError("empty source spec")
    if value in {"fixture", "openfootball"}:
        return SourceSpec("fixture", raw=value)
    if value in {"public", "public-cache", "scrape"}:
        return SourceSpec("public", raw=value)
    if value in {"deep-fixture", "synthetic", "local-deep"}:
        return SourceSpec("deep-fixture", raw=value)
    if value.startswith("http://") or value.startswith("https://"):
        return SourceSpec("url", locator=value, raw=value)
    if ":" not in value:
        raise ScoutingSourceError(
            f"unsupported source spec '{raw}'. Use fixture, public, deep-fixture, json:, mcp:, cli:, api:, or url:."
        )
    kind, locator = value.split(":", 1)
    kind = kind.strip().lower()
    locator = locator.strip()
    if kind == "mcp_stdio":
        kind = "mcp-stdio"
    if kind == "public":
        return SourceSpec(kind=kind, locator=locator, raw=value)
    if kind not in {"json", "mcp", "mcp-stdio", "cli", "api", "url"}:
        raise ScoutingSourceError(f"unsupported source kind '{kind}'")
    if not locator:
        raise ScoutingSourceError(f"missing locator for source kind '{kind}'")
    return SourceSpec(kind=kind, locator=locator, raw=value)


def _source_spec_from_object(raw: dict[str, Any]) -> SourceSpec:
    kind = str(raw.get("kind") or raw.get("type") or "").strip().lower()
    if kind == "mcp_stdio":
        kind = "mcp-stdio"
    if not kind:
        raise ScoutingSourceError("object source is missing kind")
    if kind not in {"json", "mcp", "mcp-stdio", "cli", "api", "url", "public", "fixture", "deep-fixture"}:
        raise ScoutingSourceError(f"unsupported source kind '{kind}'")
    locator_value = raw.get("locator") or raw.get("path") or raw.get("url") or raw.get("command") or ""
    if isinstance(locator_value, list):
        locator = " ".join(shlex.quote(str(part)) for part in locator_value)
    else:
        locator = str(locator_value)
    return SourceSpec(kind=kind, locator=locator, raw=json.dumps(raw, sort_keys=True), config=dict(raw))


def load_graph_for_local_scouting(
    *,
    kg_path: str | Path,
    offline_sample: bool = False,
    openfootball_cache: str | Path | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """Load a tournament graph without starting the app."""

    if offline_sample:
        schedule = load_openfootball_schedule(offline_sample=True)
        return build_tournament_graph(schedule).to_dict()
    path = Path(kg_path)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    schedule = load_openfootball_schedule(cache_path=openfootball_cache, force_refresh=refresh)
    return build_tournament_graph(schedule).to_dict()


def select_match_entity(graph: dict[str, Any], *, match_id: str | None, match_name: str) -> dict[str, Any]:
    matches = [entity for entity in graph.get("entities", []) if entity.get("entity_type") == "match"]
    if match_id is not None:
        for match in matches:
            if match.get("entity_id") == match_id:
                return match
        raise ScoutingSourceError(f"match id not found: {match_id}")

    wanted = _normalize_match_name(match_name)
    for match in matches:
        if _normalize_match_name(str(match.get("name") or "")) == wanted:
            return match
    raise ScoutingSourceError(f"match not found: {match_name}")


def build_local_scouting_result(
    *,
    match_entity: dict[str, Any],
    mode: str,
    sources: list[SourceSpec],
    existing_kg_paths: list[str | Path] | None = None,
    merge_existing_kg: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    public_cache_dir: str | Path | None = None,
    refresh_public_data: bool = False,
    include_x: bool = False,
    include_camel: bool = False,
    include_camel_deep: bool = False,
    camel_agent_count: int = 4,
    include_telegram: bool = False,
    include_polygun: bool = False,
    include_deepseek_scout: bool = False,
    rescout_targets: list[dict[str, Any]] | None = None,
    as_of_utc: str = "",
    logger: ScoutingRunLogger | None = None,
) -> LocalScoutingResult:
    """Run source plugins and return a generated KG result."""

    log = logger or ScoutingRunLogger(verbose=False)
    match = _empty_match_context(match_entity)
    findings: list[Finding] = []
    source_summaries: list[dict[str, Any]] = []
    scout_targets = list(rescout_targets or [])
    log.event(
        "scouting_start",
        mode=mode,
        match=match_entity.get("name"),
        source_count=len(sources),
        rescout_target_count=len(scout_targets),
    )

    for source in sources:
        log.event("source_start", source=source.label)
        event_start_index = len(log.events)
        source_started = time.perf_counter()
        try:
            produced = _findings_from_source(
                source,
                match_entity=match_entity,
                timeout_seconds=timeout_seconds,
                public_cache_dir=public_cache_dir,
                refresh_public_data=refresh_public_data,
                include_x=include_x,
                include_camel=include_camel,
                include_camel_deep=include_camel_deep,
                camel_agent_count=camel_agent_count,
                include_telegram=include_telegram,
                include_polygun=include_polygun,
                include_deepseek_scout=include_deepseek_scout,
                rescout_targets=scout_targets,
                logger=log,
            )
        except SOURCE_FAILURE_EXCEPTIONS as exc:
            duration_seconds = round(time.perf_counter() - source_started, 3)
            error_summary = _source_error_summary(exc)
            log.event(
                "source_error",
                source=source.label,
                error_type=type(exc).__name__,
                error=error_summary,
                duration_seconds=duration_seconds,
            )
            source_summaries.append(
                {
                    "source": source.label,
                    "finding_count": 0,
                    "evidence_claim_count": 0,
                    "duration_seconds": duration_seconds,
                    "error_type": type(exc).__name__,
                    "error": error_summary,
                    "stage_metrics": _stage_metrics_from_events(log.events[event_start_index:]),
                }
            )
            continue
        gate_result = _apply_claim_quality_gate(produced, match=match)
        _log_claim_quality_gate(log, gate_result, source=source.label)
        produced = gate_result.findings
        if as_of_utc:
            before_count = _claim_count(produced)
            produced = _filter_findings_as_of(produced, as_of_utc=as_of_utc)
            log.event(
                "temporal_gate_complete",
                source=source.label,
                as_of_utc=as_of_utc,
                input_claims=before_count,
                kept_claims=_claim_count(produced),
            )
        findings.extend(produced)
        claim_count = sum(len(finding.evidence_claims) for finding in produced)
        summary = {
            "source": source.label,
            "finding_count": len(produced),
            "evidence_claim_count": claim_count,
            "duration_seconds": round(time.perf_counter() - source_started, 3),
        }
        stage_metrics = _stage_metrics_from_events(log.events[event_start_index:])
        if stage_metrics:
            summary["stage_metrics"] = stage_metrics
        source_summaries.append(summary)
        log.event("source_complete", **summary)

    existing_graphs = []
    for existing_path in existing_kg_paths or []:
        path = Path(existing_path)
        log.event("existing_kg_start", path=str(path))
        existing_started = time.perf_counter()
        existing_graph = json.loads(path.read_text(encoding="utf-8"))
        existing_graphs.append(existing_graph)
        produced = _findings_from_existing_kg(match, existing_graph, source_label=str(path))
        gate_result = _apply_claim_quality_gate(produced, match=match)
        _log_claim_quality_gate(log, gate_result, source=f"existing-kg:{path}")
        produced = gate_result.findings
        if as_of_utc:
            before_count = _claim_count(produced)
            produced = _filter_findings_as_of(produced, as_of_utc=as_of_utc)
            log.event(
                "temporal_gate_complete",
                source=f"existing-kg:{path}",
                as_of_utc=as_of_utc,
                input_claims=before_count,
                kept_claims=_claim_count(produced),
            )
        findings.extend(produced)
        claim_count = sum(len(finding.evidence_claims) for finding in produced)
        summary = {
            "source": f"existing-kg:{path}",
            "finding_count": len(produced),
            "evidence_claim_count": claim_count,
            "duration_seconds": round(time.perf_counter() - existing_started, 3),
        }
        source_summaries.append(summary)
        log.event("existing_kg_complete", **summary)

    findings = _dedupe_finding_ids(findings)
    match = MatchContext(
        round_id=match.round_id,
        home_team=match.home_team,
        away_team=match.away_team,
        market_home_probability=match.market_home_probability,
        stats_home_signal=match.stats_home_signal,
        odds_home_signal=match.odds_home_signal,
        news_home_signal=match.news_home_signal,
        match_date=match.match_date,
        match_time=match.match_time,
        group_name=match.group_name,
        stage_name=match.stage_name,
        venue_name=match.venue_name,
        score=match.score,
        findings=findings,
    )
    graph = build_world_graph(match)
    if merge_existing_kg:
        graph = merge_existing_graphs(graph, existing_graphs)
    log.event(
        "graph_built",
        graph_id=graph.graph_id,
        entities=len(graph.entities),
        relationships=len(graph.relationships),
        findings=len(findings),
    )
    return LocalScoutingResult(
        match=match,
        findings=findings,
        graph=graph,
        source_summaries=source_summaries,
        scout_targets=scout_targets,
    )


def write_local_scouting_artifacts(
    *,
    out_dir: str | Path,
    result: LocalScoutingResult,
    logger: ScoutingRunLogger,
    mode: str,
) -> dict[str, Any]:
    """Write local artifacts compatible with export_scouting_kg.py."""

    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    round_result = SimpleNamespace(
        round_id=result.match.round_id,
        findings=result.findings,
        knowledge_views=[],
        world_graph=result.graph,
    )

    (path / "findings.json").write_text(
        json.dumps([finding.to_dict() for finding in result.findings], ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    graph_payload = result.graph.to_dict()
    graph_payload["schema_version"] = KG_SCHEMA_VERSION
    (path / "world_graph.json").write_text(
        json.dumps(graph_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    domain_graph = build_domain_graph_payload(result.graph)
    (path / "domain_graph.json").write_text(
        json.dumps(domain_graph, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    knowledge_views = build_knowledge_views_payload(
        match=result.match,
        findings=result.findings,
        graph=result.graph,
        source_summaries=result.source_summaries,
        scout_targets=result.scout_targets,
    )
    (path / "knowledge_views.json").write_text(
        json.dumps(knowledge_views, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_scouting_audit(path / "scouting_audit.json", round_result)  # type: ignore[arg-type]

    category_summary = graph_category_summary(result.graph)
    (path / "kg_categories.json").write_text(
        json.dumps(category_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest = _kg_manifest(round_result)  # type: ignore[arg-type]
    manifest["files"]["kg_categories"] = "kg_categories.json"
    manifest["files"]["scouting_log"] = "scouting_log.jsonl"
    manifest["files"]["domain_graph"] = "domain_graph.json"
    manifest["files"]["scouting_run_summary"] = "scouting_run_summary.json"
    manifest["domain_graph"] = {
        "graph_id": domain_graph["graph_id"],
        "entity_count": domain_graph["entity_count"],
        "relationship_count": domain_graph["relationship_count"],
        "entity_counts": domain_graph["entity_counts"],
        "filter": domain_graph["filter"],
    }
    manifest["knowledge_views"] = {
        "view_model": knowledge_views["view_model"],
        "view_names": knowledge_views["view_names"],
    }
    manifest["scouting_run"] = {
        "mode": mode,
        "source_summaries": result.source_summaries,
        "scout_targets": result.scout_targets,
        "category_names": sorted(category_summary["categories"]),
    }
    (path / "kg_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_local_run_summary(
        path / "scouting_run_summary.json",
        result=result,
        manifest=manifest,
        category_summary=category_summary,
        mode=mode,
        domain_graph=domain_graph,
        knowledge_views=knowledge_views,
        logger=logger,
        validation=None,
    )

    logger.event("artifacts_written", out_dir=str(path))
    (path / "scouting_log.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in logger.events),
        encoding="utf-8",
    )
    validation = validate_scouting_kg_run(path)
    logger.event(
        "validation_complete",
        passes=validation["passes"],
        status=validation["status"],
        entities=validation["entity_count"],
        relationships=validation["relationship_count"],
    )
    (path / "scouting_log.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in logger.events),
        encoding="utf-8",
    )
    _write_local_run_summary(
        path / "scouting_run_summary.json",
        result=result,
        manifest=manifest,
        category_summary=category_summary,
        mode=mode,
        domain_graph=domain_graph,
        knowledge_views=knowledge_views,
        logger=logger,
        validation=validation,
    )
    (path / "summary.md").write_text(_summary_markdown(result, manifest, validation, category_summary), encoding="utf-8")
    return {
        "out_dir": str(path),
        "manifest": manifest,
        "validation": validation,
        "categories": category_summary,
    }


def _write_local_run_summary(
    path: Path,
    *,
    result: LocalScoutingResult,
    manifest: dict[str, Any],
    category_summary: dict[str, Any],
    mode: str,
    domain_graph: dict[str, Any],
    knowledge_views: dict[str, Any],
    logger: ScoutingRunLogger,
    validation: dict[str, Any] | None,
) -> None:
    summary = build_scouting_run_summary_payload(
        mode=mode,
        match=result.match,
        graph=result.graph,
        findings=result.findings,
        source_summaries=result.source_summaries,
        scout_targets=result.scout_targets,
        manifest=manifest,
        validation=validation or {"status": "pending"},
        category_summary=category_summary,
        domain_graph=domain_graph,
        knowledge_views=knowledge_views,
    )
    summary["log_event_count"] = len(logger.events)
    readiness = manifest.get("readiness") or {}
    summary["kg_load_ready"] = bool(readiness.get("kg_load_ready"))
    summary["scouting_complete"] = bool(readiness.get("scouting_complete"))
    summary["agent_ready"] = bool(readiness.get("kg_load_ready")) and not bool(readiness.get("scouting_backlog_count"))
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def create_default_run_dir(base_dir: str | Path, round_id: str, *, mode: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_round = _safe_slug(round_id)
    path = Path(base_dir) / f"{timestamp}_{safe_round}_{mode}"
    suffix = 1
    while path.exists():
        path = Path(base_dir) / f"{timestamp}_{safe_round}_{mode}_{suffix}"
        suffix += 1
    path.mkdir(parents=True, exist_ok=False)
    return path


def graph_category_summary(graph: WorldGraph) -> dict[str, Any]:
    entity_counts = Counter(entity.entity_type for entity in graph.entities)
    relation_counts = Counter(relationship.relation_type for relationship in graph.relationships)
    categories: dict[str, dict[str, Any]] = {}
    categorized_types: set[str] = set()
    for category, entity_types in KG_CATEGORY_ENTITY_TYPES.items():
        entity_type_counts = {
            entity_type: entity_counts.get(entity_type, 0)
            for entity_type in entity_types
            if entity_counts.get(entity_type, 0)
        }
        categorized_types.update(entity_types)
        categories[category] = {
            "entity_types": list(entity_types),
            "entity_type_counts": entity_type_counts,
            "entity_count": sum(entity_type_counts.values()),
            "sample_entities": [
                {"entity_id": entity.entity_id, "entity_type": entity.entity_type, "name": entity.name}
                for entity in graph.entities
                if entity.entity_type in entity_types
            ][:12],
        }
    uncategorized = {
        entity_type: count
        for entity_type, count in sorted(entity_counts.items())
        if entity_type not in categorized_types
    }
    return {
        "graph_id": graph.graph_id,
        "round_id": graph.round_id,
        "entity_count": len(graph.entities),
        "relationship_count": len(graph.relationships),
        "entity_counts": dict(sorted(entity_counts.items())),
        "relationship_counts": dict(sorted(relation_counts.items())),
        "categories": categories,
        "uncategorized_entity_type_counts": uncategorized,
    }


def _apply_claim_quality_gate(findings: list[Finding], *, match: MatchContext) -> ClaimQualityGateResult:
    filtered_findings: list[Finding] = []
    reason_counts: Counter[str] = Counter()
    rejection_samples: list[dict[str, Any]] = []
    input_claim_count = 0
    kept_claim_count = 0

    for finding in findings:
        kept_claims: list[dict[str, Any]] = []
        for claim in finding.evidence_claims:
            input_claim_count += 1
            reasons = _claim_rejection_reasons(claim, match=match)
            if reasons:
                reason_counts.update(reasons)
                if len(rejection_samples) < 8:
                    rejection_samples.append(
                        {
                            "claim_type": claim.get("claim_type"),
                            "team": claim.get("team"),
                            "source_title": claim.get("source_title"),
                            "reason": ",".join(reasons),
                            "claim": str(claim.get("claim") or "")[:180],
                        }
                    )
                continue
            kept_claims.append(claim)
            kept_claim_count += 1
        if kept_claims:
            filtered_findings.append(
                replace(
                    finding,
                    citations=sorted({claim["source_url"] for claim in kept_claims if claim.get("source_url")}),
                    evidence_claims=kept_claims,
                    summary=_quality_gate_summary(finding.summary, len(finding.evidence_claims), len(kept_claims)),
                )
            )
    return ClaimQualityGateResult(
        findings=filtered_findings,
        input_claim_count=input_claim_count,
        kept_claim_count=kept_claim_count,
        rejected_claim_count=input_claim_count - kept_claim_count,
        rejection_reasons=dict(sorted(reason_counts.items())),
        rejection_samples=rejection_samples,
    )


def _quality_gate_summary(summary: str, input_count: int, kept_count: int) -> str:
    if input_count == kept_count:
        return summary
    suffix = f" Quality gate kept {kept_count}/{input_count} claim(s)."
    return (summary.rstrip() + suffix).strip() if summary else suffix.strip()


def _source_error_summary(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]


def _log_claim_quality_gate(log: ScoutingRunLogger, result: ClaimQualityGateResult, *, source: str) -> None:
    if not result.rejected_claim_count:
        return
    log.event(
        "claim_quality_gate_complete",
        source=source,
        input_claim_count=result.input_claim_count,
        kept_claim_count=result.kept_claim_count,
        rejected_claim_count=result.rejected_claim_count,
        rejection_reasons=json.dumps(result.rejection_reasons, sort_keys=True),
        sample_rejections=json.dumps(result.rejection_samples, ensure_ascii=False, sort_keys=True),
    )


def _claim_count(findings: list[Finding]) -> int:
    return sum(len(finding.evidence_claims) for finding in findings)


def _filter_findings_as_of(findings: list[Finding], *, as_of_utc: str) -> list[Finding]:
    cutoff = _parse_temporal_gate_datetime(as_of_utc)
    filtered: list[Finding] = []
    for finding in findings:
        kept_claims = [
            claim
            for claim in finding.evidence_claims
            if _claim_is_available_as_of(claim, cutoff=cutoff)
        ]
        if not kept_claims:
            continue
        filtered.append(
            replace(
                finding,
                citations=sorted({claim["source_url"] for claim in kept_claims if claim.get("source_url")})
                or finding.citations,
                evidence_claims=kept_claims,
                summary=_temporal_gate_summary(finding.summary, len(finding.evidence_claims), len(kept_claims)),
            )
        )
    return filtered


def _temporal_gate_summary(summary: str, input_count: int, kept_count: int) -> str:
    if input_count == kept_count:
        return summary
    suffix = f" Temporal gate kept {kept_count}/{input_count} pre-cutoff claim(s)."
    return (summary.rstrip() + suffix).strip() if summary else suffix.strip()


def _claim_is_available_as_of(claim: dict[str, Any], *, cutoff: datetime) -> bool:
    claim_type = str(claim.get("claim_type") or "")
    if claim_type in {"live_score_event", "match_result"}:
        return False
    timestamp = _claim_available_datetime(claim)
    if timestamp is not None:
        return timestamp <= cutoff
    return _is_durable_undated_claim(claim)


def _claim_available_datetime(claim: dict[str, Any]) -> datetime | None:
    for key in (
        "available_at_utc",
        "available_at",
        "published_at_utc",
        "source_published_at",
        "source_published",
        "published",
        "source_published_date",
        "date",
    ):
        parsed = _try_parse_temporal_value(claim.get(key))
        if parsed is not None:
            return parsed
    metrics = claim.get("metrics") or {}
    if isinstance(metrics, dict):
        for key in ("txline_timestamp", "ts", "timestamp", "source_timestamp"):
            parsed = _try_parse_temporal_value(metrics.get(key))
            if parsed is not None:
                return parsed
    return None


def _is_durable_undated_claim(claim: dict[str, Any]) -> bool:
    source_kind = str(claim.get("source_kind") or "")
    claim_type = str(claim.get("claim_type") or "")
    if claim_type in {"match_schedule", "team_profile", "player_profile"}:
        return source_kind in {"reference", "api", "mcp", "existing_kg"}
    return False


def _try_parse_temporal_value(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_utc(float(value))
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10,16}", text):
        return _epoch_to_utc(float(text))
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    try:
        return _parse_temporal_gate_datetime(text)
    except ValueError:
        return None


def _parse_temporal_gate_datetime(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _epoch_to_utc(value: float) -> datetime:
    timestamp = value / 1000.0 if value > 10_000_000_000 else value
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _claim_rejection_reasons(claim: dict[str, Any], *, match: MatchContext) -> list[str]:
    reasons: list[str] = []
    claim_type = str(claim.get("claim_type") or "").strip()
    claim_text = str(claim.get("claim") or "").strip()
    source_title = str(claim.get("source_title") or "").strip()
    source_url = str(claim.get("source_url") or "").strip()
    source_quality = str(claim.get("source_quality") or "").strip().lower()
    source_kind = str(claim.get("source_kind") or "").strip().lower()
    text = _claim_search_text(claim)

    if not claim_type:
        reasons.append("missing_claim_type")
    if not claim_text:
        reasons.append("missing_claim")
    if not source_title and not source_url:
        reasons.append("missing_source")
    if source_quality == "weak":
        reasons.append("weak_source")
    if source_kind == "search" and source_quality != "strong":
        reasons.append("weak_search_aggregate")
    if _contains_off_domain_competition(text):
        reasons.append("off_domain_competition")
    if (
        claim_type == "market_snapshot"
        and str(claim.get("extraction_method") or "") == "polymarket_public_search_adapter"
    ):
        reasons.extend(_market_snapshot_rejection_reasons(claim, match=match, text=text))
    return list(dict.fromkeys(reasons))


def _claim_search_text(claim: dict[str, Any]) -> str:
    metrics = claim.get("metrics") if isinstance(claim.get("metrics"), dict) else {}
    metric_text = " ".join(str(metrics.get(key) or "") for key in ("slug", "event_slug", "question", "outcome"))
    return " ".join(
        str(value or "")
        for value in (
            claim.get("claim"),
            claim.get("subject"),
            claim.get("team"),
            claim.get("player"),
            claim.get("source_title"),
            claim.get("source_url"),
            metric_text,
        )
    ).casefold()


def _contains_off_domain_competition(text: str) -> bool:
    markers = (
        "american football",
        "afc women's asian cup",
        "basketball",
        "men's basketball",
        "nba",
        "nfl",
        "olympic",
        "olympics",
        "tokyo 2020",
        "usl super league women",
        "uswnt",
        "women's",
        "womens",
        "women ",
    )
    return any(marker in text for marker in markers)


def _market_snapshot_rejection_reasons(claim: dict[str, Any], *, match: MatchContext, text: str) -> list[str]:
    reasons: list[str] = []
    text_key = _team_key(text)
    if _team_key(match.home_team) not in text_key or _team_key(match.away_team) not in text_key:
        reasons.append("market_team_mismatch")

    match_year = (match.match_date or "")[:4]
    years = set(re.findall(r"\b20\d{2}\b", text))
    if match_year and years and any(year != match_year for year in years):
        reasons.append("market_year_mismatch")

    football_markers = ("fifwc", "fifa", "world cup", "soccer", "football")
    if not any(marker in text for marker in football_markers):
        reasons.append("market_missing_football_context")

    metrics = claim.get("metrics") if isinstance(claim.get("metrics"), dict) else {}
    if _as_bool(metrics.get("closed")) is True:
        reasons.append("market_closed")
    if _as_bool(metrics.get("active")) is False:
        reasons.append("market_inactive")
    return reasons


def merge_existing_graphs(base_graph: WorldGraph, existing_graphs: list[dict[str, Any]]) -> WorldGraph:
    entities = list(base_graph.entities)
    relationships = list(base_graph.relationships)
    for graph in existing_graphs:
        for entity in graph.get("entities", []):
            entity_id = str(entity.get("entity_id") or "")
            entity_type = str(entity.get("entity_type") or "")
            if not entity_id or not entity_type:
                continue
            entities.append(
                WorldEntity(
                    entity_id=entity_id,
                    entity_type=entity_type,  # type: ignore[arg-type]
                    name=str(entity.get("name") or entity_id),
                    attributes=dict(entity.get("attributes") or {}),
                )
            )
        for relationship in graph.get("relationships", []):
            source_id = str(relationship.get("source_id") or "")
            target_id = str(relationship.get("target_id") or "")
            relation_type = str(relationship.get("relation_type") or "")
            if not source_id or not target_id or not relation_type:
                continue
            relationships.append(
                WorldRelationship(
                    source_id=source_id,
                    relation_type=relation_type,
                    target_id=target_id,
                    weight=float(relationship.get("weight") or 1.0),
                    attributes=dict(relationship.get("attributes") or {}),
                )
            )
    return WorldGraph(
        graph_id=base_graph.graph_id,
        round_id=base_graph.round_id,
        entities=_dedupe_entities(entities),
        relationships=_dedupe_relationships(relationships),
    )


def _findings_from_source(
    source: SourceSpec,
    *,
    match_entity: dict[str, Any],
    timeout_seconds: int,
    public_cache_dir: str | Path | None,
    refresh_public_data: bool,
    include_x: bool,
    include_camel: bool,
    include_camel_deep: bool,
    camel_agent_count: int,
    include_telegram: bool,
    include_polygun: bool,
    include_deepseek_scout: bool,
    rescout_targets: list[dict[str, Any]],
    logger: ScoutingRunLogger | None = None,
) -> list[Finding]:
    if source.kind == "fixture":
        return list(openfootball_match_context_from_tournament_match(match_entity).findings)
    match = _empty_match_context(match_entity)
    if source.kind == "public":
        cache_dir = Path(source.locator) if source.locator else Path(public_cache_dir or _default_public_cache_dir())
        context = public_match_context_from_tournament_match(
            match_entity,
            cache_dir=cache_dir,
            refresh=refresh_public_data,
            timeout_seconds=timeout_seconds,
            include_x=include_x,
            include_camel=include_camel,
            include_camel_deep=include_camel_deep,
            camel_agent_count=camel_agent_count,
            include_telegram=include_telegram,
            include_polygun=include_polygun,
            include_deepseek_scout=include_deepseek_scout,
            rescout_targets=rescout_targets,
            logger=logger,
        )
        return list(context.findings)
    if source.kind == "deep-fixture":
        return _local_deep_findings(match)
    if source.kind == "url":
        document = _fetch_url_document(source.locator, timeout_seconds=timeout_seconds)
        return _findings_from_documents([document], source=source, match=match)
    if source.kind == "mcp-stdio":
        payload = _payload_from_mcp_stdio_source(source, timeout_seconds=timeout_seconds)
        return _findings_from_payload(payload, source=source, match=match)
    if source.kind in {"json", "mcp"}:
        raw = Path(source.locator).read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            document = RawScoutingDocument(
                title=f"{source.kind.upper()} source {Path(source.locator).name}",
                text=raw,
                url=f"{source.kind}://{_safe_slug(source.locator)}",
            )
            return _findings_from_documents([document], source=source, match=match)
        return _findings_from_payload(payload, source=source, match=match)
    if source.kind == "api":
        return _findings_from_api_source(source, match=match, timeout_seconds=timeout_seconds, logger=logger)
    if source.kind == "cli":
        configured_command = source.config.get("command")
        if isinstance(configured_command, list):
            command = [str(part) for part in configured_command]
        elif isinstance(configured_command, str):
            command = shlex.split(configured_command)
        else:
            command = shlex.split(source.locator)
        if not command:
            raise ScoutingSourceError("empty cli source command")
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            raise ScoutingSourceError(f"cli source failed with exit {completed.returncode}: {stderr}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return _findings_from_documents(
                [
                    RawScoutingDocument(
                        title=f"CLI source {command[0]}",
                        text=completed.stdout,
                        url=f"cli://{_safe_slug(source.locator)}",
                    )
                ],
                source=source,
                match=match,
            )
        return _findings_from_payload(payload, source=source, match=match)
    raise ScoutingSourceError(f"unsupported source kind '{source.kind}'")


def _findings_from_api_source(
    source: SourceSpec,
    *,
    match: MatchContext,
    timeout_seconds: int,
    logger: ScoutingRunLogger | None = None,
) -> list[Finding]:
    response = _api_source_response(source, timeout_seconds=timeout_seconds)
    adapter = _api_adapter_name(source)
    _log_api_payload_summary(logger, source=source, adapter=adapter, response=response, match=match)
    if adapter:
        payload = _payload_from_api_adapter(
            adapter,
            response.payload,
            source=source,
            match=match,
            request_url=response.url,
        )
        return _findings_from_payload(payload, source=source, match=match)
    if response.payload is not None:
        return _findings_from_payload(response.payload, source=source, match=match)
    return _findings_from_documents(
        [
            RawScoutingDocument(
                title=f"API source {response.url}",
                text=_document_text_from_response(response.raw, response.url),
                url=response.url,
            )
        ],
        source=source,
        match=match,
    )


def _api_source_response(source: SourceSpec, *, timeout_seconds: int) -> ApiSourceResponse:
    config = _api_source_config(source)
    url = _api_request_url(source, config)
    headers = {"User-Agent": "ColonyHarness/0.1 scout-to-kg"}
    configured_headers = _expand_env_refs(config.get("headers") or {}, source=source)
    if not isinstance(configured_headers, dict):
        raise ScoutingSourceError(f"{source.label} headers must be an object")
    headers.update({str(key): str(value) for key, value in configured_headers.items()})
    body = _api_request_body(config, headers=headers, source=source)
    method = str(config.get("method") or ("POST" if body is not None else "GET")).upper()
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            content_type = response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        if exc.code not in _api_empty_on_status_codes(config, source=source):
            raise
        raw = exc.read().decode("utf-8", errors="replace")
        content_type = exc.headers.get("Content-Type", "") if exc.headers else ""
        return ApiSourceResponse(url=url, content_type=content_type, raw=raw, payload=[])
    payload = _json_payload_from_api_response(raw, content_type=content_type)
    return ApiSourceResponse(url=url, content_type=content_type, raw=raw, payload=payload)


def _api_source_config(source: SourceSpec) -> dict[str, Any]:
    config = dict(source.config)
    if not config:
        config = {"kind": "api", "url": source.locator}
    return config


def _api_empty_on_status_codes(config: dict[str, Any], *, source: SourceSpec) -> set[int]:
    raw_codes = config.get("empty_on_status") or config.get("empty_on_status_codes") or []
    if isinstance(raw_codes, (str, int)):
        raw_codes = [raw_codes]
    if not isinstance(raw_codes, list):
        raise ScoutingSourceError(f"{source.label} empty_on_status must be a list of HTTP status codes")
    codes: set[int] = set()
    for raw_code in raw_codes:
        try:
            codes.add(int(raw_code))
        except (TypeError, ValueError) as exc:
            raise ScoutingSourceError(f"{source.label} empty_on_status contains an invalid HTTP status code") from exc
    return codes


def _api_request_url(source: SourceSpec, config: dict[str, Any]) -> str:
    url = str(config.get("url") or config.get("locator") or source.locator or "").strip()
    if not url:
        raise ScoutingSourceError("api source requires a url")
    url = str(_expand_env_refs(url, source=source))
    if not urllib.parse.urlparse(url).scheme and Path(url).exists():
        url = Path(url).resolve().as_uri()
    query = config.get("query") or config.get("params")
    if query is None:
        return url
    query = _expand_env_refs(query, source=source)
    if not isinstance(query, dict):
        raise ScoutingSourceError(f"{source.label} query must be an object")
    pairs = {str(key): value for key, value in query.items() if value is not None}
    if not pairs:
        return url
    parsed = urllib.parse.urlsplit(url)
    extra = urllib.parse.urlencode(pairs, doseq=True)
    combined_query = "&".join(part for part in (parsed.query, extra) if part)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, combined_query, parsed.fragment))


def _api_request_body(config: dict[str, Any], *, headers: dict[str, str], source: SourceSpec) -> bytes | None:
    if "json" in config:
        headers.setdefault("Content-Type", "application/json")
        return json.dumps(_expand_env_refs(config["json"], source=source), ensure_ascii=False).encode("utf-8")
    if "body" not in config:
        return None
    body = _expand_env_refs(config["body"], source=source)
    if isinstance(body, str):
        return body.encode("utf-8")
    headers.setdefault("Content-Type", "application/json")
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def _json_payload_from_api_response(raw: str, *, content_type: str) -> Any | None:
    if "json" in content_type.lower():
        return json.loads(raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _api_adapter_name(source: SourceSpec) -> str:
    raw = source.config.get("adapter") or source.config.get("schema") or source.config.get("format") or ""
    return re.sub(r"[^a-z0-9]+", "_", str(raw).strip().lower()).strip("_")


def _log_api_payload_summary(
    logger: ScoutingRunLogger | None,
    *,
    source: SourceSpec,
    adapter: str,
    response: ApiSourceResponse,
    match: MatchContext,
) -> None:
    if logger is None:
        return
    payload = response.payload
    if adapter in {
        "polymarket",
        "polymarket_market",
        "polymarket_public_search",
        "polymarket_sports_market",
        "polymarket_gamma",
        "polymarket_clob",
        "polymarket_gamma_clob",
    }:
        rows = _polymarket_market_rows(payload)
    elif adapter in {"wikidata", "wikidata_profiles", "wikidata_football_profiles"}:
        rows = _wikidata_binding_rows(payload)
    elif adapter in {"wikidata_entity_search", "wikidata_search"}:
        rows = _api_rows(payload)
    elif adapter in {"row_claims", "generic_rows", "generic_row_claims"} and source.config.get("rows_path"):
        rows = _rows_from_path(payload, str(source.config.get("rows_path") or ""))
    else:
        rows = _api_rows(payload)
    fields: dict[str, Any] = {
        "source": source.label,
        "adapter": adapter or "raw",
        "response_url": response.url,
        "content_type": response.content_type,
        "payload_type": type(payload).__name__ if payload is not None else "text",
        "row_count": len(rows),
    }
    if isinstance(payload, dict):
        fields["payload_keys"] = ",".join(str(key) for key in list(payload.keys())[:12])
    if adapter in {"txline", "txline_fixture", "txline_fixtures", "txline_fixture_snapshot", "txline_fixtures_snapshot"}:
        matched_rows = _txline_fixture_rows_for_match(rows, match)
        fields["matched_row_count"] = len(matched_rows)
        fields["matched_sample_rows"] = json.dumps(
            _sample_txline_fixture_rows(matched_rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
        fields["sample_rows"] = json.dumps(
            _sample_txline_fixture_rows(rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
    elif adapter in {"txline_odds", "txline_odds_snapshot"}:
        fields["sample_rows"] = json.dumps(
            _sample_txline_odds_rows(rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
    elif adapter in {"txline_scores", "txline_score", "txline_scores_snapshot", "txline_score_snapshot"}:
        fields["sample_rows"] = json.dumps(
            _sample_txline_score_rows(rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
    elif adapter in {
        "polymarket",
        "polymarket_market",
        "polymarket_public_search",
        "polymarket_sports_market",
        "polymarket_gamma",
        "polymarket_clob",
        "polymarket_gamma_clob",
    }:
        matched_rows = [row for row in rows if not _polymarket_market_rejection_reasons(row, match=match)]
        fields["matched_row_count"] = len(matched_rows)
        fields["matched_sample_rows"] = json.dumps(
            _sample_polymarket_market_rows(matched_rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
        fields["sample_rows"] = json.dumps(
            _sample_polymarket_market_rows(rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
    elif adapter in {"wikidata", "wikidata_profiles", "wikidata_football_profiles"}:
        matched_rows = _wikidata_profile_rows_for_match(rows, match)
        fields["matched_row_count"] = len(matched_rows)
        fields["matched_sample_rows"] = json.dumps(
            _sample_wikidata_profile_rows(matched_rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
        fields["sample_rows"] = json.dumps(
            _sample_wikidata_profile_rows(rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
    elif adapter in {"wikidata_entity_search", "wikidata_search"}:
        matched_rows = _wikidata_entity_search_rows_for_match(rows, source=source, match=match)
        fields["matched_row_count"] = len(matched_rows)
        fields["matched_sample_rows"] = json.dumps(
            _sample_wikidata_entity_search_rows(matched_rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
        fields["sample_rows"] = json.dumps(
            _sample_wikidata_entity_search_rows(rows, limit=5),
            ensure_ascii=False,
            sort_keys=True,
        )
    logger.event("api_payload_summary", **fields)


def _payload_from_api_adapter(
    adapter: str,
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    if payload is None:
        raise ScoutingSourceError(f"{source.label} adapter '{adapter}' requires a JSON response")
    if adapter in {"txline", "txline_fixture", "txline_fixtures", "txline_fixture_snapshot", "txline_fixtures_snapshot"}:
        return _payload_from_txline_fixtures(payload, source=source, match=match, request_url=request_url)
    if adapter in {"txline_odds", "txline_odds_snapshot"}:
        return _payload_from_txline_odds(payload, source=source, match=match, request_url=request_url)
    if adapter in {"txline_scores", "txline_score", "txline_scores_snapshot", "txline_score_snapshot"}:
        return _payload_from_txline_scores(payload, source=source, match=match, request_url=request_url)
    if adapter in {
        "polymarket",
        "polymarket_market",
        "polymarket_public_search",
        "polymarket_sports_market",
        "polymarket_gamma",
        "polymarket_clob",
        "polymarket_gamma_clob",
    }:
        return _payload_from_polymarket_public_search(
            payload,
            source=source,
            match=match,
            request_url=request_url,
            enrich_clob=adapter in {"polymarket_clob", "polymarket_gamma_clob"} or _as_bool(source.config.get("enrich_clob")) is True,
        )
    if adapter in {"wikidata", "wikidata_profiles", "wikidata_football_profiles"}:
        return _payload_from_wikidata_profiles(payload, source=source, match=match, request_url=request_url)
    if adapter in {"wikidata_entity_search", "wikidata_search"}:
        return _payload_from_wikidata_entity_search(payload, source=source, match=match, request_url=request_url)
    if adapter in {"row_claims", "generic_rows", "generic_row_claims"}:
        return _payload_from_row_claims(payload, source=source, match=match, request_url=request_url)
    raise ScoutingSourceError(f"unsupported api adapter '{adapter}'")


def _payload_from_polymarket_public_search(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
    enrich_clob: bool = False,
) -> dict[str, Any]:
    rows = _polymarket_market_rows(payload)
    max_rows = int(_float(source.config.get("max_rows"), 10.0))
    max_clob_requests = int(_float(source.config.get("max_clob_requests"), 16.0))
    clob_cache: dict[str, dict[str, Any]] = {}
    clob_request_count = 0
    claims: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()

    for row in rows:
        reasons = _polymarket_market_rejection_reasons(row, match=match)
        if reasons:
            rejected.update(reasons)
            continue
        outcomes = _json_list(_row_value(row, "outcomes", "Outcomes"))
        prices = _json_list(_row_value(row, "outcomePrices", "OutcomePrices", "prices"))
        token_ids = _json_list(_row_value(row, "clobTokenIds", "ClobTokenIds", "tokenIds"))
        if not outcomes:
            continue
        for item_index, outcome in enumerate(outcomes):
            token_id = token_ids[item_index] if item_index < len(token_ids) else ""
            clob_metrics: dict[str, Any] = {}
            if enrich_clob and token_id and clob_request_count < max_clob_requests:
                token_key = str(token_id)
                if token_key not in clob_cache:
                    clob_cache[token_key] = _polymarket_clob_metrics(token_key, source=source)
                    clob_request_count += 1
                clob_metrics = clob_cache[token_key]
            claims.append(
                _polymarket_claim(
                    row=row,
                    source=source,
                    match=match,
                    request_url=request_url,
                    outcome=outcome,
                    outcome_index=item_index,
                    price=prices[item_index] if item_index < len(prices) else "",
                    token_id=token_id,
                    clob_metrics=clob_metrics,
                )
            )
        if len(claims) >= max_rows * max(len(outcomes), 1):
            break

    if not claims:
        return {"findings": []}
    return {
        "findings": [
            {
                "finding_id": f"{match.round_id}:api:polymarket_market_snapshot",
                "scout_name": str(source.config.get("scout_name") or "polymarket_api_scout"),
                "source_type": "market",
                "finding_name": "polymarket_market_snapshot",
                "confidence": 0.74,
                "citations": sorted({claim["source_url"] for claim in claims if claim.get("source_url")}),
                "summary": (
                    f"Mapped {len(claims)} validated Polymarket market outcome claim(s)."
                    + (f" Enriched {sum(1 for claim in claims if claim.get('metrics', {}).get('clob_midpoint') is not None)} outcome(s) with CLOB." if enrich_clob else "")
                    + (f" Rejected rows: {dict(sorted(rejected.items()))}." if rejected else "")
                ),
                "evidence_claims": claims,
            }
        ]
    }


def _polymarket_market_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(payload, dict) and isinstance(payload.get("events"), list):
        for event in payload["events"]:
            if not isinstance(event, dict):
                continue
            event_fields = {
                "event_id": event.get("id"),
                "event_slug": event.get("slug"),
                "event_title": event.get("title") or event.get("name") or event.get("question"),
                "event_start_date": event.get("startDate") or event.get("start_date") or event.get("startTime"),
                "event_end_date": event.get("endDate") or event.get("end_date") or event.get("endTime"),
            }
            for market in event.get("markets") or []:
                if isinstance(market, dict):
                    rows.append({**event_fields, **market})
    if rows:
        return rows
    return _api_rows(payload)


def _polymarket_market_rejection_reasons(row: dict[str, Any], *, match: MatchContext) -> list[str]:
    reasons: list[str] = []
    question = str(_row_value(row, "question", "Question", "title") or "")
    slug = str(_row_value(row, "slug", "Slug") or "")
    event_slug = str(row.get("event_slug") or "")
    event_title = str(row.get("event_title") or "")
    text = " ".join([question, slug, event_slug, event_title]).casefold()
    text_key = _team_key(text)

    if _team_key(match.home_team) not in text_key or _team_key(match.away_team) not in text_key:
        reasons.append("market_team_mismatch")
    if _contains_off_domain_competition(text):
        reasons.append("off_domain_competition")
    if _contains_polymarket_prop_noise(text):
        reasons.append("market_prop_noise")
    match_year = (match.match_date or "")[:4]
    years = set(re.findall(r"\b20\d{2}\b", text))
    if match_year and years and any(year != match_year for year in years):
        reasons.append("market_year_mismatch")
    if not any(marker in text for marker in ("fifwc", "fifa", "world cup", "soccer", "football")):
        reasons.append("market_missing_football_context")
    if _as_bool(_row_value(row, "closed", "Closed")) is True:
        reasons.append("market_closed")
    if _as_bool(_row_value(row, "active", "Active")) is False:
        reasons.append("market_inactive")
    return list(dict.fromkeys(reasons))


def _contains_polymarket_prop_noise(text: str) -> bool:
    markers = (
        "announcer",
        "broadcast",
        "commercial",
        "commentator",
        "coin toss",
        "halftime show",
        "mention",
        "sponsor",
        "verizon",
        "visa",
        "will the announcers say",
    )
    return any(marker in text for marker in markers)


def _polymarket_claim(
    *,
    row: dict[str, Any],
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
    outcome: Any,
    outcome_index: int,
    price: Any,
    token_id: Any,
    clob_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    question = str(_row_value(row, "question", "Question", "title") or "Polymarket market")
    slug = str(_row_value(row, "slug", "Slug") or row.get("event_slug") or "")
    source_url = f"https://polymarket.com/event/{slug}" if slug else request_url
    active = _as_bool(_row_value(row, "active", "Active"))
    closed = _as_bool(_row_value(row, "closed", "Closed"))
    accepting_orders = _as_bool(_row_value(row, "acceptingOrders", "accepting_orders", "AcceptingOrders"))
    metrics = {
        "polymarket_id": _row_value(row, "id", "marketId"),
        "condition_id": _row_value(row, "conditionId", "condition_id"),
        "slug": slug,
        "event_id": row.get("event_id"),
        "event_slug": row.get("event_slug"),
        "question": question,
        "outcome": outcome,
        "outcome_index": outcome_index,
        "token_id": token_id,
        "price": price,
        "volume": _row_value(row, "volume", "volumeNum"),
        "liquidity": _row_value(row, "liquidity", "liquidityNum"),
        "active": active,
        "closed": closed,
        "accepting_orders": accepting_orders,
        "match_date": match.match_date,
    }
    if clob_metrics:
        metrics.update(clob_metrics)
    clob_midpoint = metrics.get("clob_midpoint")
    clob_suffix = f" CLOB midpoint is {clob_midpoint}." if clob_midpoint not in {None, ""} else ""
    return {
        "claim_type": "market_snapshot",
        "subject": f"Polymarket market: {question}",
        "team": "",
        "player": "",
        "claim": f"Polymarket validated football market '{question}' lists outcome '{outcome}' at Gamma price {price}.{clob_suffix}",
        "impact": "context_home",
        "confidence": 0.74,
        "source_title": str(source.config.get("title") or "Polymarket public search"),
        "source_url": source_url,
        "source_domain": _domain(source_url),
        "source_kind": "market_snapshot",
        "source_quality": "strong",
        "extraction_method": "polymarket_gamma_clob_adapter" if clob_metrics else "polymarket_public_search_adapter",
        "metrics": _scalar_metrics(metrics),
    }


def _polymarket_clob_metrics(token_id: str, *, source: SourceSpec) -> dict[str, Any]:
    configured_snapshot = source.config.get("clob_snapshots") or source.config.get("clob_snapshot")
    if isinstance(configured_snapshot, dict):
        token_snapshot = configured_snapshot.get(token_id) or configured_snapshot.get(str(token_id))
        if isinstance(token_snapshot, dict):
            return _polymarket_clob_metrics_from_snapshot(token_snapshot)

    base_url = str(source.config.get("clob_base_url") or "https://clob.polymarket.com").rstrip("/")
    timeout_seconds = int(_float(source.config.get("clob_timeout_seconds"), 5.0))
    metrics: dict[str, Any] = {}
    midpoint_payload = _polymarket_clob_json(f"{base_url}/midpoint", token_id=token_id, timeout_seconds=timeout_seconds)
    if isinstance(midpoint_payload, dict):
        mid = _row_value(midpoint_payload, "mid", "midpoint")
        if mid not in {None, ""}:
            metrics["clob_midpoint"] = _float_or_text(mid)
    if _as_bool(source.config.get("clob_book", True)) is not False:
        book_payload = _polymarket_clob_json(f"{base_url}/book", token_id=token_id, timeout_seconds=timeout_seconds)
        if isinstance(book_payload, dict):
            metrics.update(_polymarket_book_metrics(book_payload))
    return metrics


def _polymarket_clob_json(url: str, *, token_id: str, timeout_seconds: int) -> Any | None:
    try:
        request_url = url + "?" + urllib.parse.urlencode({"token_id": token_id})
        request = urllib.request.Request(
            request_url,
            headers={"User-Agent": "ColonyHarness/0.1 scout-to-kg", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


def _polymarket_clob_metrics_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    mid = _row_value(snapshot, "mid", "midpoint", "clob_midpoint")
    if mid not in {None, ""}:
        metrics["clob_midpoint"] = _float_or_text(mid)
    book = snapshot.get("book") if isinstance(snapshot.get("book"), dict) else snapshot
    metrics.update(_polymarket_book_metrics(book))
    return metrics


def _polymarket_book_metrics(book: dict[str, Any]) -> dict[str, Any]:
    bids = [row for row in _as_list(book.get("bids")) if isinstance(row, dict)]
    asks = [row for row in _as_list(book.get("asks")) if isinstance(row, dict)]
    bid_levels = _polymarket_price_levels(bids)
    ask_levels = _polymarket_price_levels(asks)
    metrics: dict[str, Any] = {}
    if book.get("timestamp") not in {None, ""}:
        metrics["clob_book_timestamp"] = book.get("timestamp")
    if bid_levels:
        best_bid = max(bid_levels, key=lambda item: item[0])
        metrics["clob_best_bid"] = _compact_float(best_bid[0])
        metrics["clob_best_bid_size"] = _compact_float(best_bid[1])
        metrics["clob_bid_depth"] = _compact_float(sum(size for _, size in bid_levels))
        metrics["clob_bid_levels"] = len(bid_levels)
    if ask_levels:
        best_ask = min(ask_levels, key=lambda item: item[0])
        metrics["clob_best_ask"] = _compact_float(best_ask[0])
        metrics["clob_best_ask_size"] = _compact_float(best_ask[1])
        metrics["clob_ask_depth"] = _compact_float(sum(size for _, size in ask_levels))
        metrics["clob_ask_levels"] = len(ask_levels)
    if "clob_best_bid" in metrics and "clob_best_ask" in metrics:
        metrics["clob_spread"] = _compact_float(float(metrics["clob_best_ask"]) - float(metrics["clob_best_bid"]))
    return metrics


def _polymarket_price_levels(rows: list[dict[str, Any]]) -> list[tuple[float, float]]:
    levels: list[tuple[float, float]] = []
    for row in rows:
        price = _optional_float(_row_value(row, "price", "p"))
        size = _optional_float(_row_value(row, "size", "s"))
        if price is None or size is None:
            continue
        levels.append((price, size))
    return levels


def _compact_float(value: float) -> int | float:
    return int(value) if value.is_integer() else round(value, 6)


def _payload_from_wikidata_profiles(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    rows = _wikidata_profile_rows_for_match(_wikidata_binding_rows(payload), match)
    max_players_per_team = int(_float(source.config.get("max_players_per_team"), 8.0))
    claims: list[dict[str, Any]] = []
    seen_teams: set[str] = set()
    seen_players_by_team: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        kind = str(row.get("kind") or "").strip().casefold()
        team = _canonical_match_team(str(row.get("teamLabel") or row.get("team") or ""), match)
        if not team:
            continue
        if kind == "team" or not row.get("playerLabel"):
            team_key = row.get("team_id") or team
            if team_key in seen_teams:
                continue
            seen_teams.add(str(team_key))
            claims.append(_wikidata_team_profile_claim(row, source=source, match=match, request_url=request_url, team=team))
            continue

        player = str(row.get("playerLabel") or "").strip()
        if not player:
            continue
        player_key = str(row.get("player_id") or player).casefold()
        team_seen = seen_players_by_team.setdefault(team, set())
        if player_key in team_seen or len(team_seen) >= max_players_per_team:
            continue
        team_seen.add(player_key)
        claims.append(_wikidata_player_profile_claim(row, source=source, match=match, request_url=request_url, team=team, player=player))

    if not claims:
        return {"findings": []}
    return {
        "findings": [
            {
                "finding_id": f"{match.round_id}:api:wikidata_profiles",
                "scout_name": str(source.config.get("scout_name") or "wikidata_profile_api_scout"),
                "source_type": "retrieval",
                "finding_name": "wikidata_profile_enrichment",
                "confidence": 0.68,
                "citations": sorted({claim["source_url"] for claim in claims if claim.get("source_url")}),
                "summary": f"Mapped {len(claims)} Wikidata team/player profile claim(s).",
                "evidence_claims": claims,
            }
        ]
    }


def _wikidata_team_profile_claim(
    row: dict[str, Any],
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
    team: str,
) -> dict[str, Any]:
    label = str(row.get("teamLabel") or team)
    description = str(row.get("teamDescription") or "")
    country = str(row.get("countryLabel") or "")
    coach = str(row.get("coachLabel") or "")
    source_url = str(row.get("team_url") or request_url)
    details = []
    if description:
        details.append(description)
    if country:
        details.append(f"country for sport: {country}")
    if coach:
        details.append(f"head coach: {coach}")
    return {
        "claim_type": "team_profile",
        "subject": team,
        "team": team,
        "player": "",
        "claim": f"Wikidata identifies {label} as the reference entity for {team}" + (f" ({'; '.join(details)})." if details else "."),
        "impact": _default_impact(team, match),
        "confidence": 0.72,
        "source_title": str(source.config.get("title") or "Wikidata football profile"),
        "source_url": source_url,
        "source_domain": _domain(source_url),
        "source_kind": "reference",
        "source_quality": "strong",
        "extraction_method": "wikidata_profiles_adapter",
        "metrics": _scalar_metrics(
            {
                "wikidata_team_id": row.get("team_id"),
                "wikidata_team_url": row.get("team_url"),
                "wikidata_team_label": label,
                "wikidata_team_description": description,
                "country": country,
                "country_id": row.get("country_id"),
                "head_coach": coach,
                "head_coach_id": row.get("coach_id"),
            }
        ),
    }


def _wikidata_player_profile_claim(
    row: dict[str, Any],
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
    team: str,
    player: str,
) -> dict[str, Any]:
    description = str(row.get("playerDescription") or "")
    position = str(row.get("positionLabel") or "")
    club = str(row.get("clubLabel") or "")
    source_url = str(row.get("player_url") or request_url)
    details = []
    if description:
        details.append(description)
    if position:
        details.append(f"position: {position}")
    if club:
        details.append(f"linked club/team: {club}")
    return {
        "claim_type": "player_profile",
        "subject": player,
        "team": team,
        "player": player,
        "claim": f"Wikidata links {player} to {team}" + (f" ({'; '.join(details)})." if details else "."),
        "impact": _default_impact(team, match),
        "confidence": 0.6,
        "source_title": str(source.config.get("title") or "Wikidata football profile"),
        "source_url": source_url,
        "source_domain": _domain(source_url),
        "source_kind": "reference",
        "source_quality": "strong",
        "extraction_method": "wikidata_profiles_adapter",
        "metrics": _scalar_metrics(
            {
                "wikidata_player_id": row.get("player_id"),
                "wikidata_player_url": row.get("player_url"),
                "wikidata_team_id": row.get("team_id"),
                "wikidata_team_url": row.get("team_url"),
                "position": position,
                "position_id": row.get("position_id"),
                "club": club,
                "club_id": row.get("club_id"),
                "reference_scope": "identity_profile_not_live_roster",
            }
        ),
    }


def _wikidata_binding_rows(payload: Any) -> list[dict[str, Any]]:
    bindings = None
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, dict):
            bindings = results.get("bindings")
        if bindings is None:
            bindings = payload.get("bindings")
    if not isinstance(bindings, list):
        return _api_rows(payload)

    rows: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        row: dict[str, Any] = {}
        for key, cell in binding.items():
            if isinstance(cell, dict):
                value = cell.get("value")
            else:
                value = cell
            if value is None:
                continue
            row[str(key)] = value
            if isinstance(value, str) and _is_wikidata_entity_url(value):
                row[f"{key}_url"] = value
                row[f"{key}_id"] = value.rsplit("/", 1)[-1]
        rows.append(row)
    return rows


def _wikidata_profile_rows_for_match(rows: list[dict[str, Any]], match: MatchContext) -> list[dict[str, Any]]:
    matched = []
    for row in rows:
        team_label = str(row.get("teamLabel") or row.get("team") or "")
        if _canonical_match_team(team_label, match):
            matched.append(row)
    return matched


def _sample_wikidata_profile_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows[: max(limit, 0)]:
        samples.append(
            {
                "kind": row.get("kind"),
                "team": row.get("teamLabel"),
                "team_id": row.get("team_id"),
                "player": row.get("playerLabel"),
                "player_id": row.get("player_id"),
                "position": row.get("positionLabel"),
                "club": row.get("clubLabel"),
            }
        )
    return samples


def _is_wikidata_entity_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(value)
    return parsed.netloc == "www.wikidata.org" and parsed.path.startswith("/entity/")


def _payload_from_wikidata_entity_search(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    rows = _wikidata_entity_search_rows_for_match(_api_rows(payload), source=source, match=match)
    max_rows = int(_float(source.config.get("max_rows"), 1.0))
    claims = [
        _wikidata_entity_search_claim(row, source=source, match=match, request_url=request_url)
        for row in rows[: max(max_rows, 0)]
    ]
    claims = [claim for claim in claims if claim]
    if not claims:
        return {"findings": []}
    team = str(claims[0].get("team") or source.config.get("team") or "team")
    return {
        "findings": [
            {
                "finding_id": f"{match.round_id}:api:wikidata_entity_search:{_safe_slug(team)}",
                "scout_name": str(source.config.get("scout_name") or "wikidata_entity_search_api_scout"),
                "source_type": "retrieval",
                "finding_name": "wikidata_entity_search",
                "confidence": 0.66,
                "citations": sorted({claim["source_url"] for claim in claims if claim.get("source_url")}),
                "summary": f"Mapped {len(claims)} Wikidata entity-search profile claim(s) for {team}.",
                "evidence_claims": claims,
            }
        ]
    }


def _wikidata_entity_search_rows_for_match(
    rows: list[dict[str, Any]],
    *,
    source: SourceSpec,
    match: MatchContext,
) -> list[dict[str, Any]]:
    configured_team = _canonical_match_team(str(source.config.get("team") or ""), match)
    matched = []
    for row in rows:
        label = str(_row_value(row, "label", "title") or "")
        description = str(row.get("description") or "")
        candidate_team = configured_team or _canonical_match_team(label, match)
        if not candidate_team:
            continue
        text = f"{label} {description}".casefold()
        label_text = label.casefold()
        if not any(marker in label_text for marker in ("national football team", "national soccer team")):
            continue
        if any(marker in label_text for marker in ("competitive record", "history of", "results", "statistics")):
            continue
        if "football" not in text and "soccer" not in text:
            continue
        matched.append({**row, "_matched_team": candidate_team})
    return matched


def _wikidata_entity_search_claim(
    row: dict[str, Any],
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any] | None:
    team = str(row.get("_matched_team") or _canonical_match_team(str(row.get("label") or ""), match) or "")
    if not team:
        return None
    label = str(row.get("label") or team)
    entity_id = str(row.get("id") or row.get("title") or "")
    description = str(row.get("description") or "")
    source_url = str(row.get("concepturi") or (f"https://www.wikidata.org/wiki/{entity_id}" if entity_id else request_url))
    return {
        "claim_type": "team_profile",
        "subject": team,
        "team": team,
        "player": "",
        "claim": f"Wikidata entity search returns {label}" + (f" ({entity_id})" if entity_id else "") + f" as a profile candidate for {team}" + (f": {description}." if description else "."),
        "impact": _default_impact(team, match),
        "confidence": 0.66,
        "source_title": str(source.config.get("title") or "Wikidata entity search"),
        "source_url": source_url,
        "source_domain": _domain(source_url),
        "source_kind": "reference",
        "source_quality": "strong",
        "extraction_method": "wikidata_entity_search_adapter",
        "metrics": _scalar_metrics(
            {
                "wikidata_id": entity_id,
                "wikidata_url": source_url,
                "wikidata_label": label,
                "wikidata_description": description,
                "repository": row.get("repository"),
                "match_language": row.get("match", {}).get("language") if isinstance(row.get("match"), dict) else "",
            }
        ),
    }


def _sample_wikidata_entity_search_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows[: max(limit, 0)]:
        samples.append(
            {
                "id": row.get("id") or row.get("title"),
                "label": row.get("label"),
                "description": row.get("description"),
                "matched_team": row.get("_matched_team"),
            }
        )
    return samples


def _payload_from_row_claims(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    rows_path = str(source.config.get("rows_path") or "").strip()
    rows = _rows_from_path(payload, rows_path) if rows_path else _generic_payload_rows(payload)
    row_filter = source.config.get("row_filter") or {}
    if row_filter and not isinstance(row_filter, dict):
        raise ScoutingSourceError(f"{source.label} row_filter must be an object")
    matched_rows = [
        row
        for row in rows
        if not row_filter or _row_claims_filter_matches(row, row_filter, match=match, request_url=request_url)
    ]
    max_rows = int(_float(source.config.get("max_rows"), 50.0))
    claim_specs = source.config.get("claims") or source.config.get("claim_templates") or source.config.get("claim")
    if isinstance(claim_specs, dict):
        claim_specs = [claim_specs]
    if not isinstance(claim_specs, list) or not claim_specs:
        raise ScoutingSourceError(f"{source.label} row_claims adapter requires a claim or claims template")
    claims: list[dict[str, Any]] = []
    for row in matched_rows[: max(max_rows, 0)]:
        for spec in claim_specs:
            if not isinstance(spec, dict):
                continue
            claims.extend(_claims_from_row_template(row, spec, source=source, match=match, request_url=request_url))
    finding_config = source.config.get("finding") or {}
    if not isinstance(finding_config, dict):
        raise ScoutingSourceError(f"{source.label} finding must be an object")
    if not claims:
        return {"findings": []}
    source_type = _safe_source_type(finding_config.get("source_type") or source.config.get("source_type") or "retrieval")
    scout_name = str(finding_config.get("scout_name") or source.config.get("scout_name") or f"{source.kind}_row_claims_scout")
    finding_name = str(finding_config.get("finding_name") or source.config.get("finding_name") or "row_claims_mapping")
    return {
        "findings": [
            {
                "finding_id": f"{match.round_id}:{source.kind}:{_safe_slug(scout_name)}:{_safe_slug(finding_name)}",
                "scout_name": scout_name,
                "source_type": source_type,
                "finding_name": finding_name,
                "confidence": _float(finding_config.get("confidence") or source.config.get("confidence"), 0.65),
                "citations": sorted({claim["source_url"] for claim in claims if claim.get("source_url")}),
                "summary": str(
                    finding_config.get("summary")
                    or f"Mapped {len(claims)} claims from {len(matched_rows)} row(s) using row_claims."
                ),
                "evidence_claims": claims,
            }
        ]
    }


def _claims_from_row_template(
    row: dict[str, Any],
    spec: dict[str, Any],
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> list[dict[str, Any]]:
    iter_values: list[Any | None] = [None]
    for_each = str(spec.get("for_each") or "").strip()
    if for_each:
        value = _template_lookup(for_each, row=row, match=match, item=None, item_index=0, request_url=request_url)
        iter_values = _json_list(value)
        if not iter_values:
            return []
    claims = []
    for item_index, item in enumerate(iter_values):
        rendered = {
            key: _render_template_value(value, row=row, match=match, item=item, item_index=item_index, request_url=request_url)
            for key, value in spec.items()
            if key != "for_each"
        }
        metrics = rendered.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        team = str(rendered.get("team") or "")
        canonical_team = _canonical_match_team(team, match) if team else ""
        if canonical_team:
            team = canonical_team
        elif not team:
            team = match.home_team
        source_url = str(rendered.get("source_url") or rendered.get("url") or request_url)
        claim = {
            **rendered,
            "claim_type": str(rendered.get("claim_type") or "team_profile"),
            "subject": str(rendered.get("subject") or team or match.home_team),
            "team": team,
            "player": str(rendered.get("player") or ""),
            "claim": str(rendered.get("claim") or ""),
            "impact": str(rendered.get("impact") or _default_impact(team, match)),
            "confidence": _float(rendered.get("confidence"), _float(source.config.get("confidence"), 0.65)),
            "source_title": str(rendered.get("source_title") or _source_title(source)),
            "source_url": source_url,
            "source_domain": str(rendered.get("source_domain") or _domain(source_url)),
            "source_kind": str(rendered.get("source_kind") or _source_kind(source)),
            "source_quality": str(rendered.get("source_quality") or _source_quality(source)),
            "extraction_method": str(rendered.get("extraction_method") or "row_claims_adapter"),
            "metrics": _scalar_metrics(metrics),
        }
        claims.append(claim)
    return claims


def _render_template_value(
    value: Any,
    *,
    row: dict[str, Any],
    match: MatchContext,
    item: Any,
    item_index: int,
    request_url: str,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _render_template_value(inner, row=row, match=match, item=item, item_index=item_index, request_url=request_url)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [
            _render_template_value(inner, row=row, match=match, item=item, item_index=item_index, request_url=request_url)
            for inner in value
        ]
    if not isinstance(value, str):
        return value
    full = TEMPLATE_REF_RE.fullmatch(value.strip())
    if full:
        return _template_lookup(full.group(1), row=row, match=match, item=item, item_index=item_index, request_url=request_url)

    def replace(match_obj: re.Match[str]) -> str:
        resolved = _template_lookup(
            match_obj.group(1),
            row=row,
            match=match,
            item=item,
            item_index=item_index,
            request_url=request_url,
        )
        return "" if resolved is None else str(resolved)

    return TEMPLATE_REF_RE.sub(replace, value)


def _template_lookup(
    expression: str,
    *,
    row: dict[str, Any],
    match: MatchContext,
    item: Any,
    item_index: int,
    request_url: str,
) -> Any:
    expression = expression.strip()
    if expression == "home_team":
        return match.home_team
    if expression == "away_team":
        return match.away_team
    if expression == "round_id":
        return match.round_id
    if expression == "request_url":
        return request_url
    if expression == "item":
        return item
    if expression == "item_index":
        return item_index
    return _row_path_value(row, expression, item_index=item_index)


def _row_path_value(row: dict[str, Any], expression: str, *, item_index: int) -> Any:
    value: Any = row
    for part in expression.split("."):
        if value is None:
            return None
        part = part.strip()
        index: int | None = None
        match = re.fullmatch(r"(.+)\[([^\]]+)\]", part)
        if match:
            part = match.group(1)
            raw_index = match.group(2).strip()
            if raw_index == "item_index":
                index = item_index
            else:
                try:
                    index = int(raw_index)
                except ValueError:
                    return None
        if isinstance(value, dict):
            value = _row_value(value, part)
        else:
            return None
        if index is not None:
            values = _json_list(value)
            if index < 0 or index >= len(values):
                return None
            value = values[index]
    return value


def _row_claims_filter_matches(
    row: dict[str, Any],
    row_filter: dict[str, Any],
    *,
    match: MatchContext,
    request_url: str,
) -> bool:
    field = str(row_filter.get("field") or "question")
    value = str(_row_path_value(row, field, item_index=0) or "")
    value_key = _team_key(value)
    contains_all = row_filter.get("contains_all")
    if contains_all is None and row_filter.get("match_teams", False):
        contains_all = ["{home_team}", "{away_team}"]
    if isinstance(contains_all, list):
        wanted = [
            _team_key(
                str(
                    _render_template_value(item, row=row, match=match, item=None, item_index=0, request_url=request_url)
                )
            )
            for item in contains_all
        ]
        if any(item and item not in value_key for item in wanted):
            return False
    contains_any = row_filter.get("contains_any")
    if isinstance(contains_any, list) and contains_any:
        wanted_any = [
            _team_key(
                str(
                    _render_template_value(item, row=row, match=match, item=None, item_index=0, request_url=request_url)
                )
            )
            for item in contains_any
        ]
        if not any(item and item in value_key for item in wanted_any):
            return False
    exclude_contains_any = row_filter.get("exclude_contains_any") or row_filter.get("contains_none")
    if isinstance(exclude_contains_any, list) and exclude_contains_any:
        blocked = [
            _team_key(
                str(
                    _render_template_value(item, row=row, match=match, item=None, item_index=0, request_url=request_url)
                )
            )
            for item in exclude_contains_any
        ]
        if any(item and item in value_key for item in blocked):
            return False
    return True


def _generic_payload_rows(payload: Any) -> list[dict[str, Any]]:
    rows = _rows_from_path(payload, "")
    if rows:
        return rows
    if isinstance(payload, dict):
        for path in ("data", "results", "items", "rows", "markets", "events[].markets[]"):
            rows = _rows_from_path(payload, path)
            if rows:
                return rows
    return []


def _rows_from_path(payload: Any, path: str) -> list[dict[str, Any]]:
    if not path:
        return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []
    values: list[Any] = [payload]
    for raw_part in path.split("."):
        part = raw_part.strip()
        expand = part.endswith("[]")
        if expand:
            part = part[:-2]
        next_values: list[Any] = []
        for value in values:
            if isinstance(value, dict):
                selected = _row_value(value, part)
                if expand:
                    if isinstance(selected, list):
                        next_values.extend(selected)
                    elif selected is not None:
                        decoded = _json_list(selected)
                        next_values.extend(decoded)
                elif selected is not None:
                    next_values.append(selected)
            elif expand and isinstance(value, list):
                next_values.extend(value)
        values = next_values
    return [value for value in values if isinstance(value, dict)]


def _payload_from_txline_fixtures(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    rows = _api_rows(payload)
    matched_rows = rows if source.config.get("match_filter") is False else _txline_fixture_rows_for_match(rows, match)
    claims: list[dict[str, Any]] = []
    for row in matched_rows:
        participant1 = str(_row_value(row, "Participant1", "participant1") or "")
        participant2 = str(_row_value(row, "Participant2", "participant2") or "")
        fixture_id = _row_value(row, "FixtureId", "fixtureId")
        competition = str(_row_value(row, "Competition", "competition") or "")
        start_time = _row_value(row, "StartTime", "startTime")
        participant1_is_home = _as_bool(_row_value(row, "Participant1IsHome", "participant1IsHome"))
        listed_home = participant1 if participant1_is_home is not False else participant2
        listed_away = participant2 if participant1_is_home is not False else participant1
        metrics = {
            "fixture_id": fixture_id,
            "competition": competition,
            "competition_id": _row_value(row, "CompetitionId", "competitionId"),
            "fixture_group_id": _row_value(row, "FixtureGroupId", "fixtureGroupId"),
            "start_time": start_time,
            "participant1": participant1,
            "participant2": participant2,
            "participant1_id": _row_value(row, "Participant1Id", "participant1Id"),
            "participant2_id": _row_value(row, "Participant2Id", "participant2Id"),
            "participant1_is_home": participant1_is_home,
            "txline_timestamp": _row_value(row, "Ts", "ts"),
        }
        claims.append(
            _txline_claim(
                source=source,
                request_url=request_url,
                match=match,
                claim_type="match_schedule",
                team=match.home_team,
                subject=f"{match.home_team} vs {match.away_team}",
                claim=(
                    f"TXLINE fixture snapshot lists {participant1} vs {participant2}"
                    f"{f' in {competition}' if competition else ''}"
                    f"{f' with fixture id {fixture_id}' if fixture_id is not None else ''}."
                ),
                impact="context_home",
                metrics={**metrics, "listed_home_team": listed_home, "listed_away_team": listed_away},
                extraction_method="txline_fixtures_adapter",
            )
        )
        for participant in (participant1, participant2):
            team = _canonical_match_team(participant, match) or participant
            if not team:
                continue
            claims.append(
                _txline_claim(
                    source=source,
                    request_url=request_url,
                    match=match,
                    claim_type="team_profile",
                    team=team,
                    subject=team,
                    claim=(
                        f"TXLINE fixture snapshot identifies {team} as a participant"
                        f"{f' in {competition}' if competition else ''}"
                        f" for fixture {fixture_id} against {participant2 if participant == participant1 else participant1}."
                    ),
                    impact=_default_impact(team, match),
                    metrics=metrics,
                    extraction_method="txline_fixtures_adapter",
                )
            )
    return _txline_payload(
        source=source,
        match=match,
        source_type="retrieval",
        finding_name="txline_fixture_snapshot",
        scout_name="txline_fixture_api_scout",
        summary=f"Mapped {len(claims)} TXLINE fixture claims from {len(matched_rows)} matching row(s).",
        claims=claims,
        request_url=request_url,
    )


def _payload_from_txline_odds(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    rows = _api_rows(payload)
    max_rows = int(_float(source.config.get("max_rows"), 20.0))
    claims = []
    for row in rows[:max(max_rows, 0)]:
        fixture_id = _row_value(row, "FixtureId", "fixtureId")
        bookmaker = str(_row_value(row, "Bookmaker", "bookmaker") or "bookmaker")
        odds_type = str(_row_value(row, "SuperOddsType", "superOddsType") or "market")
        price_names = _as_list(_row_value(row, "PriceNames", "priceNames"))
        prices = _as_list(_row_value(row, "Prices", "prices"))
        pct = _as_list(_row_value(row, "Pct", "pct"))
        price_labels = _txline_price_labels(price_names, match)
        price_summary = _price_summary(price_labels, prices)
        claims.append(
            _txline_claim(
                source=source,
                request_url=request_url,
                match=match,
                claim_type="market_snapshot",
                team=match.home_team,
                subject=f"TXLINE odds fixture {fixture_id}",
                claim=(
                    f"TXLINE odds snapshot for fixture {fixture_id} lists {bookmaker} "
                    f"{odds_type} prices{f': {price_summary}' if price_summary else '.'}"
                ),
                impact="context_home",
                confidence=0.74,
                metrics={
                    "fixture_id": fixture_id,
                    "message_id": _row_value(row, "MessageId", "messageId"),
                    "bookmaker": bookmaker,
                    "bookmaker_id": _row_value(row, "BookmakerId", "bookmakerId"),
                    "odds_type": odds_type,
                    "in_running": _as_bool(_row_value(row, "InRunning", "inRunning")),
                    "game_state": _row_value(row, "GameState", "gameState"),
                    "market_parameters": _row_value(row, "MarketParameters", "marketParameters"),
                    "market_period": _row_value(row, "MarketPeriod", "marketPeriod"),
                    "price_names": price_names,
                    "price_labels": price_labels,
                    "prices": prices,
                    "pct": pct,
                    "txline_timestamp": _row_value(row, "Ts", "ts"),
                },
                extraction_method="txline_odds_adapter",
            )
        )
    return _txline_payload(
        source=source,
        match=match,
        source_type="odds",
        finding_name="txline_odds_snapshot",
        scout_name="txline_odds_api_scout",
        summary=f"Mapped {len(claims)} TXLINE odds snapshot claim(s).",
        claims=claims,
        request_url=request_url,
    )


def _payload_from_txline_scores(
    payload: Any,
    *,
    source: SourceSpec,
    match: MatchContext,
    request_url: str,
) -> dict[str, Any]:
    rows = _api_rows(payload)
    max_rows = int(_float(source.config.get("max_rows"), 20.0))
    claims = []
    for row in rows[:max(max_rows, 0)]:
        fixture_id = _row_value(row, "fixtureId", "FixtureId")
        action = str(_row_value(row, "action", "Action") or "score update")
        game_state = str(_row_value(row, "gameState", "GameState") or "")
        claim_type = _txline_score_claim_type(action=action, game_state=game_state)
        is_live_score = claim_type == "live_score_event"
        claims.append(
            _txline_claim(
                source=source,
                request_url=request_url,
                match=match,
                claim_type=claim_type,
                team=match.home_team,
                subject=f"TXLINE score fixture {fixture_id}",
                claim=(
                    f"TXLINE {'score' if is_live_score else 'coverage'} snapshot for fixture {fixture_id} reports action {action}"
                    f"{f' in game state {game_state}' if game_state else ''}."
                ),
                impact="context_home",
                confidence=0.72 if is_live_score else 0.68,
                metrics={
                    "fixture_id": fixture_id,
                    "action": action,
                    "game_state": game_state,
                    "start_time": _row_value(row, "startTime", "StartTime"),
                    "sequence": _row_value(row, "seq", "Seq"),
                    "txline_timestamp": _row_value(row, "ts", "Ts"),
                    "clock": _row_value(row, "clock", "Clock"),
                    "confirmed": _as_bool(_row_value(row, "confirmed", "Confirmed")),
                },
                extraction_method="txline_scores_adapter",
            )
        )
    return _txline_payload(
        source=source,
        match=match,
        source_type="stats",
        finding_name="txline_score_snapshot",
        scout_name="txline_score_api_scout",
        summary=f"Mapped {len(claims)} TXLINE score/status claim(s).",
        claims=claims,
        request_url=request_url,
    )


def _txline_payload(
    *,
    source: SourceSpec,
    match: MatchContext,
    source_type: SourceType,
    finding_name: str,
    scout_name: str,
    summary: str,
    claims: list[dict[str, Any]],
    request_url: str,
) -> dict[str, Any]:
    if not claims:
        return {"findings": []}
    return {
        "findings": [
            {
                "finding_id": f"{match.round_id}:api:{finding_name}",
                "scout_name": scout_name,
                "source_type": source_type,
                "finding_name": finding_name,
                "confidence": 0.74,
                "citations": [request_url],
                "summary": summary,
                "evidence_claims": claims,
            }
        ]
    }


def _txline_claim(
    *,
    source: SourceSpec,
    request_url: str,
    match: MatchContext,
    claim_type: str,
    team: str,
    subject: str,
    claim: str,
    impact: str,
    metrics: dict[str, Any],
    extraction_method: str,
    confidence: float = 0.78,
) -> dict[str, Any]:
    return {
        "claim_type": claim_type,
        "subject": subject,
        "team": team,
        "player": "",
        "claim": claim,
        "impact": impact or _default_impact(team, match),
        "confidence": confidence,
        "source_title": str(source.config.get("title") or "TXLINE API snapshot"),
        "source_url": request_url,
        "source_domain": _domain(request_url),
        "source_kind": "api",
        "source_quality": "strong",
        "extraction_method": extraction_method,
        "metrics": _scalar_metrics(metrics),
    }


def _scalar_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _scalar_metric_value(value) for key, value in metrics.items()}


def _scalar_metric_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _api_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "fixtures", "odds", "scores", "items", "results", "rows", "search"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if any(key in payload for key in ("FixtureId", "fixtureId", "Participant1", "participant1")):
            return [payload]
    return []


def _txline_fixture_rows_for_match(rows: list[dict[str, Any]], match: MatchContext) -> list[dict[str, Any]]:
    matched = []
    for row in rows:
        participant1 = str(_row_value(row, "Participant1", "participant1") or "")
        participant2 = str(_row_value(row, "Participant2", "participant2") or "")
        if (
            _team_matches(participant1, match.home_team)
            and _team_matches(participant2, match.away_team)
        ) or (
            _team_matches(participant1, match.away_team)
            and _team_matches(participant2, match.home_team)
        ):
            matched.append(row)
    return matched


def _sample_txline_fixture_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows[: max(limit, 0)]:
        samples.append(
            {
                "fixture_id": _row_value(row, "FixtureId", "fixtureId"),
                "competition": _row_value(row, "Competition", "competition"),
                "competition_id": _row_value(row, "CompetitionId", "competitionId"),
                "participant1": _row_value(row, "Participant1", "participant1"),
                "participant2": _row_value(row, "Participant2", "participant2"),
                "start_time": _row_value(row, "StartTime", "startTime"),
                "ts": _row_value(row, "Ts", "ts"),
            }
        )
    return samples


def _sample_txline_odds_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows[: max(limit, 0)]:
        samples.append(
            {
                "fixture_id": _row_value(row, "FixtureId", "fixtureId"),
                "message_id": _row_value(row, "MessageId", "messageId"),
                "bookmaker": _row_value(row, "Bookmaker", "bookmaker"),
                "odds_type": _row_value(row, "SuperOddsType", "superOddsType"),
                "game_state": _row_value(row, "GameState", "gameState"),
                "market_period": _row_value(row, "MarketPeriod", "marketPeriod"),
                "price_names": _as_list(_row_value(row, "PriceNames", "priceNames"))[:4],
                "prices": _as_list(_row_value(row, "Prices", "prices"))[:4],
                "ts": _row_value(row, "Ts", "ts"),
            }
        )
    return samples


def _sample_txline_score_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows[: max(limit, 0)]:
        samples.append(
            {
                "fixture_id": _row_value(row, "fixtureId", "FixtureId"),
                "action": _row_value(row, "action", "Action"),
                "game_state": _row_value(row, "gameState", "GameState"),
                "sequence": _row_value(row, "sequence", "Sequence"),
                "confirmed": _row_value(row, "confirmed", "Confirmed"),
                "ts": _row_value(row, "ts", "Ts"),
            }
        )
    return samples


def _sample_polymarket_market_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    samples = []
    for row in rows[: max(limit, 0)]:
        samples.append(
            {
                "id": _row_value(row, "id", "marketId"),
                "question": _row_value(row, "question", "Question", "title"),
                "slug": _row_value(row, "slug", "Slug"),
                "event_slug": row.get("event_slug"),
                "active": _row_value(row, "active", "Active"),
                "closed": _row_value(row, "closed", "Closed"),
            }
        )
    return samples


def _canonical_match_team(candidate: str, match: MatchContext) -> str:
    if _team_matches(candidate, match.home_team):
        return match.home_team
    if _team_matches(candidate, match.away_team):
        return match.away_team
    return ""


def _team_matches(candidate: str, team: str) -> bool:
    candidate_key = _team_key(candidate)
    team_key = _team_key(team)
    return bool(candidate_key and team_key and (candidate_key == team_key or candidate_key in team_key or team_key in candidate_key))


def _team_key(value: str) -> str:
    stopwords = {"fc", "cf", "national", "team", "men", "mens", "women", "womens"}
    tokens = [
        token
        for token in re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).split()
        if token not in stopwords
    ]
    return " ".join(tokens)


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    lowered = {str(key).casefold(): value for key, value in row.items()}
    for key in keys:
        lowered_key = key.casefold()
        if lowered_key in lowered:
            return lowered[lowered_key]
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    return []


def _float_or_text(value: Any) -> Any:
    if value in {None, ""}:
        return ""
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return str(value)


def _price_summary(names: list[Any], prices: list[Any]) -> str:
    pairs = []
    for index, price in enumerate(prices[:6]):
        name = str(names[index]) if index < len(names) else f"price_{index + 1}"
        pairs.append(f"{name}={price}")
    return ", ".join(pairs)


def _txline_price_labels(names: list[Any], match: MatchContext) -> list[str]:
    labels = []
    for index, name in enumerate(names):
        name_text = str(name or "").strip()
        name_key = _team_key(name_text)
        if name_key in {"part1", "participant1", "p1", "team1", "home"}:
            labels.append(match.home_team)
        elif name_key in {"part2", "participant2", "p2", "team2", "away"}:
            labels.append(match.away_team)
        elif name_key in {"draw", "x", "tie"}:
            labels.append("draw")
        else:
            labels.append(name_text or f"price_{index + 1}")
    return labels


def _txline_score_claim_type(*, action: str, game_state: str) -> str:
    action_key = _team_key(action)
    state_key = _team_key(game_state)
    if state_key in {"scheduled", "pre match", "prematch", "not started"}:
        return "coverage_status"
    if action_key in {"comment", "coverage update", "coverageupdate"}:
        return "coverage_status"
    return "live_score_event"


def _expand_env_refs(value: Any, *, source: SourceSpec) -> Any:
    missing: set[str] = set()
    expanded = _expand_env_refs_inner(value, missing=missing)
    if missing:
        names = ", ".join(sorted(missing))
        raise ScoutingSourceError(f"{source.label} is missing environment variable(s): {names}")
    return expanded


def _expand_env_refs_inner(value: Any, *, missing: set[str]) -> Any:
    if isinstance(value, str):
        if value.startswith("env:"):
            name = value[4:].strip()
            if name not in os.environ:
                missing.add(name)
                return ""
            return os.environ[name]

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                missing.add(name)
                return ""
            return os.environ[name]

        return ENV_REF_RE.sub(replace, value)
    if isinstance(value, list):
        return [_expand_env_refs_inner(item, missing=missing) for item in value]
    if isinstance(value, dict):
        return {key: _expand_env_refs_inner(item, missing=missing) for key, item in value.items()}
    return value


def _payload_from_mcp_stdio_source(source: SourceSpec, *, timeout_seconds: int) -> Any:
    config = _mcp_stdio_config(source)
    command = _mcp_command(config)
    tool_name = str(config.get("tool") or config.get("tool_name") or "").strip()
    if not tool_name:
        raise ScoutingSourceError("mcp-stdio source requires a tool name")
    arguments = config.get("arguments") or config.get("args") or {}
    if not isinstance(arguments, dict):
        raise ScoutingSourceError("mcp-stdio arguments must be an object")
    cwd = str(config.get("cwd") or "") or None
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    try:
        _write_json_rpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "colony-scout-to-kg", "version": "0.1"},
                },
            },
        )
        _write_json_rpc(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _write_json_rpc(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        response = _read_json_rpc_response(process, response_id=2, timeout_seconds=timeout_seconds)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except Exception:
                    pass
    if response.get("error"):
        raise ScoutingSourceError(f"mcp-stdio tool call failed: {response['error']}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise ScoutingSourceError("mcp-stdio tool call returned no result object")
    return _payload_from_mcp_tool_result(result, source=source, tool_name=tool_name)


def _mcp_stdio_config(source: SourceSpec) -> dict[str, Any]:
    config = dict(source.config)
    if source.locator and Path(source.locator).exists():
        loaded = json.loads(Path(source.locator).read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ScoutingSourceError(f"mcp-stdio config must be an object: {source.locator}")
        config = {**loaded, **config}
    return config


def _mcp_command(config: dict[str, Any]) -> list[str]:
    command = config.get("command")
    if isinstance(command, str):
        parsed = shlex.split(command)
    elif isinstance(command, list):
        parsed = [str(part) for part in command]
    else:
        parsed = []
    if not parsed:
        raise ScoutingSourceError("mcp-stdio source requires a command")
    return parsed


def _write_json_rpc(process: subprocess.Popen, payload: dict[str, Any]) -> None:
    if process.stdin is None:
        raise ScoutingSourceError("mcp-stdio process stdin is unavailable")
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()


def _read_json_rpc_response(
    process: subprocess.Popen,
    *,
    response_id: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    if process.stdout is None:
        raise ScoutingSourceError("mcp-stdio process stdout is unavailable")
    lines: queue.Queue[str] = queue.Queue()

    def reader() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)

    threading.Thread(target=reader, daemon=True).start()
    deadline = datetime.now().timestamp() + timeout_seconds
    while datetime.now().timestamp() < deadline:
        remaining = max(deadline - datetime.now().timestamp(), 0.05)
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == response_id:
            return message
    raise ScoutingSourceError(f"timed out waiting for mcp-stdio response id={response_id}")


def _payload_from_mcp_tool_result(result: dict[str, Any], *, source: SourceSpec, tool_name: str) -> Any:
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    content = result.get("content")
    if not isinstance(content, list):
        return result
    text_parts: list[str] = []
    documents: list[dict[str, str]] = []
    for index, part in enumerate(content):
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or part.get("content") or "")
        if not text:
            continue
        text_parts.append(text)
        documents.append(
            {
                "title": str(part.get("title") or f"MCP {tool_name} result {index + 1}"),
                "url": str(part.get("uri") or f"mcp-stdio://{_safe_slug(tool_name)}/{index + 1}"),
                "text": text,
            }
        )
    if len(text_parts) == 1:
        try:
            return json.loads(text_parts[0])
        except json.JSONDecodeError:
            pass
    if documents:
        return {"documents": documents}
    return {"documents": [{"title": _source_title(source), "url": _fallback_source_url(source), "text": json.dumps(result)}]}


def _findings_from_payload(payload: Any, *, source: SourceSpec, match: MatchContext) -> list[Finding]:
    if isinstance(payload, list):
        if _looks_like_documents(payload):
            return _findings_from_documents(_documents_from_payload(payload, source=source), source=source, match=match)
        return [_finding_from_claims(payload, source=source, match=match, finding_index=0)]
    if not isinstance(payload, dict):
        document = RawScoutingDocument(
            title=_source_title(source),
            text=str(payload),
            url=_fallback_source_url(source),
        )
        return _findings_from_documents([document], source=source, match=match)
    documents = _documents_from_payload(payload, source=source)
    if documents:
        return _findings_from_documents(documents, source=source, match=match)
    if isinstance(payload.get("findings"), list):
        findings = []
        for index, row in enumerate(payload["findings"]):
            if not isinstance(row, dict):
                raise ScoutingSourceError(f"{source.label} finding #{index + 1} is not an object")
            claims = row.get("evidence_claims") or row.get("claims") or []
            findings.append(_finding_from_row(row, claims=claims, source=source, match=match, finding_index=index))
        return findings
    claims = payload.get("evidence_claims") or payload.get("claims")
    if isinstance(claims, list):
        return [_finding_from_claims(claims, source=source, match=match, finding_index=0)]
    raise ScoutingSourceError(
        f"{source.label} must include findings, evidence_claims, claims, documents, items, or text"
    )


def _findings_from_documents(
    documents: list[RawScoutingDocument],
    *,
    source: SourceSpec,
    match: MatchContext,
) -> list[Finding]:
    claims: list[dict[str, Any]] = []
    citations: list[str] = []
    for document in documents:
        source_url = document.url or _fallback_source_url(source)
        text = _combine_document_text(document)
        if not text:
            continue
        citations.append(source_url)
        claims.extend(
            claim.to_dict()
            for claim in _extract_claims_from_text(
                text=text,
                source_title=document.title or _source_title(source),
                source_url=source_url,
                source_published=document.published,
                home_team=match.home_team,
                away_team=match.away_team,
            )
        )
    normalized_claims = [_normalize_claim(claim, source=source, match=match) for claim in _dedupe_claim_dicts(claims)]
    if not normalized_claims:
        return []
    return [
        Finding(
            finding_id=f"{match.round_id}:{source.kind}:document_scout",
            scout_name=f"{source.kind}_document_scout",
            access_level="public",
            source_type=_source_type_for_source(source),
            finding_name=f"{source.kind}_document_extraction",
            home_probability=None,
            home_delta=None,
            confidence=0.58,
            cost=0.0,
            citations=sorted(set(citation for citation in citations if citation)),
            summary=f"Scraped/extracted {len(normalized_claims)} scouting claims from {len(documents)} {source.kind} document(s).",
            evidence_claims=normalized_claims,
        )
    ]


def _documents_from_payload(payload: Any, *, source: SourceSpec) -> list[RawScoutingDocument]:
    if isinstance(payload, dict):
        documents = payload.get("documents")
        if isinstance(documents, list):
            return [_document_from_payload_item(item, source=source) for item in documents]
        items = payload.get("items") or payload.get("results") or payload.get("articles")
        if isinstance(items, list):
            return [_document_from_payload_item(item, source=source) for item in items]
        text = payload.get("text") or payload.get("content") or payload.get("body")
        if isinstance(text, str):
            return [_document_from_payload_item(payload, source=source)]
        return []
    if isinstance(payload, list):
        return [_document_from_payload_item(item, source=source) for item in payload]
    if isinstance(payload, str):
        return [RawScoutingDocument(title=_source_title(source), text=payload, url=_fallback_source_url(source))]
    return []


def _looks_like_documents(rows: list[Any]) -> bool:
    if not rows:
        return False
    if any(isinstance(row, str) for row in rows):
        return True
    if not all(isinstance(row, dict) for row in rows):
        return False
    claim_markers = {"claim", "claim_type", "impact", "evidence_claims", "claims"}
    document_markers = {"text", "content", "body", "snippet", "description", "title", "url", "link", "source_url"}
    has_document_marker = any(any(key in row for key in document_markers) for row in rows)
    has_claim_marker = any(any(key in row for key in claim_markers) for row in rows)
    return has_document_marker and not has_claim_marker


def _document_from_payload_item(item: Any, *, source: SourceSpec) -> RawScoutingDocument:
    if isinstance(item, str):
        return RawScoutingDocument(title=_source_title(source), text=item, url=_fallback_source_url(source))
    if not isinstance(item, dict):
        return RawScoutingDocument(title=_source_title(source), text=str(item), url=_fallback_source_url(source))
    title = str(item.get("title") or item.get("source_title") or item.get("name") or _source_title(source))
    url = str(item.get("url") or item.get("link") or item.get("source_url") or _fallback_source_url(source))
    published = str(item.get("published") or item.get("source_published") or item.get("date") or "")
    text_parts = [
        str(item.get(key) or "")
        for key in ("title", "snippet", "description", "summary", "text", "content", "body")
        if item.get(key)
    ]
    return RawScoutingDocument(
        title=title,
        text=_document_text_from_response(" ".join(text_parts), url),
        url=url,
        published=published,
    )


def _fetch_url_document(url: str, *, timeout_seconds: int) -> RawScoutingDocument:
    request = urllib.request.Request(url, headers={"User-Agent": "ColonyHarness/0.1 scout-to-kg"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8", errors="replace")
        content_type = response.headers.get("Content-Type", "")
    title, text = _extract_document_title_and_text(raw, url=url, content_type=content_type)
    return RawScoutingDocument(title=title, text=text, url=url)


def _extract_document_title_and_text(raw: str, *, url: str, content_type: str = "") -> tuple[str, str]:
    if "html" in content_type.lower() or re.search(r"<(?:html|body|article|p|h1|h2)\b", raw, flags=re.I):
        title, text = _SourceDocumentParser.extract(raw)
        return title or _title_from_url(url), text
    return _title_from_url(url), _clean_document_text(raw)


def _document_text_from_response(raw: str, url: str) -> str:
    return _extract_document_title_and_text(raw, url=url)[1]


def _combine_document_text(document: RawScoutingDocument) -> str:
    parts = [document.title, document.text]
    return _clean_document_text(" ".join(part for part in parts if part))


def _dedupe_claim_dicts(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for claim in claims:
        key = (
            str(claim.get("claim_type") or ""),
            str(claim.get("team") or ""),
            str(claim.get("player") or claim.get("subject") or ""),
            str(claim.get("claim") or "")[:160],
        )
        normalized_key = tuple(part.strip().casefold() for part in key)
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        deduped.append(claim)
    return deduped


class _SourceDocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self._capture_tag = ""
        self._current: list[str] = []
        self._parts: list[str] = []
        self._in_title = False
        self._title_parts: list[str] = []

    @classmethod
    def extract(cls, html: str) -> tuple[str, str]:
        parser = cls()
        parser.feed(html)
        parser.close()
        title = _clean_document_text(" ".join(parser._title_parts))
        text = _clean_document_text(" ".join(parser._parts))
        return title, text[:8000]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in {"p", "li", "h1", "h2", "h3", "article"} and not self._skip:
            self._capture_tag = tag
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == self._capture_tag:
            text = _clean_document_text(" ".join(self._current))
            if len(text) >= 30:
                self._parts.append(text)
            self._capture_tag = ""
            self._current = []

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        if self._capture_tag:
            self._current.append(data)


def _finding_from_row(
    row: dict[str, Any],
    *,
    claims: Any,
    source: SourceSpec,
    match: MatchContext,
    finding_index: int,
) -> Finding:
    if not isinstance(claims, list):
        raise ScoutingSourceError(f"{source.label} finding #{finding_index + 1} claims must be a list")
    normalized_claims = [
        _normalize_claim(claim, source=source, match=match)
        for claim in claims
        if isinstance(claim, dict)
    ]
    source_type = _safe_source_type(row.get("source_type"))
    probability = _optional_float(row.get("home_probability"))
    market = match.market_home_probability
    return Finding(
        finding_id=str(row.get("finding_id") or f"{match.round_id}:{source.kind}:{finding_index + 1}"),
        scout_name=str(row.get("scout_name") or f"{source.kind}_dataset_scout"),
        access_level=str(row.get("access_level") or "public"),  # type: ignore[arg-type]
        source_type=source_type,
        finding_name=str(row.get("finding_name") or f"{source.kind}_dataset_read"),
        home_probability=probability,
        home_delta=None if probability is None else round(probability - market, 4),
        confidence=_float(row.get("confidence"), 0.65),
        cost=_float(row.get("cost"), 0.0),
        citations=[str(item) for item in row.get("citations") or []],
        summary=str(row.get("summary") or f"Normalized {len(normalized_claims)} claims from {source.label}."),
        evidence_claims=normalized_claims,
    )


def _finding_from_claims(
    claims: list[Any],
    *,
    source: SourceSpec,
    match: MatchContext,
    finding_index: int,
) -> Finding:
    normalized_claims = [
        _normalize_claim(claim, source=source, match=match)
        for claim in claims
        if isinstance(claim, dict)
    ]
    return Finding(
        finding_id=f"{match.round_id}:{source.kind}:{finding_index + 1}",
        scout_name=f"{source.kind}_dataset_scout",
        access_level="public",
        source_type=_source_type_for_source(source),
        finding_name=f"{source.kind}_dataset_claims",
        home_probability=None,
        home_delta=None,
        confidence=0.65,
        cost=0.0,
        citations=[claim["source_url"] for claim in normalized_claims if claim.get("source_url")],
        summary=f"Normalized {len(normalized_claims)} claims from {source.label}.",
        evidence_claims=normalized_claims,
    )


def _normalize_claim(claim: dict[str, Any], *, source: SourceSpec, match: MatchContext) -> dict[str, Any]:
    source_url = str(claim.get("source_url") or "")
    source_title = str(claim.get("source_title") or _source_title(source))
    source_kind = str(claim.get("source_kind") or _source_kind(source))
    source_quality = str(claim.get("source_quality") or _source_quality(source))
    if source.kind in {"mcp", "mcp-stdio"} and source_kind in {"", "web"}:
        source_kind = _source_kind(source)
    if source.kind in {"mcp", "mcp-stdio"} and source_quality in {"", "medium"}:
        source_quality = _source_quality(source)
    team = str(claim.get("team") or "") if "team" in claim else str(_infer_team(claim, match) or "")
    impact = str(claim.get("impact") or _default_impact(team, match) or "context_home")
    normalized = {
        **claim,
        "claim_type": str(claim.get("claim_type") or "team_profile"),
        "subject": str(claim.get("subject") or claim.get("player") or team or match.home_team),
        "team": team,
        "player": str(claim.get("player") or ""),
        "claim": str(claim.get("claim") or ""),
        "impact": impact,
        "confidence": _float(claim.get("confidence"), 0.62),
        "source_title": source_title,
        "source_url": source_url,
        "source_domain": str(claim.get("source_domain") or _domain(source_url)),
        "source_kind": source_kind,
        "source_quality": source_quality,
        "extraction_method": str(claim.get("extraction_method") or f"{source.kind}_dataset"),
        "metrics": dict(claim.get("metrics") or {}),
    }
    return normalized


def _local_deep_findings(match: MatchContext) -> list[Finding]:
    claims: list[dict[str, Any]] = []
    today = date.today()
    for side, team, opponent in (
        ("home", match.home_team, match.away_team),
        ("away", match.away_team, match.home_team),
    ):
        impact = f"context_{side}"
        player = f"{team} Sample Forward"
        defender = f"{team} Sample Defender"
        prefix = f"local://deep-scout/{_safe_slug(match.round_id)}/{_safe_slug(team)}"
        claims.extend(
            [
                _local_claim(
                    team=team,
                    claim_type="team_profile",
                    subject=team,
                    claim=f"Local deep-scout fixture identifies {team} as the {side} country team against {opponent}.",
                    impact=impact,
                    source_url=f"{prefix}/team-profile",
                    metrics={"side": side, "opponent": opponent},
                    today=today,
                ),
                _local_claim(
                    team=team,
                    claim_type="recent_form",
                    subject=f"{team} recent form",
                    claim=f"Local deep-scout fixture gives {team} a six-match form line of 4 wins, 1 draw and 1 loss.",
                    impact=impact,
                    source_url=f"{prefix}/recent-form",
                    metrics={
                        "recent_sample_matches": 6,
                        "recent_wins": 4,
                        "recent_draws": 1,
                        "recent_losses": 1,
                        "recent_goals_for": 11,
                        "recent_goals_against": 5,
                    },
                    today=today,
                ),
                _local_claim(
                    team=team,
                    player=player,
                    claim_type="player_form",
                    subject=player,
                    claim=f"Local deep-scout fixture gives {player} 18 goals and 9 assists in 42 appearances.",
                    impact=impact,
                    source_url=f"{prefix}/player-form",
                    metrics={
                        "goals": 18,
                        "assists": 9,
                        "goal_contributions": 27,
                        "appearances": 42,
                        "position": "Forward",
                        "club": f"{team} Test Club",
                    },
                    today=today,
                ),
                _local_claim(
                    team=team,
                    player=player,
                    claim_type="squad_roster",
                    subject=player,
                    claim=f"Local deep-scout fixture lists {player} as a forward for {team}.",
                    impact=impact,
                    source_url=f"{prefix}/squad-roster",
                    metrics={
                        "position": "Forward",
                        "club": f"{team} Test Club",
                        "caps": 24,
                        "goals": 10,
                    },
                    today=today,
                ),
                _local_claim(
                    team=team,
                    player=defender,
                    claim_type="injury_availability",
                    subject=defender,
                    claim=f"Local deep-scout fixture marks {defender} available for the match.",
                    impact=impact,
                    source_url=f"{prefix}/availability",
                    metrics={
                        "availability_status": "available",
                        "position": "Defender",
                        "club": f"{team} Test Club",
                    },
                    today=today,
                ),
                _local_claim(
                    team=team,
                    claim_type="lineup",
                    subject=f"{team} local lineup",
                    claim=f"Local deep-scout fixture projects {team} in a 4-3-3 with {player} starting.",
                    impact=impact,
                    source_url=f"{prefix}/lineup",
                    metrics={"formation": "4-3-3", "lineup_signal": "projected_xi", "player": player},
                    today=today,
                ),
                _local_claim(
                    team=team,
                    claim_type="match_history",
                    subject=f"{team} vs {opponent} history",
                    claim=f"Local deep-scout fixture records a prior test result: {team} 2-1 {opponent}.",
                    impact=impact,
                    source_url=f"{prefix}/match-history",
                    metrics={
                        "historical_team_a": team,
                        "historical_team_b": opponent,
                        "historical_team_a_score": 2,
                        "historical_team_b_score": 1,
                        "historical_result_label": f"{team} 2-1 {opponent}",
                        "historical_result_signal": "explicit_score",
                    },
                    today=today,
                ),
                _local_claim(
                    team=team,
                    claim_type="tactical",
                    subject=f"{team} tactical setup",
                    claim=f"Local deep-scout fixture tags {team} with a 4-3-3 high-press tactical setup.",
                    impact=impact,
                    source_url=f"{prefix}/tactical",
                    metrics={"formation": "4-3-3", "tactical_signal": "high_press", "lineup_signal": "shape"},
                    today=today,
                ),
            ]
        )

    market, stats, odds, news = synthetic_probabilities(match.home_team, match.away_team)
    return [
        Finding(
            finding_id=f"{match.round_id}:local_deep_fixture",
            scout_name="local_deep_fixture_scout",
            access_level="public",
            source_type="retrieval",
            finding_name="local_deep_fixture_claims",
            home_probability=stats,
            home_delta=round(stats - market, 4),
            confidence=0.72,
            cost=0.0,
            citations=sorted({claim["source_url"] for claim in claims}),
            summary=(
                "Local deterministic deep-scout source covering team, player, roster, lineup, "
                "availability, history, tactical, and context topics."
            ),
            evidence_claims=claims,
        )
    ]


def _local_claim(
    *,
    team: str,
    claim_type: str,
    subject: str,
    claim: str,
    impact: str,
    source_url: str,
    metrics: dict[str, Any],
    today: date,
    player: str = "",
) -> dict[str, Any]:
    return {
        "claim_type": claim_type,
        "subject": subject,
        "team": team,
        "player": player,
        "claim": claim,
        "impact": impact,
        "confidence": 0.72,
        "source_title": "Local deterministic deep-scout fixture",
        "source_url": source_url,
        "source_domain": _domain(source_url),
        "source_published_date": today.isoformat(),
        "source_recency_days": 0,
        "source_recency_bucket": "last_7_days",
        "source_kind": "reference",
        "source_quality": "strong",
        "extraction_method": "local_deep_fixture",
        "metrics": metrics,
    }


def _findings_from_existing_kg(
    match: MatchContext,
    existing_graph: dict[str, Any],
    *,
    source_label: str,
) -> list[Finding]:
    evidence_claims = _existing_evidence_claims(match, existing_graph, source_label=source_label)
    if not evidence_claims:
        evidence_claims = _existing_context_claims(match, existing_graph, source_label=source_label)
    if not evidence_claims:
        return []
    return [
        Finding(
            finding_id=f"{match.round_id}:existing_kg:{_safe_slug(source_label)}",
            scout_name="existing_kg_scout",
            access_level="public",
            source_type="retrieval",
            finding_name="existing_kg_enrichment",
            home_probability=None,
            home_delta=None,
            confidence=0.7,
            cost=0.0,
            citations=sorted({claim["source_url"] for claim in evidence_claims if claim.get("source_url")}),
            summary=f"Reused {len(evidence_claims)} claims from an existing KG.",
            evidence_claims=evidence_claims,
        )
    ]


def _existing_evidence_claims(
    match: MatchContext,
    existing_graph: dict[str, Any],
    *,
    source_label: str,
) -> list[dict[str, Any]]:
    claims = []
    teams = {match.home_team.casefold(), match.away_team.casefold()}
    match_ids = {f"match:{match.round_id}", match.round_id}
    for entity in existing_graph.get("entities", []):
        if entity.get("entity_type") != "evidence_claim":
            continue
        attrs = dict(entity.get("attributes") or {})
        team = str(attrs.get("team") or "")
        match_id = str(attrs.get("match_id") or "")
        if team.casefold() not in teams and match_id not in match_ids:
            continue
        attrs["source_title"] = str(attrs.get("source_title") or f"Existing KG {source_label}")
        attrs["source_url"] = str(attrs.get("source_url") or f"kg://{_safe_slug(source_label)}#{entity.get('entity_id')}")
        attrs["source_kind"] = str(attrs.get("source_kind") or "existing_kg")
        attrs["source_quality"] = str(attrs.get("source_quality") or "strong")
        attrs["extraction_method"] = "existing_kg_reuse"
        claims.append(attrs)
    return claims[:80]


def _existing_context_claims(
    match: MatchContext,
    existing_graph: dict[str, Any],
    *,
    source_label: str,
) -> list[dict[str, Any]]:
    match_entity = _match_entity_from_existing_graph(match, existing_graph)
    claims = []
    source_url = f"kg://{_safe_slug(source_label)}"
    for side, team, opponent in (
        ("home", match.home_team, match.away_team),
        ("away", match.away_team, match.home_team),
    ):
        impact = f"context_{side}"
        claims.append(
            {
                "claim_type": "team_profile",
                "subject": team,
                "team": team,
                "player": "",
                "claim": f"Existing KG contains {team} as the {side} team for {match.home_team} vs {match.away_team}.",
                "impact": impact,
                "confidence": 0.7,
                "source_title": f"Existing KG {source_label}",
                "source_url": source_url,
                "source_domain": _domain(source_url),
                "source_kind": "existing_kg",
                "source_quality": "strong",
                "extraction_method": "existing_kg_context",
                "metrics": {"side": side, "opponent": opponent},
            }
        )
    if match_entity:
        attrs = dict(match_entity.get("attributes") or {})
        claims.append(
            {
                "claim_type": "match_schedule",
                "subject": match_entity.get("name") or f"{match.home_team} vs {match.away_team}",
                "team": match.home_team,
                "player": "",
                "claim": (
                    f"Existing KG schedules {match.home_team} vs {match.away_team}"
                    + (f" on {attrs.get('date')}" if attrs.get("date") else "")
                    + (f" at {attrs.get('ground')}" if attrs.get("ground") else "")
                    + "."
                ),
                "impact": "context_home",
                "confidence": 0.72,
                "source_title": f"Existing KG {source_label}",
                "source_url": source_url,
                "source_domain": _domain(source_url),
                "source_kind": "existing_kg",
                "source_quality": "strong",
                "extraction_method": "existing_kg_context",
                "metrics": {
                    "match_date": attrs.get("date"),
                    "kickoff_time": attrs.get("time"),
                    "group": attrs.get("group"),
                    "venue": attrs.get("ground") or attrs.get("venue"),
                    "stage": attrs.get("round") or attrs.get("stage"),
                },
            }
        )
    return claims


def _match_entity_from_existing_graph(match: MatchContext, graph: dict[str, Any]) -> dict[str, Any] | None:
    wanted = _normalize_match_name(f"{match.home_team} vs {match.away_team}")
    for entity in graph.get("entities", []):
        if entity.get("entity_type") != "match":
            continue
        if str(entity.get("entity_id") or "") in {f"match:{match.round_id}", match.round_id}:
            return entity
        if _normalize_match_name(str(entity.get("name") or "")) == wanted:
            return entity
    return None


def _empty_match_context(match_entity: dict[str, Any]) -> MatchContext:
    attrs = dict(match_entity.get("attributes") or {})
    home_team = str(attrs.get("team1") or attrs.get("home_team") or "Home")
    away_team = str(attrs.get("team2") or attrs.get("away_team") or "Away")
    round_id = str(match_entity.get("entity_id") or f"round:{_safe_slug(home_team)}_{_safe_slug(away_team)}")
    round_id = round_id.replace("match:", "round:")
    market, stats, odds, news = synthetic_probabilities(home_team, away_team)
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
        findings=[],
    )


def _summary_markdown(
    result: LocalScoutingResult,
    manifest: dict[str, Any],
    validation: dict[str, Any],
    categories: dict[str, Any],
) -> str:
    lines = [
        f"# Local Scouting KG: {result.match.round_id}",
        "",
        "## Match",
        "",
        f"- Match: {result.match.home_team} vs {result.match.away_team}",
        f"- Graph id: {result.graph.graph_id}",
        f"- Validation: {'passes' if validation['passes'] else 'fails'} ({validation['status']})",
        f"- KG load ready: {validation['kg_load_ready']}",
        f"- Scouting complete: {validation['scouting_complete']}",
        "",
        "## Counts",
        "",
        f"- Findings: {len(result.findings)}",
        f"- Evidence claims: {sum(len(finding.evidence_claims) for finding in result.findings)}",
        f"- Entities: {len(result.graph.entities)}",
        f"- Relationships: {len(result.graph.relationships)}",
        "",
        "## Categories",
        "",
    ]
    for category, row in categories["categories"].items():
        lines.append(f"- {category}: {row['entity_count']} entities")
    readiness = manifest.get("readiness") or {}
    if readiness.get("scouting_backlog_count"):
        lines.extend(
            [
                "",
                "## Scouting Backlog",
                "",
                f"- Items: {readiness['scouting_backlog_count']}",
                f"- Missing required claim types: {', '.join(readiness.get('missing_required_claim_types') or []) or 'none'}",
                f"- Teams with missing claims: {', '.join(readiness.get('teams_with_missing_required_claims') or []) or 'none'}",
            ]
        )
    if result.scout_targets:
        lines.extend(["", "## Focused Scout Targets", ""])
        for target in result.scout_targets:
            suffix = ""
            if target.get("quality_reasons"):
                suffix = f" ({', '.join(str(reason) for reason in target.get('quality_reasons') or [])})"
            lines.append(f"- {target.get('team')}:{target.get('claim_type')}{suffix}")
    lines.extend(
        [
            "",
            "## Source Summaries",
            "",
        ]
    )
    for source in result.source_summaries:
        lines.append(
            f"- {source['source']}: {source['finding_count']} findings, {source['evidence_claim_count']} claims"
        )
    return "\n".join(lines) + "\n"


def _source_title(source: SourceSpec) -> str:
    configured_title = source.config.get("title") or source.config.get("name")
    if configured_title:
        return str(configured_title)
    if source.kind == "mcp-stdio":
        tool = source.config.get("tool") or source.config.get("tool_name")
        return f"MCP stdio tool {tool or source.locator or 'source'}"
    if source.kind == "mcp":
        return f"MCP dataset export {Path(source.locator).name}"
    if source.kind == "json":
        return f"JSON dataset {Path(source.locator).name}"
    if source.kind == "api":
        return f"API dataset {source.locator}"
    if source.kind == "url":
        return f"URL source {_title_from_url(source.locator)}"
    if source.kind == "cli":
        return f"CLI dataset {source.locator}"
    return source.label


def _source_kind(source: SourceSpec) -> str:
    return {
        "json": "reference",
        "mcp": "mcp",
        "mcp-stdio": "mcp",
        "api": "api",
        "cli": "cli",
        "public": "web",
        "url": "web",
    }.get(source.kind, "reference")


def _source_quality(source: SourceSpec) -> str:
    return "strong" if source.kind in {"json", "mcp", "mcp-stdio", "public"} else "medium"


def _source_type_for_source(source: SourceSpec) -> SourceType:
    if source.kind in {"json", "mcp", "mcp-stdio", "api", "cli", "public", "url"}:
        return "retrieval"
    return "other"


def _default_public_cache_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "live_scouts"


def _fallback_source_url(source: SourceSpec) -> str:
    if source.kind in {"api", "url"} and (source.locator or source.config.get("url")):
        return str(source.locator or source.config.get("url"))
    if source.kind == "mcp-stdio":
        tool = source.config.get("tool") or source.config.get("tool_name") or source.locator or source.raw
        return f"mcp-stdio://{_safe_slug(str(tool))}"
    if source.kind in {"json", "mcp"}:
        return f"{source.kind}://{_safe_slug(source.locator or source.raw)}"
    if source.kind == "cli":
        return f"cli://{_safe_slug(source.locator or source.raw)}"
    return source.raw or source.label


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc:
        tail = Path(parsed.path).name or parsed.netloc
        return f"{parsed.netloc} {tail}".strip()
    return Path(url).name or url or "source"


def _clean_document_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _safe_source_type(value: Any) -> SourceType:
    allowed = {"market", "stats", "odds", "news", "lineup", "social", "weather", "retrieval", "other"}
    text = str(value or "retrieval")
    return text if text in allowed else "other"  # type: ignore[return-value]


def _infer_team(claim: dict[str, Any], match: MatchContext) -> str:
    text = " ".join(str(claim.get(key) or "") for key in ("subject", "claim", "player"))
    if match.home_team.casefold() in text.casefold():
        return match.home_team
    if match.away_team.casefold() in text.casefold():
        return match.away_team
    return ""


def _default_impact(team: str, match: MatchContext) -> str:
    if team == match.away_team:
        return "context_away"
    return "context_home"


def _dedupe_finding_ids(findings: list[Finding]) -> list[Finding]:
    seen: Counter[str] = Counter()
    deduped: list[Finding] = []
    for finding in findings:
        seen[finding.finding_id] += 1
        if seen[finding.finding_id] == 1:
            deduped.append(finding)
            continue
        suffix = seen[finding.finding_id]
        deduped.append(
            Finding(
                finding_id=f"{finding.finding_id}:{suffix}",
                scout_name=finding.scout_name,
                access_level=finding.access_level,
                source_type=finding.source_type,
                finding_name=finding.finding_name,
                home_probability=finding.home_probability,
                home_delta=finding.home_delta,
                confidence=finding.confidence,
                cost=finding.cost,
                citations=finding.citations,
                summary=finding.summary,
                evidence_claims=finding.evidence_claims,
            )
        )
    return deduped


def _dedupe_entities(entities: list[WorldEntity]) -> list[WorldEntity]:
    seen = set()
    output = []
    for entity in entities:
        if entity.entity_id in seen:
            continue
        seen.add(entity.entity_id)
        output.append(entity)
    return output


def _dedupe_relationships(relationships: list[WorldRelationship]) -> list[WorldRelationship]:
    seen = set()
    output = []
    for relationship in relationships:
        key = (relationship.source_id, relationship.relation_type, relationship.target_id)
        if key in seen:
            continue
        seen.add(key)
        output.append(relationship)
    return output


def _normalize_match_name(value: str) -> str:
    return " ".join(value.lower().replace("-", " ").split())


def _safe_slug(value: str) -> str:
    chars = []
    for char in str(value).lower():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_", " ", ":", "/", "."}:
            chars.append("_")
    return "_".join(part for part in "".join(chars).split("_") if part) or "value"


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _domain(url: str) -> str:
    if not url:
        return ""
    parsed = urllib.parse.urlparse(url)
    return parsed.netloc.lower()
