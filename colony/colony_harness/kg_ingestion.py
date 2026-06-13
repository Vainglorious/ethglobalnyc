"""Strict ingestion contract for scouting KG run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .world_graph import KG_SCHEMA_VERSION


class KGIngestionError(ValueError):
    """Raised when a run directory is not safe to ingest into the KG."""


def load_scouting_kg_bundle(
    run_dir: str | Path,
    *,
    require_complete: bool = False,
) -> dict[str, Any]:
    """Validate a scouting run and return a loader-friendly ingestion bundle.

    The bundle does not invent missing facts. It only materializes entrypoints
    and lineage already present in the run's manifest and world graph.
    """

    run_path = Path(run_dir)
    manifest = _read_json_object(run_path / "kg_manifest.json")
    graph = _read_json_object(run_path / str((manifest.get("files") or {}).get("world_graph") or "world_graph.json"))
    audit_path = run_path / str((manifest.get("files") or {}).get("scouting_audit") or "scouting_audit.json")
    audit = _read_json_object(audit_path) if audit_path.exists() else {}
    validation = validate_scouting_kg_run(
        run_path,
        manifest=manifest,
        graph=graph,
        audit=audit,
        require_complete=require_complete,
    )
    if not validation["passes"]:
        raise KGIngestionError("; ".join(validation["errors"]))

    entities = list(graph.get("entities") or [])
    relationships = list(graph.get("relationships") or [])
    entrypoint_types = list(manifest.get("entrypoint_entity_types") or [])
    entrypoints = {
        entity_type: [
            _compact_entity(entity)
            for entity in entities
            if entity.get("entity_type") == entity_type
        ]
        for entity_type in entrypoint_types
    }
    profile_entity_types = set(manifest.get("profile_entity_types") or [])
    profile_lineage = {
        str(entity.get("entity_id")): list((entity.get("attributes") or {}).get("evidence_claim_ids") or [])
        for entity in entities
        if entity.get("entity_type") in profile_entity_types
    }
    lineage_relation = str(manifest.get("lineage_relation") or "summarizes_evidence_claim")
    lineage_edges = [
        relationship
        for relationship in relationships
        if relationship.get("relation_type") == lineage_relation
    ]
    return {
        "schema_version": manifest.get("schema_version"),
        "graph_id": manifest.get("graph_id"),
        "round_id": manifest.get("round_id"),
        "run_dir": str(run_path),
        "source_files": {
            key: str(run_path / str(value))
            for key, value in (manifest.get("files") or {}).items()
        },
        "readiness": dict(manifest.get("readiness") or {}),
        "ingestion_policy": dict(manifest.get("ingestion_policy") or {}),
        "entity_count": manifest.get("entity_count"),
        "relationship_count": manifest.get("relationship_count"),
        "entity_counts": dict(manifest.get("entity_counts") or {}),
        "relationship_counts": dict(manifest.get("relationship_counts") or {}),
        "entrypoints": entrypoints,
        "profile_lineage": profile_lineage,
        "lineage_edges": lineage_edges,
        "scouting_backlog": dict(audit.get("scouting_backlog") or {}),
        "admission": dict(manifest.get("admission") or audit.get("kg_admission") or {}),
        "validation": validation,
    }


def validate_scouting_kg_run(
    run_dir: str | Path,
    *,
    manifest: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
    audit: dict[str, Any] | None = None,
    require_complete: bool = False,
) -> dict[str, Any]:
    """Return a strict validation report for a scouting KG run directory."""

    run_path = Path(run_dir)
    errors: list[str] = []
    warnings: list[str] = []
    manifest = manifest if manifest is not None else _read_json_object(run_path / "kg_manifest.json")
    files = manifest.get("files") or {}
    graph_path = run_path / str(files.get("world_graph") or "world_graph.json")
    graph = graph if graph is not None else _read_json_object(graph_path)
    audit_path = run_path / str(files.get("scouting_audit") or "scouting_audit.json")
    audit = audit if audit is not None else (_read_json_object(audit_path) if audit_path.exists() else {})

    _expect(manifest.get("schema_version") == KG_SCHEMA_VERSION, errors, "manifest_schema_version_mismatch")
    _expect(graph.get("schema_version") == KG_SCHEMA_VERSION, errors, "world_graph_schema_version_mismatch")
    _expect(manifest.get("graph_id") == graph.get("graph_id"), errors, "graph_id_mismatch")
    _expect(manifest.get("round_id") == graph.get("round_id"), errors, "round_id_mismatch")

    for key, relative_path in files.items():
        if not (run_path / str(relative_path)).exists():
            errors.append(f"missing_manifest_file:{key}:{relative_path}")

    entities = list(graph.get("entities") or [])
    relationships = list(graph.get("relationships") or [])
    entity_ids = [str(entity.get("entity_id") or "") for entity in entities]
    entity_id_set = {entity_id for entity_id in entity_ids if entity_id}
    duplicate_entity_ids = sorted(
        entity_id for entity_id in entity_id_set if entity_ids.count(entity_id) > 1
    )
    if duplicate_entity_ids:
        errors.append(f"duplicate_entity_ids:{','.join(duplicate_entity_ids[:20])}")
    if len(entity_id_set) != len(entities):
        errors.append("empty_entity_id_present")

    orphan_edges = [
        relationship
        for relationship in relationships
        if relationship.get("source_id") not in entity_id_set or relationship.get("target_id") not in entity_id_set
    ]
    if orphan_edges:
        errors.append(f"orphan_relationships:{len(orphan_edges)}")

    if int(manifest.get("entity_count") or -1) != len(entities):
        errors.append("entity_count_mismatch")
    if int(manifest.get("relationship_count") or -1) != len(relationships):
        errors.append("relationship_count_mismatch")

    readiness = manifest.get("readiness") or {}
    if not readiness.get("kg_load_ready"):
        errors.append("kg_not_load_ready")
    if require_complete and not readiness.get("scouting_complete"):
        errors.append("scouting_not_complete")
    integrity = manifest.get("integrity") or {}
    if not integrity.get("passes"):
        errors.append("manifest_integrity_failed")
    duplicate_claim_group_count = int(integrity.get("duplicate_evidence_claim_group_count") or 0)
    if duplicate_claim_group_count > 0:
        warnings.append(f"duplicate_evidence_claim_groups:{duplicate_claim_group_count}")
    admission = manifest.get("admission") or {}
    rejected_claim_count = int(admission.get("rejected_claim_count") or 0)
    if rejected_claim_count > 0:
        warnings.append(f"rejected_evidence_claims:{rejected_claim_count}")

    required_present = manifest.get("required_entity_types_present") or {}
    missing_required = sorted(entity_type for entity_type, present in required_present.items() if not present)
    if missing_required:
        errors.append(f"missing_required_entity_types:{','.join(missing_required)}")

    profile_entity_types = set(manifest.get("profile_entity_types") or [])
    lineage_relation = str(manifest.get("lineage_relation") or "summarizes_evidence_claim")
    evidence_ids = {
        str(entity.get("entity_id"))
        for entity in entities
        if entity.get("entity_type") == "evidence_claim"
    }
    lineage_targets = {
        str(relationship.get("target_id"))
        for relationship in relationships
        if relationship.get("relation_type") == lineage_relation
    }
    for entity in entities:
        if entity.get("entity_type") not in profile_entity_types:
            continue
        attrs = entity.get("attributes") or {}
        claim_ids = [str(claim_id) for claim_id in attrs.get("evidence_claim_ids") or []]
        if int(attrs.get("claim_count") or 0) > 0 and not claim_ids:
            errors.append(f"profile_missing_evidence:{entity.get('entity_id')}")
        missing_claims = [claim_id for claim_id in claim_ids if claim_id not in evidence_ids]
        if missing_claims:
            errors.append(f"profile_unknown_evidence:{entity.get('entity_id')}")
        unlinked_claims = [claim_id for claim_id in claim_ids if claim_id not in lineage_targets]
        if unlinked_claims:
            errors.append(f"profile_unlinked_evidence:{entity.get('entity_id')}")

    backlog = audit.get("scouting_backlog") or {}
    if readiness.get("scouting_complete") and int(backlog.get("item_count") or 0) > 0:
        warnings.append("audit_backlog_present_but_manifest_complete")

    return {
        "passes": not errors,
        "errors": errors,
        "warnings": warnings,
        "kg_load_ready": bool(readiness.get("kg_load_ready")),
        "scouting_complete": bool(readiness.get("scouting_complete")),
        "status": readiness.get("status"),
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "entrypoint_entity_types": list(manifest.get("entrypoint_entity_types") or []),
    }


def _compact_entity(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "entity_id": entity.get("entity_id"),
        "entity_type": entity.get("entity_type"),
        "name": entity.get("name"),
        "attributes": dict(entity.get("attributes") or {}),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise KGIngestionError(f"Missing KG artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise KGIngestionError(f"Invalid JSON KG artifact: {path}") from exc
    if not isinstance(data, dict):
        raise KGIngestionError(f"Expected JSON object in KG artifact: {path}")
    return data


def _expect(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)
