#!/usr/bin/env python3
"""Run local scouting KG tests across several matches and source modules."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:  # Script mode: PYTHONPATH=colony python3 scouting_matrix.py
    from colony_harness.env import load_env_file
    from colony_harness.scouting_pipeline import (
        DEFAULT_LOCAL_RUNS_DIR,
        ScoutingRunLogger,
        SourceSpec,
        build_local_scouting_result,
        load_graph_for_local_scouting,
        parse_source_spec,
        write_local_scouting_artifacts,
    )
except ImportError:  # Package mode: import colony.scouting_matrix
    from colony.colony_harness.env import load_env_file
    from colony.colony_harness.scouting_pipeline import (
        DEFAULT_LOCAL_RUNS_DIR,
        ScoutingRunLogger,
        SourceSpec,
        build_local_scouting_result,
        load_graph_for_local_scouting,
        parse_source_spec,
        write_local_scouting_artifacts,
    )


DEFAULT_KG = Path(__file__).parent / "data" / "world_cup_kg.json"
DEFAULT_ENV = Path(__file__).parent / ".env"
DEFAULT_SOURCE_CATALOG = Path(__file__).parent / "config" / "scouting_source_catalog.json"
DEFAULT_MODULES = ["fixture", "polymarket_market_context"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a matrix of local scouting KG tests.")
    parser.add_argument("--kg", default=str(DEFAULT_KG), help="Tournament KG to select matches from.")
    parser.add_argument("--env", default=str(DEFAULT_ENV), help="Optional .env path for scouting provider settings.")
    parser.add_argument("--from-date", default=date.today().isoformat(), help="First match date, YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=3, help="Number of matches to test.")
    parser.add_argument("--match", action="append", default=[], help="Exact match name to include. Repeatable.")
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        help="Source module to include. Repeatable. Defaults to fixture + polymarket_market_context.",
    )
    parser.add_argument(
        "--source-catalog",
        default=str(DEFAULT_SOURCE_CATALOG),
        help="JSON catalog of reusable source modules and datasource candidates.",
    )
    parser.add_argument("--list-modules", action="store_true", help="Print source modules from the catalog and exit.")
    parser.add_argument("--list-datasources", action="store_true", help="Print datasource candidates from the catalog and exit.")
    parser.add_argument("--mode", choices=["fast", "deep"], default="fast")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--cutoff-hours", type=float, default=6.0, help="Prediction cutoff before kickoff for as-of source templates.")
    parser.add_argument(
        "--camel-agents",
        type=int,
        default=0,
        help="Override number of focused CAMEL/DDGS research agents for modules that enable CAMEL.",
    )
    parser.add_argument("--out-dir", default="", help="Matrix output directory.")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)
    catalog = _load_source_catalog(args.source_catalog)
    if args.list_modules:
        print(_module_catalog_report(catalog))
        return
    if args.list_datasources:
        print(_datasource_catalog_report(catalog))
        return
    modules = _expanded_modules(args.module or DEFAULT_MODULES, catalog)
    graph = load_graph_for_local_scouting(kg_path=args.kg, offline_sample=False)
    matches = _select_matches(graph, wanted=args.match, from_date=args.from_date, limit=args.limit)
    run_root = Path(args.out_dir) if args.out_dir else Path(DEFAULT_LOCAL_RUNS_DIR) / "matrix" / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for match_entity in matches:
        match_name = str(match_entity.get("name") or "")
        match_slug = _safe_slug(match_name)
        out_dir = run_root / match_slug
        logger = ScoutingRunLogger(verbose=not args.quiet)
        existing_kg_paths = [args.kg] if _uses_existing_kg(modules, catalog) else []
        pipeline_flags = _pipeline_flags_for_modules(modules, catalog, camel_agent_count_override=args.camel_agents)
        sources = _sources_for_match(match_entity, modules, catalog=catalog, cutoff_hours=args.cutoff_hours, logger=logger)
        result = build_local_scouting_result(
            match_entity=match_entity,
            mode=args.mode,
            sources=sources,
            existing_kg_paths=existing_kg_paths,
            merge_existing_kg=False,
            timeout_seconds=args.timeout,
            include_x=pipeline_flags["include_x"],
            include_camel=pipeline_flags["include_camel"],
            include_camel_deep=pipeline_flags["include_camel_deep"],
            camel_agent_count=pipeline_flags["camel_agent_count"],
            include_telegram=pipeline_flags["include_telegram"],
            include_polygun=pipeline_flags["include_polygun"],
            include_deepseek_scout=pipeline_flags["include_deepseek_scout"],
            logger=logger,
        )

        if _needs_txline_second_pass(modules, catalog):
            fixture = _txline_fixture_from_findings(result.findings)
            if fixture:
                logger.event(
                    "matrix_txline_fixture_resolved",
                    match=match_name,
                    fixture_id=fixture.get("fixture_id"),
                    as_of=fixture.get("start_time"),
                )
                sources = _sources_for_match(
                    match_entity,
                    modules,
                    catalog=catalog,
                    txline_fixture=fixture,
                    cutoff_hours=args.cutoff_hours,
                    logger=logger,
                )
                result = build_local_scouting_result(
                    match_entity=match_entity,
                    mode=args.mode,
                    sources=sources,
                    existing_kg_paths=existing_kg_paths,
                    merge_existing_kg=False,
                    timeout_seconds=args.timeout,
                    include_x=pipeline_flags["include_x"],
                    include_camel=pipeline_flags["include_camel"],
                    include_camel_deep=pipeline_flags["include_camel_deep"],
                    camel_agent_count=pipeline_flags["camel_agent_count"],
                    include_telegram=pipeline_flags["include_telegram"],
                    include_polygun=pipeline_flags["include_polygun"],
                    include_deepseek_scout=pipeline_flags["include_deepseek_scout"],
                    logger=logger,
                )
            else:
                logger.event("matrix_txline_fixture_missing", match=match_name)

        artifacts = write_local_scouting_artifacts(out_dir=out_dir, result=result, logger=logger, mode=args.mode)
        validation = artifacts["validation"]
        rows.append(
            {
                "match": match_name,
                "date": match_entity.get("attributes", {}).get("date"),
                "modules": modules,
                "out_dir": artifacts["out_dir"],
                "status": validation["status"],
                "kg_load_ready": validation["kg_load_ready"],
                "scouting_complete": validation["scouting_complete"],
                "entities": validation["entity_count"],
                "relationships": validation["relationship_count"],
                "findings": len(result.findings),
                "claims": sum(len(f.evidence_claims) for f in result.findings),
                "source_summaries": result.source_summaries,
            }
        )

    (run_root / "matrix_results.json").write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (run_root / "matrix_report.md").write_text(_matrix_report(rows), encoding="utf-8")
    print(f"Scouting matrix: {run_root}")
    for row in rows:
        print(
            f"{row['match']}: {row['status']} "
            f"entities={row['entities']} relationships={row['relationships']} claims={row['claims']}"
        )


def _expanded_modules(modules: list[str], catalog: dict[str, Any]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()

    def add_module(module_name: str) -> None:
        if module_name in seen:
            return
        module = _catalog_module(catalog, module_name)
        seen.add(module_name)
        for included in module.get("includes", []):
            add_module(str(included))
        if not module.get("includes"):
            expanded.append(module_name)

    for module in modules:
        add_module(module)
    if "fixture" not in expanded:
        expanded.insert(0, "fixture")
    return list(dict.fromkeys(expanded))


def _select_matches(graph: dict[str, Any], *, wanted: list[str], from_date: str, limit: int) -> list[dict[str, Any]]:
    matches = [entity for entity in graph.get("entities", []) if entity.get("entity_type") == "match"]
    if wanted:
        wanted_keys = {_team_key(name) for name in wanted}
        selected = [match for match in matches if _team_key(str(match.get("name") or "")) in wanted_keys]
    else:
        selected = [
            match
            for match in matches
            if str(match.get("attributes", {}).get("date") or "") >= from_date
        ]
    return sorted(selected, key=lambda match: (match.get("attributes", {}).get("date") or "", match.get("name") or ""))[:limit]


def _sources_for_match(
    match_entity: dict[str, Any],
    modules: list[str],
    *,
    catalog: dict[str, Any],
    txline_fixture: dict[str, Any] | None = None,
    cutoff_hours: float = 6.0,
    logger: ScoutingRunLogger | None = None,
) -> list[SourceSpec]:
    sources: list[SourceSpec] = []
    seen_sources: set[tuple[str, str, str]] = set()
    context = _match_template_context(match_entity, txline_fixture=txline_fixture, cutoff_hours=cutoff_hours)
    for module_name in modules:
        module = _catalog_module(catalog, module_name)
        missing_env = _missing_module_env(module)
        if missing_env:
            if logger:
                logger.event("matrix_module_skipped", module=module_name, reason="missing_env", missing=",".join(missing_env))
            continue
        if not _module_context_ready(module, context):
            if logger:
                logger.event(
                    "matrix_module_skipped",
                    module=module_name,
                    reason="missing_context",
                    missing=",".join(str(item) for item in module.get("requires_context", [])),
                )
            continue
        for raw_source in module.get("sources", []):
            source = parse_source_spec(_render_catalog_value(raw_source, context))
            source_key = (source.kind, source.locator, json.dumps(source.config, sort_keys=True, default=str))
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            sources.append(source)
    return sources


def _load_source_catalog(path: str) -> dict[str, Any]:
    catalog_path = Path(path)
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Source catalog not found: {catalog_path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid source catalog JSON: {catalog_path}") from exc
    if not isinstance(catalog, dict) or not isinstance(catalog.get("modules"), dict):
        raise SystemExit(f"Source catalog must contain a modules object: {catalog_path}")
    return catalog


def _catalog_module(catalog: dict[str, Any], module_name: str) -> dict[str, Any]:
    modules = catalog.get("modules") or {}
    module = modules.get(module_name)
    if not isinstance(module, dict):
        known = ", ".join(sorted(str(name) for name in modules))
        raise SystemExit(f"Unknown source module '{module_name}'. Known modules: {known}")
    return module


def _uses_existing_kg(modules: list[str], catalog: dict[str, Any]) -> bool:
    return any(bool(_catalog_module(catalog, module_name).get("existing_kg")) for module_name in modules)


def _pipeline_flags_for_modules(
    modules: list[str],
    catalog: dict[str, Any],
    *,
    camel_agent_count_override: int = 0,
) -> dict[str, Any]:
    flags = {
        "include_x": False,
        "include_camel": False,
        "include_camel_deep": False,
        "camel_agent_count": 4,
        "include_telegram": False,
        "include_polygun": False,
        "include_deepseek_scout": False,
    }
    for module_name in modules:
        raw_flags = _catalog_module(catalog, module_name).get("pipeline_flags") or {}
        if not isinstance(raw_flags, dict):
            continue
        for key in flags:
            if key == "camel_agent_count":
                raw_count = raw_flags.get(key)
                if raw_count:
                    flags[key] = int(raw_count)
                continue
            flags[key] = flags[key] or bool(raw_flags.get(key))
    if camel_agent_count_override:
        flags["camel_agent_count"] = camel_agent_count_override
    return flags


def _needs_txline_second_pass(modules: list[str], catalog: dict[str, Any]) -> bool:
    return any("txline_fixture" in _context_requirements(_catalog_module(catalog, module_name)) for module_name in modules)


def _context_requirements(module: dict[str, Any]) -> list[str]:
    raw = module.get("requires_context") or []
    if isinstance(raw, str):
        return [raw]
    return [str(item) for item in raw if str(item)]


def _missing_module_env(module: dict[str, Any]) -> list[str]:
    required = module.get("requires_env") or []
    if isinstance(required, str):
        required = [required]
    missing = [str(name) for name in required if str(name) and not os.getenv(str(name))]
    for group in module.get("requires_any_env") or []:
        group_names = [str(name) for name in (group if isinstance(group, list) else [group]) if str(name)]
        if group_names and not any(os.getenv(name) for name in group_names):
            missing.append("one_of(" + "|".join(group_names) + ")")
    return missing



def _module_context_ready(module: dict[str, Any], context: dict[str, Any]) -> bool:
    for requirement in _context_requirements(module):
        if requirement == "txline_fixture":
            if not context.get("txline_fixture_id"):
                return False
            continue
        if context.get(requirement) in {None, ""}:
            return False
    return True


def _match_template_context(
    match_entity: dict[str, Any],
    *,
    txline_fixture: dict[str, Any] | None,
    cutoff_hours: float = 6.0,
) -> dict[str, Any]:
    attrs = match_entity.get("attributes", {})
    team1 = str(attrs.get("team1") or "").strip()
    team2 = str(attrs.get("team2") or "").strip()
    match_name = str(match_entity.get("name") or f"{team1} vs {team2}")
    match_date = str(attrs.get("date") or "")
    kickoff_utc = _match_kickoff_utc(match_date=match_date, match_time=str(attrs.get("time") or ""))
    prediction_cutoff_utc = kickoff_utc - timedelta(hours=cutoff_hours) if kickoff_utc else None
    context: dict[str, Any] = {
        "match_id": str(match_entity.get("entity_id") or ""),
        "match_name": match_name,
        "match_slug": _safe_slug(match_name),
        "team1": team1,
        "team2": team2,
        "home_team": team1,
        "away_team": team2,
        "match_date": match_date,
        "epoch_day": _epoch_day(match_date) if match_date else "",
        "kickoff_utc": _iso_utc(kickoff_utc) if kickoff_utc else "",
        "prediction_cutoff_utc": _iso_utc(prediction_cutoff_utc) if prediction_cutoff_utc else "",
        "prediction_cutoff_ms": _epoch_ms(prediction_cutoff_utc) if prediction_cutoff_utc else "",
    }
    if txline_fixture:
        txline_start_utc = _timestamp_to_utc(txline_fixture.get("start_time"))
        txline_cutoff_utc = txline_start_utc - timedelta(hours=cutoff_hours) if txline_start_utc else prediction_cutoff_utc
        context.update(
            {
                "txline_fixture_id": txline_fixture.get("fixture_id") or "",
                "txline_start_time": txline_fixture.get("start_time") or "",
                "txline_start_time_utc": _iso_utc(txline_start_utc) if txline_start_utc else "",
                "txline_prediction_cutoff_utc": _iso_utc(txline_cutoff_utc) if txline_cutoff_utc else "",
                "txline_prediction_cutoff_ms": _epoch_ms(txline_cutoff_utc) if txline_cutoff_utc else "",
            }
        )
    return context


_TEMPLATE_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _render_catalog_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _TEMPLATE_TOKEN_RE.sub(lambda match: str(context.get(match.group(1), match.group(0))), value)
    if isinstance(value, list):
        return [_render_catalog_value(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_catalog_value(item, context) for key, item in value.items()}
    return value


def _txline_fixture_from_findings(findings: list[Any]) -> dict[str, Any] | None:
    for finding in findings:
        for claim in finding.evidence_claims:
            if isinstance(claim, dict):
                metrics = claim.get("metrics") or {}
                claim_type = str(claim.get("claim_type") or "")
                claim_text = str(claim.get("claim") or "")
            else:
                metrics = getattr(claim, "metrics", None) or {}
                claim_type = str(getattr(claim, "claim_type", "") or "")
                claim_text = str(getattr(claim, "claim", "") or "")
            fixture_id = metrics.get("fixture_id")
            if fixture_id and claim_type == "match_schedule" and "TXLINE" in claim_text:
                return {"fixture_id": fixture_id, "start_time": metrics.get("start_time")}
    return None


def _epoch_day(match_date: str) -> int:
    parsed = datetime.strptime(match_date, "%Y-%m-%d").date()
    return (parsed - date(1970, 1, 1)).days


def _match_kickoff_utc(*, match_date: str, match_time: str) -> datetime | None:
    if not match_date or not match_time:
        return None
    match = re.match(r"^(\d{1,2}):(\d{2})\s+UTC([+-]\d{1,2})$", match_time.strip())
    if not match:
        return None
    hour, minute, offset = match.groups()
    tz = timezone(timedelta(hours=int(offset)))
    local = datetime.fromisoformat(f"{match_date}T{int(hour):02d}:{minute}:00").replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def _timestamp_to_utc(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    if timestamp > 10_000_000_000:
        timestamp /= 1000.0
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _iso_utc(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _epoch_ms(value: datetime | None) -> str:
    if value is None:
        return ""
    return str(int(value.astimezone(timezone.utc).timestamp() * 1000))


def _safe_slug(value: str) -> str:
    return "_".join(_team_key(value).split())[:80] or "match"


def _team_key(value: str) -> str:
    import re

    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def _matrix_report(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Scouting Matrix",
        "",
        "| Match | Status | Entities | Relationships | Claims | KG |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        summary = Path(row["out_dir"]) / "summary.md"
        lines.append(
            f"| {row['match']} | {row['status']} | {row['entities']} | "
            f"{row['relationships']} | {row['claims']} | {summary} |"
        )
    lines.extend(["", "## Sources", ""])
    for row in rows:
        lines.append(f"### {row['match']}")
        for source in row["source_summaries"]:
            duration = source.get("duration_seconds")
            duration_text = f", {duration}s" if duration is not None else ""
            lines.append(
                f"- {source['source']}: {source['finding_count']} findings, "
                f"{source['evidence_claim_count']} claims{duration_text}"
            )
            for stage in (source.get("stage_metrics") or [])[:8]:
                lines.append(
                    f"  - {stage.get('stage')}: {stage.get('duration_seconds')}s, "
                    f"{stage.get('item_count', 0)} items"
                )
        lines.append("")
    return "\n".join(lines)


def _module_catalog_report(catalog: dict[str, Any]) -> str:
    lines = [
        "# Scouting Source Modules",
        "",
        "| Module | Surface | Status | Family | Claims | Description |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, module in sorted((catalog.get("modules") or {}).items()):
        if not isinstance(module, dict):
            continue
        surface = "cli-only" if module.get("ui_hidden") else "dashboard"
        if module.get("alias_for"):
            surface = f"cli-only alias for {module['alias_for']}"
        if module.get("superseded_by"):
            surface = f"cli-only superseded by {module['superseded_by']}"
        claims = ", ".join(str(item) for item in module.get("claim_types", [])) or "-"
        status = str(module.get("status") or "-")
        family = str(module.get("source_family") or "-")
        description = str(module.get("description") or "").replace("|", "\\|")
        if module.get("includes"):
            description = f"includes: {', '.join(str(item) for item in module['includes'])}"
        lines.append(f"| {name} | {surface} | {status} | {family} | {claims} | {description} |")
    return "\n".join(lines)


def _datasource_catalog_report(catalog: dict[str, Any]) -> str:
    lines = [
        "# Scouting Datasource Candidates",
        "",
        "| Datasource | Priority | Status | Integration | Claims | Module | Docs |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for source in catalog.get("datasources", []):
        if not isinstance(source, dict):
            continue
        name = str(source.get("name") or source.get("id") or "-").replace("|", "\\|")
        priority = str(source.get("priority") or "-")
        status = str(source.get("status") or "-")
        integration = ", ".join(str(item) for item in source.get("integration_kind", [])) or "-"
        claims = ", ".join(str(item) for item in source.get("claim_types", [])) or "-"
        module = str(source.get("module") or "-")
        docs = str(source.get("docs_url") or "-")
        lines.append(f"| {name} | {priority} | {status} | {integration} | {claims} | {module} | {docs} |")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
