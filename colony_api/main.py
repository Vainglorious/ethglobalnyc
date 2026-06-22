"""FastAPI wrapper around the Colony CLI pipeline.

The first deployment goal is intentionally narrow: keep the existing harness as
the source of truth, run it as a managed subprocess, and expose run artifacts and
an SSE stream to the frontend or demo tooling.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = REPO_ROOT / "colony" / "runs" / "api"
RUNS_ROOT = Path(os.environ.get("COLONY_API_RUNS_DIR", str(DEFAULT_RUNS_ROOT))).resolve()
RUN_DEMO = REPO_ROOT / "colony" / "run_demo.py"
RUN_MATCH = REPO_ROOT / "colony" / "run_match.py"
RUN_SUPABASE_COLONY = REPO_ROOT / "colony" / "tools" / "run_supabase_colony.py"
SCOUTING_MATRIX = REPO_ROOT / "colony" / "scouting_matrix.py"
SCOUTING_SOURCE_CATALOG = REPO_ROOT / "colony" / "config" / "scouting_source_catalog.json"
COLONY_ENV = REPO_ROOT / "colony" / ".env"
WORLD_CUP_KG = REPO_ROOT / "colony" / "data" / "world_cup_kg.json"
WORLD_CUP_KG_SUMMARY = REPO_ROOT / "colony" / "data" / "world_cup_kg.summary.md"
PREMATCH_SCRAPE_ROOT = Path(
    os.environ.get("COLONY_PREMATCH_SCRAPE_ROOT", str(REPO_ROOT / "colony" / "runs" / "prematch_scrape"))
).resolve()
DEFAULT_PUBLIC_WALLET_STORE = "colony/data/agent-wallets.dynamic.200.public.json"
DEFAULT_LOCAL_WALLET_STORE = "colony/secrets/agent-wallets.local.json"
DEFAULT_FORECAST_MARKET_KEY = "worldcup:2026:brazil-morocco:frontend-demo"
FORECAST_CLI = REPO_ROOT / "arc" / "forecast-market.mjs"
X402_SERVICE_CLI = REPO_ROOT / "arc" / "x402-agent-service.mjs"
X402_PAY_CLI = REPO_ROOT / "arc" / "x402-agent-pay.mjs"
DEFAULT_FORECAST_CONTRACT = "0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87"
CHILD_ANTS_PATH = RUNS_ROOT / "child_ants.json"
ANT_STATE_PATH = RUNS_ROOT / "ant_state.json"
FUND_AGENTS_CLI = REPO_ROOT / "arc" / "fund-agents.mjs"
REGISTER_ENS_IDENTITIES = REPO_ROOT / "colony" / "register_ens_identities.py"
DEFAULT_PUBLIC_API_BASE_URL = "https://ethglobalnyc-production.up.railway.app"
RUN_EVENT_LOCK = threading.Lock()
DEFAULT_KG_RUN_MODULES = ["fixture", "public_x", "polymarket_market_context", "wikidata_profiles"]

COLONY_SRC = REPO_ROOT / "colony"
if str(COLONY_SRC) not in sys.path:
    sys.path.insert(0, str(COLONY_SRC))

from colony_harness.ant_records import generate_ant_rows, next_agent_index  # noqa: E402
from colony_harness.colony_config import (  # noqa: E402
    ALLOWED_ANT_COUNTS,
    ALLOWED_PRESETS,
    ALLOWED_RISK_PROFILES,
    CONFIG_SCHEMA_VERSION,
    MODEL_SPECIES,
    describe_colony_config,
    normalize_colony_config,
)
from colony_harness.genes import Genome, SourceWeights, mutate_genome  # noqa: E402
from colony_harness.supabase_client import (  # noqa: E402
    SupabaseRequestError,
    delete_colony,
    delete_colony_ants,
    fetch_colony,
    fetch_colony_ants,
    load_supabase_settings,
    update_ant_status,
    upsert_colony,
    upsert_colony_ants,
)
from colony_harness.wallets import WalletStore  # noqa: E402

ENS_ADJECTIVES = [
    "amber",
    "brisk",
    "cold",
    "ember",
    "fable",
    "gold",
    "iron",
    "lumen",
    "onyx",
    "quiet",
    "sable",
    "silver",
]


class DemoRunRequest(BaseModel):
    agents: int = Field(default=200, ge=1, le=500)
    rooms: int = Field(default=12, ge=1, le=50)
    seed: int | None = Field(default=205, ge=0)
    match: str | None = None
    match_id: str | None = None
    voice_mode: Literal["template", "llm"] = "llm"
    debug: bool = False
    agent_wallets: bool = True
    wallet_provider: Literal["local", "dynamic"] | None = "dynamic"
    wallet_store: str | None = DEFAULT_PUBLIC_WALLET_STORE
    # Optional fixture binding so the run's metadata.json records which
    # market this run is for. /forecast/settle's _validate_forecast_run_match
    # reads this to confirm settle-time market_key matches the run.
    match: str | None = None
    match_id: str | None = None
    home_team: str | None = None
    away_team: str | None = None


class ScoutingRunRequest(BaseModel):
    match: str = "Brazil vs Morocco"
    match_id: str | None = None
    data_mode: Literal["synthetic", "public", "openfootball"] = "openfootball"
    refresh_data: bool = False
    include_deepseek_scout: bool = False
    include_camel: bool = False
    include_x: bool = False
    include_telegram: bool = False
    include_polygun: bool = False
    agents: int = Field(default=20, ge=1, le=200)
    rooms: int = Field(default=5, ge=1, le=50)
    seed: int = Field(default=12, ge=0)
    voice_mode: Literal["template", "llm"] = "template"
    debug: bool = True
    agent_wallets: bool = True
    wallet_provider: Literal["local", "dynamic"] | None = "dynamic"
    wallet_store: str | None = DEFAULT_PUBLIC_WALLET_STORE


class KGRunRequest(BaseModel):
    match: str = "Brazil vs Morocco"
    match_id: str | None = None
    mode: Literal["fast", "deep"] = "fast"
    modules: list[str] = Field(
        default_factory=lambda: list(DEFAULT_KG_RUN_MODULES),
        min_length=1,
        max_length=12,
    )
    timeout: int = Field(default=120, ge=5, le=300)
    camel_agents: int = Field(default=4, ge=0, le=12)


class UserColonyConfigRequest(BaseModel):
    ant_count: Literal[50, 100, 200] = 50
    preset: Literal["market", "scout", "quant"] = "market"
    risk_profile: Literal["cautious", "balanced", "aggressive"] = "balanced"
    model_preference: str = "mixed"
    personality_mix: list[str] | None = None
    kg_focus: list[str] | None = None
    source_weights: dict[str, float] | None = None


class UserColonyUpsertRequest(BaseModel):
    pubkey: str = Field(min_length=1)
    angle: float = 0.0
    dist: float = 120.0
    accent: int = 0xB07E1C
    name: str | None = None
    visibility: Literal["public", "private", "unlisted"] = "public"
    config: UserColonyConfigRequest = Field(default_factory=UserColonyConfigRequest)


class UserColonyAntRosterRequest(BaseModel):
    target_count: Literal[50, 100, 200] | None = None
    count: int | None = Field(default=None, ge=1, le=200)
    replace: bool = False
    seed: int = Field(default=42, ge=0)


class UserColonyAntStatusRequest(BaseModel):
    status: Literal["alive", "dead", "inactive", "retired"]


class UserColonyRunRequest(BaseModel):
    match: str = "Brazil vs Morocco"
    match_id: str | None = None
    data_mode: Literal["synthetic", "public", "openfootball"] = "public"
    rooms: int = Field(default=5, ge=1, le=50)
    agents: int | None = Field(default=None, ge=1, le=200)
    seed: int = Field(default=42, ge=0)
    voice_mode: Literal["template", "llm"] = "template"
    refresh_data: bool = False
    include_camel: bool = False
    include_x: bool = False
    include_telegram: bool = False
    include_polygun: bool = False
    include_deepseek_scout: bool = False
    debug: bool = True


class RunRecord(BaseModel):
    id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    returncode: int | None = None
    command: list[str]
    run_dir: str
    events_path: str
    compact_runs_dir: str


class ForecastDeployRequest(BaseModel):
    treasury: str | None = None


class ForecastCreateMarketRequest(BaseModel):
    contract: str | None = None
    market_key: str = DEFAULT_FORECAST_MARKET_KEY
    market_type: Literal["three_way", "binary"] = "three_way"
    close_time: int = Field(default=0, ge=0)
    fee_bps: int = Field(default=1000, ge=0, le=2000)
    metadata_uri: str = DEFAULT_FORECAST_MARKET_KEY


class ForecastStakeInstruction(BaseModel):
    agent: str
    outcome: Literal["home", "draw", "away"]
    amount: str = "0.001"


class ForecastDemoSetupRequest(ForecastCreateMarketRequest):
    wallet_store: str = DEFAULT_LOCAL_WALLET_STORE
    stakes: list[ForecastStakeInstruction] | None = None
    run_id: str | None = None
    expected_match_id: str | None = None
    max_stakers: int = Field(default=3, ge=1, le=25)
    stake_scale: float = Field(default=0.0001, gt=0.0, le=1.0)
    fund_stakers: bool | None = None
    fund_amount: str = "0.01"
    wait_for_run_forecasts: bool | None = None
    run_forecast_timeout_seconds: int = Field(default=180, ge=0, le=600)
    allow_fallback_stakes: bool = True


class ForecastSettleRequest(BaseModel):
    contract: str | None = None
    market_key: str = "worldcup:2026:brazil-morocco:frontend-demo"
    winner: str = "home"
    home_team: str = "Brazil"
    away_team: str = "Morocco"
    wallet_store: str = DEFAULT_LOCAL_WALLET_STORE
    claim_winners: bool = True
    withdraw_treasury: bool = True
    winning_agents: list[str] | None = None


class X402DemoPaymentRequest(BaseModel):
    buyer: str = "ant_0001"
    seller: str = "ant_0002"
    service: Literal["summary", "audit", "finding_shared", "finding_private"] = "finding_private"
    wallet_store: str = DEFAULT_LOCAL_WALLET_STORE
    deposit: str | None = None
    round_id: str = "worldcup:2026:brazil-morocco:x402-demo"
    resource_id: str = "kg:worldcup:brazil-morocco:private-scout-signal"
    topic: str = "Brazil vs Morocco"


class AntReproduceRequest(BaseModel):
    parent_agent_id: str
    wallet_provider: Literal["local", "dynamic"] | None = None
    wallet_store: str | None = None
    mutation_rate: float = Field(default=0.08, ge=0.0, le=0.5)
    initial_bankroll: float = Field(default=0.05, ge=0.0, le=100.0)
    fund_amount: str = "0.05"
    fund_wallet: bool = True
    broadcast_funding: bool | None = None
    publish_ens: bool = True
    broadcast_ens: bool | None = None


class AntKillRequest(BaseModel):
    reason: str = "manual"
    publish_ens: bool = True
    broadcast_ens: bool | None = None


class AntAvatarRequest(BaseModel):
    variant: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id


def _metadata_path(run_id: str) -> Path:
    return _run_dir(run_id) / "metadata.json"


def _read_metadata(run_id: str) -> dict:
    path = _metadata_path(run_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _run_created_sort_key(metadata: dict) -> str:
    return str(
        metadata.get("created_at")
        or metadata.get("started_at")
        or metadata.get("completed_at")
        or metadata.get("id")
        or ""
    )


def _write_metadata(run_id: str, payload: dict) -> None:
    path = _metadata_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_run_event(run_id: str, event: dict) -> None:
    path = _run_dir(run_id) / "events.jsonl"
    payload = {
        "timestamp": _utc_now(),
        **event,
    }
    with RUN_EVENT_LOCK:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def _supabase_settings_or_503():
    try:
        return load_supabase_settings(COLONY_ENV)
    except SupabaseRequestError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _run_supabase_call(func):
    try:
        return func()
    except SupabaseRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _clean_pubkey(pubkey: str) -> str:
    cleaned = str(pubkey or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="pubkey is required")
    return cleaned


def _short_pubkey(pubkey: str) -> str:
    return pubkey if len(pubkey) <= 12 else f"{pubkey[:4]}...{pubkey[-4:]}"


def _default_colony_name(pubkey: str) -> str:
    return f"Colony {_short_pubkey(pubkey)}"


def _colony_config_from_request(config: UserColonyConfigRequest | dict | None) -> dict:
    if isinstance(config, UserColonyConfigRequest):
        payload = config.dict(exclude_none=True)
    else:
        payload = dict(config or {})
    if str(payload.get("model_preference") or "") not in MODEL_SPECIES:
        raise HTTPException(status_code=400, detail=f"Unsupported model_preference: {payload.get('model_preference')}")
    return normalize_colony_config(payload)


def _colony_ant_summary(rows: list[dict]) -> dict:
    statuses: dict[str, int] = {}
    models: dict[str, int] = {}
    personas: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status") or "")
        model = str(row.get("model") or "")
        persona = str(row.get("persona") or "")
        if status:
            statuses[status] = statuses.get(status, 0) + 1
        if model:
            models[model] = models.get(model, 0) + 1
        if persona:
            personas[persona] = personas.get(persona, 0) + 1
    return {
        "total": len(rows),
        "statuses": dict(sorted(statuses.items())),
        "models": dict(sorted(models.items())),
        "personas": dict(sorted(personas.items())),
    }


def _colony_payload(settings, pubkey: str) -> dict:
    row = fetch_colony(settings, pubkey, select="*")
    if row is None:
        raise HTTPException(status_code=404, detail=f"Colony not found: {pubkey}")
    ants = fetch_colony_ants(
        settings,
        pubkey,
        status="all",
        select="agent_id,status,model,persona,risk_profile,datafeed_interests,parent_agent_id,generation,genome_id,updated_at",
    )
    return {
        "colony": row,
        "config_description": describe_colony_config(row.get("config") if isinstance(row.get("config"), dict) else {}),
        "ant_summary": _colony_ant_summary(ants),
    }


def _ensure_colony_ant_roster(settings, pubkey: str, request: UserColonyAntRosterRequest) -> dict:
    colony = fetch_colony(settings, pubkey, select="pubkey,name,config")
    if colony is None:
        raise HTTPException(status_code=404, detail=f"Colony not found: {pubkey}")
    colony_config = normalize_colony_config(colony.get("config") if isinstance(colony.get("config"), dict) else {})
    if request.count is not None and request.target_count is not None:
        raise HTTPException(status_code=400, detail="Use either count or target_count, not both")

    existing = [] if request.replace else fetch_colony_ants(settings, pubkey, status="all", select="agent_id")
    deleted: list[dict] = []
    if request.replace:
        deleted = delete_colony_ants(settings, pubkey)

    if request.count is not None:
        start_index = next_agent_index(existing)
        target_count = start_index + request.count
        max_count = max(ALLOWED_ANT_COUNTS)
        if target_count > max_count:
            raise HTTPException(status_code=400, detail=f"Max supported roster size is {max_count}")
        min_agent_index = start_index
    else:
        target_count = int(request.target_count or colony_config["ant_count"])
        min_agent_index = 0
    if target_count not in ALLOWED_ANT_COUNTS and request.count is None:
        raise HTTPException(status_code=400, detail=f"target_count must be one of {sorted(ALLOWED_ANT_COUNTS)}")

    existing_ids = {str(row.get("agent_id") or "") for row in existing}
    generated_rows = generate_ant_rows(
        pubkey=pubkey,
        colony_config=colony_config,
        population_size=target_count,
        seed=request.seed,
        status="alive",
    )
    rows_to_write = [
        row
        for row in generated_rows
        if row["agent_id"] not in existing_ids and _agent_index(row["agent_id"]) >= min_agent_index
    ]
    written = upsert_colony_ants(settings, rows_to_write) if rows_to_write else []
    roster = fetch_colony_ants(
        settings,
        pubkey,
        status="all",
        select="agent_id,status,model,persona,risk_profile,datafeed_interests,parent_agent_id,generation,genome_id,updated_at",
    )
    return {
        "pubkey": pubkey,
        "target_count": target_count,
        "deleted": len(deleted),
        "written": len(written),
        "ant_summary": _colony_ant_summary(roster),
        "ants": roster,
    }


def _agent_index(agent_id: str) -> int:
    match = re.fullmatch(r"ant_(\d+)", str(agent_id))
    if not match:
        return 0
    return int(match.group(1))


def _safe_artifact_path(run_id: str, relative_path: str) -> Path:
    base = _run_dir(run_id).resolve()
    target = (base / relative_path).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(status_code=400, detail="Artifact path escapes run directory")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {relative_path}")
    return target


def _safe_repo_path(path_value: str) -> Path:
    target = (REPO_ROOT / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value).resolve()
    if target != REPO_ROOT and REPO_ROOT not in target.parents:
        raise HTTPException(status_code=400, detail="Path escapes repository")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path_value}")
    return target


def _latest_compact_dir(run_id: str) -> Path | None:
    compact_root = _run_dir(run_id) / "compact"
    if not compact_root.exists():
        return None
    children = [path for path in compact_root.iterdir() if path.is_dir()]
    if not children:
        return None
    return sorted(children)[-1]


def _latest_compact_artifact(run_id: str, filename: str) -> Path:
    latest = _latest_compact_dir(run_id)
    if latest is None:
        raise HTTPException(status_code=404, detail=f"No compact artifacts for run: {run_id}")
    path = latest / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {filename}")
    return path


def _read_latest_compact_json(run_id: str, filename: str) -> dict | None:
    latest = _latest_compact_dir(run_id)
    if latest is None:
        return None
    path = latest / filename
    if not path.exists() or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _compact_artifact_url(run_id: str, filename: str) -> str | None:
    latest = _latest_compact_dir(run_id)
    if latest is None:
        return None
    path = latest / filename
    if not path.exists() or not path.is_file():
        return None
    relative = path.relative_to(_run_dir(run_id)).as_posix()
    return f"/runs/{run_id}/artifacts/{relative}"


def _read_events(run_id: str) -> list[dict]:
    path = _safe_artifact_path(run_id, "events.jsonl")
    events: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _latest_event(run_id: str, event_type: str) -> dict | None:
    try:
        events = _read_events(run_id)
    except HTTPException:
        return None
    latest = None
    for event in events:
        if event.get("event_type") == event_type:
            latest = event
    return latest


def _agent_predictions_with_forecasts(run_id: str, decision: dict | None) -> list[dict]:
    predictions = [
        dict(item)
        for item in ((decision or {}).get("agent_predictions") or [])
        if isinstance(item, dict)
    ]
    try:
        events = _read_events(run_id)
    except HTTPException:
        events = []
    forecasts_by_agent = {
        str(event.get("agent_id")): event
        for event in events
        if event.get("event_type") == "forecast" and event.get("agent_id")
    }
    seen = {str(item.get("agent_id")) for item in predictions if item.get("agent_id")}
    for item in predictions:
        agent_id = str(item.get("agent_id") or "")
        forecast = forecasts_by_agent.get(agent_id)
        if forecast:
            item["forecast"] = {
                "side": forecast.get("side"),
                "stake": forecast.get("stake"),
                "home_probability": forecast.get("home_probability"),
                "edge": forecast.get("edge"),
                "market_edge": forecast.get("market_edge"),
                "bankroll": forecast.get("bankroll"),
                "decision_reason": forecast.get("decision_reason"),
            }
    for agent_id, forecast in sorted(forecasts_by_agent.items()):
        if agent_id in seen:
            continue
        predictions.append(
            {
                "agent_id": agent_id,
                "ens_name": forecast.get("ens_name"),
                "model": forecast.get("model"),
                "persona": forecast.get("persona"),
                "risk_profile": forecast.get("risk_profile"),
                "bet_intent": {
                    "side": forecast.get("side"),
                    "value": forecast.get("edge"),
                    "risk_profile": forecast.get("risk_profile"),
                },
                "forecast": {
                    "side": forecast.get("side"),
                    "stake": forecast.get("stake"),
                    "home_probability": forecast.get("home_probability"),
                    "edge": forecast.get("edge"),
                    "market_edge": forecast.get("market_edge"),
                    "bankroll": forecast.get("bankroll"),
                    "decision_reason": forecast.get("decision_reason"),
                },
            }
        )
    return predictions


def _prediction_record(
    metadata: dict,
    *,
    include_incomplete: bool = True,
    include_agents: bool = False,
) -> dict | None:
    run_id = str(metadata.get("id") or "")
    if not run_id:
        return None
    decision = _read_latest_compact_json(run_id, "decision.json")
    if decision is None:
        decision = _read_latest_compact_json(run_id, "decision.compact.json")
    if decision is None:
        event_decision = _latest_event(run_id, "collective_decision")
        if event_decision:
            decision = {key: value for key, value in event_decision.items() if key != "event_type"}
    if decision is None and not include_incomplete:
        return None

    audit = _read_latest_compact_json(run_id, "scouting_audit.json") or {}
    manifest = _read_latest_compact_json(run_id, "kg_manifest.json") or {}
    readiness = audit.get("kg_readiness") or audit.get("readiness") or {}
    vote_breakdown = (decision or {}).get("vote_breakdown") or {}
    internal_metrics = (decision or {}).get("internal_metrics") or {}
    match = dict((decision or {}).get("match") or {})
    if metadata.get("match") and not match.get("name"):
        match["name"] = metadata.get("match")
    if metadata.get("match_id") and not match.get("match_id"):
        match["match_id"] = metadata.get("match_id")

    artifacts = {
        "summary": _compact_artifact_url(run_id, "summary.md"),
        "decision": _compact_artifact_url(run_id, "decision.compact.json"),
        "full_decision": _compact_artifact_url(run_id, "decision.json"),
        "forecasts": _compact_artifact_url(run_id, "forecasts.csv"),
        "kg": f"/runs/{run_id}/kg" if _latest_compact_dir(run_id) is not None else None,
        "kg_manifest": f"/runs/{run_id}/kg/manifest" if manifest else None,
        "scouting_audit": f"/runs/{run_id}/scouting-audit" if audit else None,
        "events": f"/runs/{run_id}/events" if (_run_dir(run_id) / "events.jsonl").exists() else None,
    }

    record = {
        "run_id": run_id,
        "kind": metadata.get("kind") or "demo",
        "status": metadata.get("status"),
        "created_at": metadata.get("created_at"),
        "started_at": metadata.get("started_at"),
        "completed_at": metadata.get("completed_at"),
        "data_mode": metadata.get("data_mode"),
        "match": match,
        "prediction": (decision or {}).get("prediction"),
        "recommendation": (decision or {}).get("recommendation"),
        "match_call": (decision or {}).get("match_call"),
        "score_projection": (decision or {}).get("score_projection"),
        "metrics": {
            "confidence": internal_metrics.get("confidence"),
            "market_edge": internal_metrics.get("market_edge"),
            "prediction_value_signal": internal_metrics.get("prediction_value_signal"),
            "weighted_home_probability": internal_metrics.get("weighted_home_probability"),
            "calibrated_home_probability": internal_metrics.get("calibrated_home_probability"),
        },
        "vote_breakdown": vote_breakdown,
        "scouting": {
            "kg_load_ready": readiness.get("kg_load_ready"),
            "scouting_complete": readiness.get("scouting_complete"),
            "status": readiness.get("status"),
            "backlog_count": readiness.get("scouting_backlog_count") or readiness.get("backlog_count"),
            "entity_count": manifest.get("entity_count") or (manifest.get("counts") or {}).get("entities"),
            "relationship_count": manifest.get("relationship_count") or (manifest.get("counts") or {}).get("relationships"),
        },
        "artifacts": {key: value for key, value in artifacts.items() if value},
    }
    if include_agents:
        record["agent_predictions"] = _agent_predictions_with_forecasts(run_id, decision)
        record["top_supporters"] = (decision or {}).get("top_supporters") or []
    return record


def _match_text_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _match_words(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _split_match_teams(match: str | None) -> tuple[str, str] | None:
    parts = re.split(r"\s+v(?:s\.?)?\s+", str(match or "").strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None
    home = parts[0].strip()
    away = parts[1].strip()
    if not home or not away:
        return None
    return home, away


def _safe_probability(value) -> float | None:
    try:
        probability = float(value)
    except (TypeError, ValueError):
        return None
    if probability <= 0.0 or probability >= 1.0:
        return None
    return probability


def _market_claim_price(metrics: dict) -> float | None:
    for key in ("clob_midpoint", "price", "last_price", "best_ask", "best_bid"):
        probability = _safe_probability(metrics.get(key))
        if probability is not None:
            return probability
    return None


def _market_claim_side(claim: dict, *, home_team: str, away_team: str) -> str | None:
    metrics = claim.get("metrics") if isinstance(claim.get("metrics"), dict) else {}
    question = str(metrics.get("question") or claim.get("claim") or claim.get("subject") or "")
    words = _match_words(question)
    home = _match_words(home_team)
    away = _match_words(away_team)
    if "draw" in words:
        return "draw"
    if "win" not in words:
        return None
    if home and home in words:
        return "home"
    if away and away in words:
        return "away"
    return None


def _market_side_probabilities_from_findings(findings_path: Path, *, home_team: str, away_team: str) -> dict[str, float]:
    try:
        payload = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(payload, dict):
        findings = payload.get("findings") or []
    elif isinstance(payload, list):
        findings = payload
    else:
        findings = []

    probabilities: dict[str, float] = {}
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        for claim in finding.get("evidence_claims") or []:
            if not isinstance(claim, dict):
                continue
            metrics = claim.get("metrics") if isinstance(claim.get("metrics"), dict) else {}
            if claim.get("claim_type") != "market_snapshot":
                continue
            if str(metrics.get("outcome") or "").casefold() != "yes":
                continue
            side = _market_claim_side(claim, home_team=home_team, away_team=away_team)
            price = _market_claim_price(metrics)
            if side and price is not None:
                probabilities[side] = price
    return probabilities


def _metadata_matches_request(metadata: dict, *, match: str, match_id: str | None) -> bool:
    if match_id and metadata.get("match_id") == match_id:
        return True
    return bool(match and _match_text_key(metadata.get("match")) == _match_text_key(match))


def _latest_market_override_for_match(match: str, match_id: str | None) -> dict | None:
    teams = _split_match_teams(match)
    if teams is None or not RUNS_ROOT.exists():
        return None
    home_team, away_team = teams
    candidates: list[dict] = []
    for path in RUNS_ROOT.glob("kg_*/metadata.json"):
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get("kind") != "kg" or metadata.get("status") != "succeeded":
            continue
        if not _metadata_matches_request(metadata, match=match, match_id=match_id):
            continue
        candidates.append(metadata)
    candidates.sort(key=lambda item: str(item.get("completed_at") or item.get("created_at") or ""), reverse=True)

    for metadata in candidates:
        run_id = str(metadata.get("id") or "")
        latest = _latest_compact_dir(run_id)
        if latest is None:
            continue
        side_probabilities = _market_side_probabilities_from_findings(
            latest / "findings.json",
            home_team=home_team,
            away_team=away_team,
        )
        home = side_probabilities.get("home")
        away = side_probabilities.get("away")
        if home is None or away is None or (home + away) <= 0:
            continue
        home_anchor = home / (home + away)
        return {
            "home_anchor": round(home_anchor, 6),
            "side_probabilities": {key: round(value, 6) for key, value in side_probabilities.items()},
            "source": f"Polymarket KG {run_id}",
            "kg_run_id": run_id,
            "home_team": home_team,
            "away_team": away_team,
        }
    return None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _configured_env_names() -> set[str]:
    names = {key for key, value in os.environ.items() if str(value).strip()}
    if COLONY_ENV.exists():
        for raw_line in COLONY_ENV.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and value:
                names.add(key)
    return names


def _load_scouting_source_catalog() -> dict:
    if not SCOUTING_SOURCE_CATALOG.exists():
        return {"modules": {}}
    try:
        payload = json.loads(SCOUTING_SOURCE_CATALOG.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"modules": {}}
    return payload if isinstance(payload, dict) else {"modules": {}}


def _module_env_requirements(
    module_id: str,
    modules: dict,
    *,
    seen: set[str] | None = None,
) -> tuple[set[str], list[list[str]]]:
    seen = seen or set()
    if module_id in seen:
        return set(), []
    seen.add(module_id)
    module = modules.get(module_id) or {}
    required = {str(name) for name in module.get("requires_env", []) if str(name).strip()}
    any_groups = [
        [str(name) for name in group if str(name).strip()]
        for group in module.get("requires_any_env", [])
        if isinstance(group, list)
    ]
    for included in module.get("includes", []) or []:
        child_required, child_any_groups = _module_env_requirements(str(included), modules, seen=seen)
        required.update(child_required)
        any_groups.extend(child_any_groups)
    return required, any_groups


def _module_setup_state(module_id: str, modules: dict, configured_env: set[str]) -> dict:
    required, any_groups = _module_env_requirements(module_id, modules)
    missing_required = sorted(name for name in required if name not in configured_env)
    missing_any = [group for group in any_groups if not any(name in configured_env for name in group)]
    return {
        "configured": not missing_required and not missing_any,
        "missing_env": missing_required,
        "missing_any_env": missing_any,
    }


def _kg_module_records() -> list[dict]:
    catalog = _load_scouting_source_catalog()
    modules = catalog.get("modules") or {}
    configured_env = _configured_env_names()
    records: list[dict] = []
    for module_id, module in modules.items():
        if not isinstance(module, dict):
            continue
        if module.get("ui_hidden"):
            continue
        if module.get("status") != "implemented":
            continue
        setup = _module_setup_state(str(module_id), modules, configured_env)
        records.append(
            {
                "id": str(module_id),
                "display_name": module.get("display_name") or str(module_id).replace("_", " ").title(),
                "description": module.get("description") or "",
                "status": module.get("status"),
                "source_family": module.get("source_family") or "",
                "claim_types": list(module.get("claim_types") or []),
                "docs_url": module.get("docs_url") or "",
                "setup_url": module.get("setup_url") or "",
                "setup_hint": module.get("setup_hint") or "",
                "requires_setup": not setup["configured"],
                "configured": setup["configured"],
                "missing_env": setup["missing_env"],
                "missing_any_env": setup["missing_any_env"],
                "default_enabled": str(module_id) in DEFAULT_KG_RUN_MODULES,
                "ui_order": module.get("ui_order", 999),
            }
        )
    return sorted(records, key=lambda item: (item["ui_order"], item["display_name"]))


def _default_wallet_store() -> str:
    return os.environ.get("COLONY_API_DEFAULT_WALLET_STORE", DEFAULT_PUBLIC_WALLET_STORE)


def _agent_number(agent_id: str) -> str:
    match = re.search(r"(\d+)$", agent_id)
    if not match:
        return "0"
    return str(int(match.group(1)))


def _root_ens_name(agent_id: str) -> str:
    digest = hashlib.sha256(agent_id.encode("utf-8")).digest()
    adjective = ENS_ADJECTIVES[digest[0] % len(ENS_ADJECTIVES)]
    parent = os.environ.get("COLONY_ENS_PARENT", "colonny.eth").strip().lower().strip(".")
    return f"root-{adjective}-{_agent_number(agent_id)}.{parent}"


def _ens_parent() -> str:
    return os.environ.get("COLONY_ENS_PARENT", "colonny.eth").strip().lower().strip(".")


def _public_api_base_url() -> str:
    return os.environ.get("COLONY_PUBLIC_API_BASE_URL", DEFAULT_PUBLIC_API_BASE_URL).strip().rstrip("/")


def _avatar_url(agent_id: str) -> str:
    return f"{_public_api_base_url()}/ants/{agent_id}/avatar.svg"


def _safe_repo_write_path(path_value: str) -> Path:
    target = (REPO_ROOT / path_value).resolve() if not Path(path_value).is_absolute() else Path(path_value).resolve()
    in_repo = target == REPO_ROOT or REPO_ROOT in target.parents
    in_runs = target == RUNS_ROOT or RUNS_ROOT in target.parents
    if not in_repo and not in_runs:
        raise HTTPException(status_code=400, detail="Path escapes repository")
    return target


def _read_child_ants() -> list[dict]:
    if not CHILD_ANTS_PATH.exists():
        return []
    payload = json.loads(CHILD_ANTS_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        agents = list(payload.get("agents") or [])
    if isinstance(payload, list):
        agents = payload
    if not isinstance(payload, (dict, list)):
        return []
    for agent in agents:
        agent.update({key: value for key, value in _avatar_record_fields(agent).items() if key not in agent or not agent[key]})
    return agents


def _write_child_ants(agents: list[dict]) -> None:
    CHILD_ANTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": _utc_now(),
        "agents": agents,
    }
    CHILD_ANTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_ant_state() -> dict:
    if not ANT_STATE_PATH.exists():
        return {}
    payload = json.loads(ANT_STATE_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("agents"), dict):
        return dict(payload["agents"])
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _write_ant_state(state: dict) -> None:
    ANT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "updated_at": _utc_now(),
        "agents": state,
    }
    ANT_STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _apply_ant_state(record: dict, state: dict) -> dict:
    agent_state = state.get(str(record.get("agent_id") or "")) or {}
    if isinstance(agent_state, dict):
        record.update(agent_state)
    return record


def _genome_tokens(genome_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(genome_id.encode("utf-8")).digest()
    nouns = ["oracle", "scout", "striker", "market", "signal", "keeper", "wager", "edge", "lens", "runner", "seer", "vector"]
    return ENS_ADJECTIVES[digest[0] % len(ENS_ADJECTIVES)], nouns[digest[1] % len(nouns)]


def _child_ens_name(agent_id: str, genome_id: str) -> str:
    first, second = _genome_tokens(genome_id)
    return f"{first}-{second}-{_agent_number(agent_id)}.{_ens_parent()}"


def _personality_genome(seed_value: str) -> Genome:
    digest = hashlib.sha256(seed_value.encode("utf-8")).digest()
    total = sum(digest[:4]) + 4
    personas = [
        "cold probabilist",
        "market contrarian",
        "news-sensitive scout",
        "risk-on striker",
        "defensive skeptic",
        "crowd watcher",
        "model maximalist",
        "quiet value hunter",
    ]
    return Genome(
        estimator="poisson" if digest[4] % 5 else "llm",
        model="parametric" if digest[4] % 5 else "deepseek-v3.2",
        risk_appetite=round(0.02 + (digest[5] / 255) * 0.22, 4),
        edge_threshold=round(0.01 + (digest[6] / 255) * 0.16, 4),
        source_weights=SourceWeights(
            stats=(digest[0] + 1) / total,
            odds=(digest[1] + 1) / total,
            news=(digest[2] + 1) / total,
            debate=(digest[3] + 1) / total,
        ).normalized(),
        herd_bias=round((digest[7] / 127.5) - 1.0, 4),
        query_budget=round(0.2 + (digest[8] / 255) * 2.2, 4),
        persona=personas[digest[9] % len(personas)],
    )


def _strongest_trait(personality: dict) -> str:
    weights = personality.get("source_weights") or {}
    if weights:
        strongest = max(weights.items(), key=lambda item: float(item[1] or 0))[0]
        return {
            "stats": "stats lens",
            "odds": "market compass",
            "news": "scout satchel",
            "debate": "debate badge",
        }.get(strongest, "signal satchel")
    persona = str(personality.get("persona") or "")
    if "contrarian" in persona:
        return "market compass"
    if "scout" in persona or "news" in persona:
        return "scout satchel"
    if "skeptic" in persona:
        return "debate badge"
    return "signal satchel"


def _avatar_personality_for_record(record: dict) -> dict:
    if isinstance(record.get("personality"), dict):
        return record["personality"]
    seed = "|".join(str(record.get(key) or "") for key in ("agent_id", "ens_name", "wallet_address", "genome_hash"))
    return _personality_genome(seed).to_dict()


def _avatar_record_fields(record: dict) -> dict:
    personality = _avatar_personality_for_record(record)
    return {
        "avatar": _avatar_url(str(record.get("agent_id") or "")),
        "avatar_trait": _strongest_trait(personality),
        "personality": personality,
    }


def _find_parent_ant(parent_agent_id: str) -> dict:
    needle = parent_agent_id.strip()
    if not needle:
        raise HTTPException(status_code=400, detail="parent_agent_id is required")
    for ant in _read_public_ants():
        values = {str(ant.get("agent_id") or ""), str(ant.get("name") or ""), str(ant.get("ens_name") or "")}
        if needle in values:
            return ant
    raise HTTPException(status_code=404, detail=f"Parent ant not found: {parent_agent_id}")


def _next_child_agent_id(existing: list[dict]) -> str:
    max_id = -1
    for ant in _read_public_ants() + existing:
        match = re.search(r"(\d+)$", str(ant.get("agent_id") or ""))
        if match:
            max_id = max(max_id, int(match.group(1)))
    return f"ant_{max_id + 1:04d}"


def _child_identity_text(child: dict) -> dict:
    agent_context = {
        "schema": "ensip-26",
        "kind": "colony_ant",
        "agent_id": child["agent_id"],
        "ens_name": child["ens_name"],
        "active": True,
        "generation": child["generation"],
        "parent": child["parent_ens_name"],
        "lineage": child["lineage_ens_name"],
        "avatar": child["avatar"],
        "wallets": {"evm": child["wallet_address"], "arc_testnet": child["wallet_address"]},
        "personality": child["personality"],
    }
    return {
        "description": "Colony child ant derived from a high-performing parent personality card.",
        "avatar": child["avatar"],
        "agent-context": json.dumps(agent_context, sort_keys=True, separators=(",", ":")),
        "com.colony.agent_id": child["agent_id"],
        "com.colony.parent": child["parent_ens_name"],
        "com.colony.parent_agent_id": child["parent_agent_id"],
        "com.colony.lineage": child["lineage_ens_name"],
        "com.colony.generation": str(child["generation"]),
        "com.colony.genome_id": child["genome_id"],
        "com.colony.genome_hash": child["genome_hash"],
        "com.colony.wallet": child["wallet_address"],
        "com.colony.avatar": child["avatar"],
        "com.colony.avatar_trait": child["avatar_trait"],
    }


def _avatar_svg(agent_id: str) -> str:
    record = _find_parent_ant(agent_id)
    personality = _avatar_personality_for_record(record)
    trait = str(record.get("avatar_trait") or _strongest_trait(personality))
    digest = hashlib.sha256(
        json.dumps({"agent_id": agent_id, "personality": personality, "trait": trait}, sort_keys=True).encode("utf-8")
    ).digest()
    bg = ["#b9e8f2", "#d6f3e6", "#f7dfb6", "#d9ddff", "#f7d4e5"][digest[0] % 5]
    shell = ["#d88933", "#c76b36", "#e0a23d", "#b87447", "#d19152"][digest[1] % 5]
    face = ["#fff4d8", "#ffe8bf", "#f8f0d6"][digest[2] % 3]
    accent = ["#1aa6a6", "#2f8bd6", "#6e78d6", "#3fa86b"][digest[3] % 4]
    blush = "#f2a7a7"
    item = {
        "scout satchel": f'''
          <path d="M82 150 C104 165 150 165 172 150" fill="none" stroke="{accent}" stroke-width="10" stroke-linecap="round"/>
          <rect x="142" y="142" width="25" height="22" rx="6" fill="{accent}" stroke="#202225" stroke-width="4"/>
          <circle cx="154" cy="153" r="3" fill="#e9fbff"/>''',
        "market compass": f'''
          <circle cx="162" cy="144" r="17" fill="{accent}" stroke="#202225" stroke-width="4"/>
          <path d="M157 149 L169 138 L164 153 Z" fill="#ffffff"/>
          <path d="M152 159 H172" stroke="#202225" stroke-width="3" stroke-linecap="round"/>''',
        "stats lens": f'''
          <circle cx="162" cy="145" r="15" fill="#e9fbff" stroke="{accent}" stroke-width="5"/>
          <path d="M173 156 L184 166" stroke="#202225" stroke-width="5" stroke-linecap="round"/>
          <path d="M154 148 L159 142 L164 146 L170 137" fill="none" stroke="#202225" stroke-width="3" stroke-linecap="round"/>''',
        "debate badge": f'''
          <path d="M147 135 h33 a9 9 0 0 1 9 9 v10 a9 9 0 0 1-9 9 h-16 l-10 9 v-9 h-7 a9 9 0 0 1-9-9 v-20 a9 9 0 0 1 9-9z" fill="{accent}" stroke="#202225" stroke-width="4"/>
          <circle cx="154" cy="150" r="3" fill="#fff"/><circle cx="164" cy="150" r="3" fill="#fff"/><circle cx="174" cy="150" r="3" fill="#fff"/>''',
        "signal satchel": f'''
          <path d="M87 150 C108 164 148 164 169 150" fill="none" stroke="{accent}" stroke-width="9" stroke-linecap="round"/>
          <path d="M157 139 q12 10 0 20 q-12-10 0-20z" fill="{accent}" stroke="#202225" stroke-width="4"/>''',
    }.get(trait, "")
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="{agent_id} ant avatar">
      <rect width="256" height="256" fill="{bg}"/>
      <circle cx="128" cy="128" r="105" fill="#ffffff" opacity="0.18"/>
      <path d="M91 80 C74 54 55 45 41 41" fill="none" stroke="#202225" stroke-width="8" stroke-linecap="round"/>
      <path d="M165 80 C182 54 201 45 215 41" fill="none" stroke="#202225" stroke-width="8" stroke-linecap="round"/>
      <circle cx="39" cy="40" r="10" fill="{shell}" stroke="#202225" stroke-width="5"/>
      <circle cx="217" cy="40" r="10" fill="{shell}" stroke="#202225" stroke-width="5"/>
      <ellipse cx="128" cy="137" rx="77" ry="72" fill="{shell}" stroke="#202225" stroke-width="8"/>
      <ellipse cx="128" cy="130" rx="58" ry="50" fill="{face}" stroke="#202225" stroke-width="6"/>
      <ellipse cx="104" cy="124" rx="12" ry="15" fill="#202225"/>
      <ellipse cx="152" cy="124" rx="12" ry="15" fill="#202225"/>
      <circle cx="100" cy="118" r="4" fill="#fff"/>
      <circle cx="148" cy="118" r="4" fill="#fff"/>
      <circle cx="91" cy="142" r="8" fill="{blush}" opacity="0.55"/>
      <circle cx="165" cy="142" r="8" fill="{blush}" opacity="0.55"/>
      <path d="M108 151 Q128 166 148 151" fill="none" stroke="#202225" stroke-width="6" stroke-linecap="round"/>
      <path d="M66 178 C85 197 171 197 190 178 L200 256 H56 Z" fill="#ffe0ea" stroke="#202225" stroke-width="8"/>
      {item}
    </svg>'''


def _resolve_reproduction_wallet_store(request: AntReproduceRequest, provider: str) -> Path:
    env_payload = _wallet_store_env_payload("COLONY_API_REPRODUCTION_WALLETS_JSON")
    if not env_payload and provider == "local":
        env_payload = _wallet_store_env_payload("COLONY_API_FORECAST_WALLETS_JSON")
    if env_payload:
        return Path(
            _write_env_wallet_store(
                env_payload,
                env_name="COLONY_API_REPRODUCTION_WALLETS_JSON",
                target_dir="reproduction_wallets",
            )
        )

    configured = (
        request.wallet_store
        or os.environ.get("COLONY_API_REPRODUCTION_WALLET_STORE")
        or ("colony/secrets/agent-wallets.dynamic.200.json" if provider == "dynamic" else DEFAULT_LOCAL_WALLET_STORE)
    )
    return _safe_repo_write_path(configured)


def _create_child_wallet(agent_id: str, request: AntReproduceRequest) -> tuple[dict, str]:
    provider = request.wallet_provider or os.environ.get("COLONY_API_REPRODUCTION_WALLET_PROVIDER")
    if not provider:
        provider = "dynamic" if os.environ.get("DYNAMIC_ENVIRONMENT_ID") and os.environ.get("DYNAMIC_API_KEY") else "local"
    provider = provider.strip().lower()
    wallet_store_path = _resolve_reproduction_wallet_store(request, provider)
    try:
        wallet = WalletStore(wallet_store_path, provider=provider).get_or_create(agent_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not create {provider} wallet for {agent_id}: {exc}") from exc
    return wallet.public_record, str(wallet_store_path)


def _fund_child_wallet(agent_id: str, wallet_store: str, request: AntReproduceRequest) -> dict:
    if not request.fund_wallet:
        return {"status": "skipped", "reason": "fund_wallet=false"}
    if not FUND_AGENTS_CLI.exists():
        return {"status": "skipped", "reason": "arc/fund-agents.mjs is missing"}
    broadcast = request.broadcast_funding
    if broadcast is None:
        broadcast = _env_bool("COLONY_API_REPRODUCTION_BROADCAST_FUNDING", False)
    out_path = RUNS_ROOT / "funding" / f"fund-{agent_id}-{int(time.time())}.json"
    command = [
        "node",
        str(FUND_AGENTS_CLI),
        "--wallet-store",
        wallet_store,
        "--amount",
        request.fund_amount,
        "--agent",
        agent_id,
        "--out",
        str(out_path),
    ]
    if broadcast:
        command.append("--broadcast")
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, check=False, capture_output=True, text=True, timeout=180)
    except Exception as exc:
        return {"status": "failed", "broadcast": broadcast, "error": str(exc)}
    receipt = {}
    if out_path.exists():
        try:
            receipt = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            receipt = {}
    status = "funded" if broadcast and result.returncode == 0 else "planned" if result.returncode == 0 else "failed"
    return {
        "status": status,
        "broadcast": broadcast,
        "amount_usdc": request.fund_amount,
        "receipt_path": str(out_path),
        "returncode": result.returncode,
        "stdout": result.stdout[-1200:],
        "stderr": result.stderr[-1200:],
        "receipt": receipt,
    }


def _child_ens_record(child: dict) -> dict:
    return _ant_ens_record(child, child.get("ens_text_records") or {})


def _ant_ens_record(ant: dict, text_records: dict) -> dict:
    ens_name = str(ant.get("ens_name") or "")
    parent = _ens_parent()
    suffix = f".{parent}"
    label = ens_name.removesuffix(suffix) if ens_name.endswith(suffix) else ens_name.split(".", 1)[0]
    return {
        "agent_id": ant.get("agent_id"),
        "ens_name": ens_name,
        "label": label,
        "addr": ant.get("wallet_address") or "",
        "text": text_records,
    }


def _publish_child_ens(child: dict, request: AntReproduceRequest) -> dict:
    if not request.publish_ens:
        return {"status": "skipped", "reason": "publish_ens=false"}
    if not REGISTER_ENS_IDENTITIES.exists():
        return {"status": "skipped", "reason": "colony/register_ens_identities.py is missing"}
    broadcast = request.broadcast_ens
    if broadcast is None:
        broadcast = _env_bool("COLONY_API_REPRODUCTION_BROADCAST_ENS", False)
    identity_path = RUNS_ROOT / "ens" / f"{child['agent_id']}.identity.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_payload = {
        "schema_version": 1,
        "ens_parent": _ens_parent(),
        "records": [_child_ens_record(child)],
    }
    identity_path.write_text(json.dumps(identity_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(REGISTER_ENS_IDENTITIES),
        str(identity_path),
        "--env",
        "colony/.env",
        "--ens-parent",
        _ens_parent(),
        "--agent-id",
        str(child["agent_id"]),
    ]
    if broadcast:
        command.append("--broadcast")
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, env=_x402_env(), check=False, capture_output=True, text=True, timeout=420)
    except Exception as exc:
        return {"status": "failed", "broadcast": broadcast, "identity_path": str(identity_path), "error": str(exc)}
    status = "published" if broadcast and result.returncode == 0 else "planned" if result.returncode == 0 else "failed"
    return {
        "status": status,
        "broadcast": broadcast,
        "identity_path": str(identity_path),
        "returncode": result.returncode,
        "stdout": result.stdout[-2400:],
        "stderr": result.stderr[-2400:],
    }


def _ant_identity_text(ant: dict, *, active: bool, status: str, killed_at: str | None = None, kill_reason: str | None = None) -> dict:
    agent_id = str(ant.get("agent_id") or "")
    ens_name = str(ant.get("ens_name") or _root_ens_name(agent_id))
    generation = int(ant.get("generation") or 0)
    parent_ens = str(ant.get("parent_ens_name") or "")
    lineage_ens = str(ant.get("lineage_ens_name") or ant.get("lineage") or ens_name)
    profile_url = str(ant.get("profile_url") or f"{_public_api_base_url()}/ants/{agent_id}.json")
    avatar = str(ant.get("avatar") or _avatar_url(agent_id))
    personality = _avatar_personality_for_record(ant)
    description = (
        f"Colony ant {ens_name} is inactive; killed for {kill_reason or 'manual'}."
        if not active
        else f"Colony ant {ens_name} is active in the forecast colony."
    )
    agent_context = {
        "schema": "ensip-26",
        "kind": "colony_ant",
        "agent_id": agent_id,
        "ens_name": ens_name,
        "display_name": ens_name.split(".", 1)[0].replace("-", " ").title(),
        "description": description,
        "active": active,
        "status": status,
        "generation": generation,
        "parent": parent_ens,
        "lineage": lineage_ens,
        "avatar": avatar,
        "profile": profile_url,
        "wallets": {
            "evm": str(ant.get("wallet_address") or ""),
            "arc_testnet": str(ant.get("wallet_address") or ""),
        },
        "personality": personality,
        "endpoints": {
            "web": profile_url,
        },
    }
    if killed_at:
        agent_context["killed_at"] = killed_at
    if kill_reason:
        agent_context["kill_reason"] = kill_reason
    records = {
        "description": description,
        "url": profile_url,
        "avatar": avatar,
        "agent-context": json.dumps(agent_context, sort_keys=True, separators=(",", ":")),
        "agent-endpoint[web]": profile_url,
        "com.colony.agent_id": agent_id,
        "com.colony.active": "true" if active else "false",
        "com.colony.status": status,
        "com.colony.parent": parent_ens,
        "com.colony.lineage": lineage_ens,
        "com.colony.generation": str(generation),
        "com.colony.profile": profile_url,
        "com.colony.avatar": avatar,
        "com.colony.avatar_trait": str(ant.get("avatar_trait") or _strongest_trait(personality)),
    }
    if killed_at:
        records["com.colony.killed_at"] = killed_at
    if kill_reason:
        records["com.colony.kill_reason"] = kill_reason
    if ant.get("genome_id"):
        records["com.colony.genome_id"] = str(ant.get("genome_id"))
    if ant.get("genome_hash"):
        records["com.colony.genome_hash"] = str(ant.get("genome_hash"))
    if ant.get("wallet_address"):
        records["com.colony.wallet"] = str(ant.get("wallet_address"))
    return records


def _publish_ant_ens_update(
    ant: dict,
    *,
    action: str,
    text_records: dict,
    publish: bool,
    broadcast: bool | None,
) -> dict:
    if not publish:
        return {"status": "skipped", "reason": "publish_ens=false"}
    if not REGISTER_ENS_IDENTITIES.exists():
        return {"status": "skipped", "reason": "colony/register_ens_identities.py is missing"}
    if broadcast is None:
        broadcast = _env_bool(f"COLONY_API_{action.upper()}_BROADCAST_ENS", False)
    agent_id = str(ant.get("agent_id") or "")
    identity_path = RUNS_ROOT / "ens" / f"{agent_id}.{action}.identity.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    identity_payload = {
        "schema_version": 1,
        "ens_parent": _ens_parent(),
        "records": [_ant_ens_record(ant, text_records)],
    }
    identity_path.write_text(json.dumps(identity_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    command = [
        sys.executable,
        str(REGISTER_ENS_IDENTITIES),
        str(identity_path),
        "--env",
        "colony/.env",
        "--ens-parent",
        _ens_parent(),
        "--agent-id",
        agent_id,
    ]
    if broadcast:
        command.append("--broadcast")
    try:
        result = subprocess.run(command, cwd=REPO_ROOT, env=_x402_env(), check=False, capture_output=True, text=True, timeout=420)
    except Exception as exc:
        return {"status": "failed", "broadcast": broadcast, "identity_path": str(identity_path), "error": str(exc)}
    status = "published" if broadcast and result.returncode == 0 else "planned" if result.returncode == 0 else "failed"
    return {
        "status": status,
        "broadcast": broadcast,
        "identity_path": str(identity_path),
        "returncode": result.returncode,
        "stdout": result.stdout[-2400:],
        "stderr": result.stderr[-2400:],
    }


def _fund_forecast_stakers(wallet_store: str, stakes: list[ForecastStakeInstruction], amount: str, broadcast: bool) -> dict:
    agents = sorted({stake.agent for stake in stakes if stake.agent})
    if not agents:
        return {"status": "skipped", "reason": "no stakers"}
    if not FUND_AGENTS_CLI.exists():
        return {"status": "skipped", "reason": "arc/fund-agents.mjs is missing"}
    out_path = RUNS_ROOT / "funding" / f"forecast-stakers-{int(time.time())}.json"
    command = [
        "node",
        str(FUND_AGENTS_CLI),
        "--wallet-store",
        wallet_store,
        "--amount",
        amount,
        "--out",
        str(out_path),
    ]
    for agent in agents:
        command.extend(["--agent", agent])
    if broadcast:
        command.append("--broadcast")
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=_x402_env(),
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not fund forecast stakers: {exc}") from exc

    receipt = {}
    if out_path.exists():
        try:
            receipt = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            receipt = {}
    status = "funded" if broadcast and completed.returncode == 0 else "planned" if completed.returncode == 0 else "failed"
    payload = {
        "ok": completed.returncode == 0,
        "action": "fund-forecast-stakers",
        "status": status,
        "broadcast": broadcast,
        "agents": agents,
        "amount_usdc": amount,
        "command": command,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "returncode": completed.returncode,
        "receipt_path": str(out_path),
        "receipt": receipt,
    }
    if completed.returncode != 0:
        raise HTTPException(status_code=500, detail=payload)
    return payload


def _read_public_ants() -> list[dict]:
    state = _read_ant_state()
    store_path = _safe_repo_path(_default_wallet_store())
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    wallets = payload.get("wallets") or {}
    ants = []
    for agent_id, wallet in sorted(wallets.items()):
        address = str(wallet.get("address") or "")
        record = {
            "agent_id": agent_id,
            "name": agent_id.replace("_", "-"),
            "ens_name": _root_ens_name(agent_id),
            "wallet_address": address,
            "wallet_provider": str(wallet.get("provider") or payload.get("provider") or ""),
            "chains": wallet.get("chains") or {},
        }
        record.update(_avatar_record_fields(record))
        ants.append(_apply_ant_state(record, state))
    children = [_apply_ant_state(child, state) for child in _read_child_ants()]
    return ants + children


def _build_command(request: DemoRunRequest, run_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(RUN_DEMO),
        "--agents",
        str(request.agents),
        "--rooms",
        str(request.rooms),
        "--out",
        str(run_dir / "events.jsonl"),
        "--runs-dir",
        str(run_dir / "compact"),
        "--voice-mode",
        request.voice_mode,
    ]
    if request.seed is not None:
        command.extend(["--seed", str(request.seed)])
    if request.match:
        command.extend(["--match", request.match])
    if request.match_id:
        command.extend(["--match-id", request.match_id])
    if request.debug:
        command.append("--debug")
    if request.agent_wallets:
        command.append("--agent-wallets")
        if request.wallet_provider:
            command.extend(["--wallet-provider", request.wallet_provider])
        if request.wallet_store:
            command.extend(["--wallet-store", request.wallet_store])
    return command


def _build_scouting_command(request: ScoutingRunRequest, run_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(RUN_MATCH),
        "--kg",
        str(WORLD_CUP_KG),
        "--match",
        request.match,
        "--data-mode",
        request.data_mode,
        "--agents",
        str(request.agents),
        "--rooms",
        str(request.rooms),
        "--seed",
        str(request.seed),
        "--runs-dir",
        str(run_dir / "compact"),
        "--voice-mode",
        request.voice_mode,
    ]
    if request.match_id:
        command.extend(["--match-id", request.match_id])
    if request.refresh_data:
        command.append("--refresh-data")
    if request.include_deepseek_scout:
        command.append("--include-deepseek-scout")
    if request.include_camel:
        command.append("--include-camel")
    if request.include_x:
        command.append("--include-x")
    if request.include_telegram:
        command.append("--include-telegram")
    if request.include_polygun:
        command.append("--include-polygun")
    if request.debug:
        command.append("--debug")
    if request.agent_wallets:
        command.append("--agent-wallets")
        if request.wallet_provider:
            command.extend(["--wallet-provider", request.wallet_provider])
        if request.wallet_store:
            command.extend(["--wallet-store", request.wallet_store])
    return command


def _build_kg_command(request: KGRunRequest, run_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(SCOUTING_MATRIX),
        "--kg",
        str(WORLD_CUP_KG),
        "--env",
        str(COLONY_ENV),
        "--source-catalog",
        str(SCOUTING_SOURCE_CATALOG),
        "--match",
        request.match,
        "--mode",
        request.mode,
        "--timeout",
        str(request.timeout),
        "--camel-agents",
        str(request.camel_agents),
        "--limit",
        "1",
        "--out-dir",
        str(run_dir / "compact"),
    ]
    for module in request.modules:
        command.extend(["--module", module])
    return command


def _build_colony_run_command(
    pubkey: str,
    request: UserColonyRunRequest,
    run_dir: Path,
    *,
    market_override: dict | None = None,
) -> list[str]:
    command = [
        sys.executable,
        str(RUN_SUPABASE_COLONY),
        "--env",
        str(COLONY_ENV),
        "--pubkey",
        pubkey,
        "--match",
        request.match,
        "--data-mode",
        request.data_mode,
        "--voice-mode",
        request.voice_mode,
        "--seed",
        str(request.seed),
        "--runs-dir",
        str(run_dir / "compact"),
        "--rooms",
        str(request.rooms),
    ]
    if request.match_id:
        command.extend(["--match-id", request.match_id])
    if request.agents is not None:
        command.extend(["--agents", str(request.agents)])
    if request.refresh_data:
        command.append("--refresh-data")
    if request.include_camel:
        command.append("--include-camel")
    if request.include_x:
        command.append("--include-x")
    if request.include_telegram:
        command.append("--include-telegram")
    if request.include_polygun:
        command.append("--include-polygun")
    if request.include_deepseek_scout:
        command.append("--include-deepseek-scout")
    if market_override:
        command.extend(["--market-home-probability", str(market_override["home_anchor"])])
        command.extend(
            [
                "--market-side-probabilities-json",
                json.dumps(market_override["side_probabilities"], sort_keys=True),
            ]
        )
        command.extend(["--market-source", str(market_override["source"])])
    if request.debug:
        command.append("--debug")
    return command


def _emit_kg_stream_events(run_id: str, compact_dir: Path) -> None:
    graph_path = compact_dir / "world_graph.json"
    manifest_path = compact_dir / "kg_manifest.json"
    audit_path = compact_dir / "scouting_audit.json"
    if not graph_path.exists():
        return

    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    entities = graph.get("entities") or []
    relationships = graph.get("relationships") or []
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "world_graph_built",
            "graph_id": graph.get("graph_id"),
            "entity_count": len(entities),
            "relationship_count": len(relationships),
        },
    )
    for index, entity in enumerate(entities):
        _append_run_event(
            run_id,
            {
                "event_type": "kg_entity",
                "sequence": index,
                "entity": entity,
            },
        )
        time.sleep(0.003)
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "relationships_building",
            "graph_id": graph.get("graph_id"),
            "entity_count": len(entities),
            "relationship_count": len(relationships),
        },
    )
    for index, relationship in enumerate(relationships):
        _append_run_event(
            run_id,
            {
                "event_type": "kg_relationship",
                "sequence": index,
                "relationship": relationship,
            },
        )
        time.sleep(0.002)
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        _append_run_event(
            run_id,
            {
                "event_type": "kg_manifest",
                "manifest": manifest,
            },
        )
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        readiness = audit.get("kg_readiness") or audit.get("readiness") or {}
        _append_run_event(
            run_id,
            {
                "event_type": "scouting_audit",
                "kg_load_ready": readiness.get("kg_load_ready"),
                "scouting_complete": readiness.get("scouting_complete"),
                "backlog_count": readiness.get("scouting_backlog_count"),
                "audit": audit,
            },
        )
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "kg_stream_complete",
            "graph_id": graph.get("graph_id"),
            "entity_count": len(entities),
            "relationship_count": len(relationships),
        },
    )


def _pipe_process_output(run_id: str, stream_name: str, pipe, sink) -> None:
    if pipe is None:
        return
    try:
        for line in pipe:
            sink.write(line)
            sink.flush()
            message = line.rstrip("\r\n")
            if message:
                _append_run_event(
                    run_id,
                    {
                        "event_type": "run_log",
                        "stream": stream_name,
                        "message": message,
                    },
                )
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def _execute_run(run_id: str, command: list[str]) -> None:
    metadata = _read_metadata(run_id)
    metadata["status"] = "running"
    metadata["started_at"] = _utc_now()
    _write_metadata(run_id, metadata)
    if metadata.get("kind") in {"scouting", "colony"}:
        _append_run_event(
            run_id,
            {
                "event_type": "kg_stage",
                "stage": "colony_process_started" if metadata.get("kind") == "colony" else "scouting_process_started",
                "match": metadata.get("match"),
                "data_mode": metadata.get("data_mode"),
            },
        )

    run_dir = _run_dir(run_id)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'colony'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    env["PYTHONUNBUFFERED"] = "1"

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        output_threads = [
            threading.Thread(
                target=_pipe_process_output,
                args=(run_id, "stdout", process.stdout, stdout),
                daemon=True,
            ),
            threading.Thread(
                target=_pipe_process_output,
                args=(run_id, "stderr", process.stderr, stderr),
                daemon=True,
            ),
        ]
        for thread in output_threads:
            thread.start()
        returncode = process.wait()
        for thread in output_threads:
            thread.join()

    metadata = _read_metadata(run_id)
    metadata["completed_at"] = _utc_now()
    metadata["returncode"] = returncode
    metadata["status"] = "succeeded" if returncode == 0 else "failed"
    latest = _latest_compact_dir(run_id)
    if latest is not None:
        metadata["latest_compact_dir"] = str(latest)
        compact_events = latest / "events.compact.jsonl"
        root_events = run_dir / "events.jsonl"
        if compact_events.exists():
            compact_text = compact_events.read_text(encoding="utf-8")
            with RUN_EVENT_LOCK:
                if root_events.exists() and root_events.stat().st_size > 0:
                    with root_events.open("a", encoding="utf-8") as handle:
                        if not root_events.read_text(encoding="utf-8").endswith("\n"):
                            handle.write("\n")
                        handle.write(compact_text)
                else:
                    root_events.write_text(compact_text, encoding="utf-8")
        if metadata.get("kind") in {"scouting", "kg", "colony"} and returncode == 0:
            _emit_kg_stream_events(run_id, latest)
    _write_metadata(run_id, metadata)


def _forecast_contract_address(value: str | None = None) -> str:
    contract = (value or os.environ.get("FORECAST_MARKET_ADDRESS") or DEFAULT_FORECAST_CONTRACT).strip()
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}", contract):
        raise HTTPException(status_code=400, detail="Invalid forecast contract address")
    return contract


def _forecast_receipt_path(action: str) -> Path:
    target = RUNS_ROOT / "forecast_receipts" / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{action}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _wallet_store_env_payload(base_name: str) -> str:
    chunks: list[str] = []
    index = 0
    while True:
        part = os.environ.get(f"{base_name}_{index}")
        if part is None:
            part = os.environ.get(f"{base_name}_CHUNK_{index}")
        if part is None:
            break
        chunks.append(part)
        index += 1
    if chunks:
        return "".join(chunks)

    return os.environ.get(base_name) or ""


def _write_env_wallet_store(env_payload: str, *, env_name: str, target_dir: str) -> str:
    try:
        parsed = json.loads(env_payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"{env_name} is not valid JSON. If Railway rejected the full value, split it into {env_name}_0, {env_name}_1, ...",
        ) from exc
    target = RUNS_ROOT / target_dir / "agent-wallets.env.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(target)


def _forecast_wallet_store_argument(wallet_store: str) -> str:
    env_payload = _wallet_store_env_payload("COLONY_API_FORECAST_WALLETS_JSON")
    if env_payload:
        return _write_env_wallet_store(
            env_payload,
            env_name="COLONY_API_FORECAST_WALLETS_JSON",
            target_dir="forecast_wallets",
        )

    configured = os.environ.get("COLONY_API_FORECAST_WALLET_STORE") or wallet_store
    try:
        path = _safe_repo_path(configured)
    except HTTPException as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Forecast signing wallets are not configured. Set "
                "COLONY_API_FORECAST_WALLETS_JSON, COLONY_API_FORECAST_WALLETS_JSON_0...N, "
                "or COLONY_API_FORECAST_WALLET_STORE "
                "to a private-key wallet store before expecting Arc USDC stake/claim transactions."
            ),
        ) from exc
    return str(path.relative_to(REPO_ROOT))


def _x402_wallet_store_argument(wallet_store: str) -> str:
    env_payload = _wallet_store_env_payload("COLONY_API_X402_WALLETS_JSON") or _wallet_store_env_payload("COLONY_API_FORECAST_WALLETS_JSON")
    if env_payload:
        return _write_env_wallet_store(
            env_payload,
            env_name="COLONY_API_X402_WALLETS_JSON",
            target_dir="x402_wallets",
        )

    configured = os.environ.get("COLONY_API_X402_WALLET_STORE") or wallet_store
    return str(_safe_repo_path(configured).relative_to(REPO_ROOT))


def _x402_receipt_path(action: str, suffix: str) -> Path:
    target = RUNS_ROOT / "x402_receipts" / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{action}.{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _x402_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("ARC_RPC_URL", "https://rpc.testnet.arc.network")
    return env


def _free_local_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_x402_service(base_url: str, process: subprocess.Popen, timeout: float = 12.0) -> dict:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        if process.poll() is not None:
            raise HTTPException(status_code=500, detail=f"x402 service exited early with code {process.returncode}")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1.0) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise HTTPException(status_code=504, detail=f"x402 service did not become ready: {last_error}")


def _run_x402_pay(args: list[str], *, timeout: int = 120) -> dict:
    if not X402_PAY_CLI.exists():
        raise HTTPException(status_code=500, detail="arc/x402-agent-pay.mjs is missing")
    out_path = _x402_receipt_path("pay", "json")
    command = ["node", str(X402_PAY_CLI), *args, "--out", str(out_path)]
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=_x402_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Node.js is required for x402 operations") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="x402 payment timed out") from exc

    payload: dict = {
        "ok": completed.returncode == 0,
        "command": command,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "returncode": completed.returncode,
        "receipt_path": str(out_path),
    }
    if out_path.exists():
        try:
            payload["receipt"] = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["receipt"] = None
    if completed.returncode != 0:
        raise HTTPException(status_code=500, detail=payload)
    return payload


def _latest_jsonl(path: Path) -> dict | None:
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            latest = json.loads(line)
        except json.JSONDecodeError:
            continue
    return latest


def _run_forecast_cli(args: list[str], *, action: str, timeout: int = 120) -> dict:
    if not FORECAST_CLI.exists():
        raise HTTPException(status_code=500, detail="arc/forecast-market.mjs is missing")
    out_path = _forecast_receipt_path(action)
    command = ["node", str(FORECAST_CLI), *args, "--out", str(out_path)]
    env = os.environ.copy()
    env.setdefault("ARC_RPC_URL", "https://rpc.testnet.arc.network")
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Node.js is required for forecast contract operations") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"Forecast contract operation timed out: {action}") from exc

    payload: dict = {
        "ok": completed.returncode == 0,
        "action": action,
        "command": command,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "returncode": completed.returncode,
        "receipt_path": str(out_path),
    }
    if out_path.exists():
        try:
            payload["receipt"] = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload["receipt"] = None
    if completed.returncode != 0:
        raise HTTPException(status_code=500, detail=payload)
    return payload


def _run_forecast_cli_read(args: list[str], *, action: str, timeout: int = 60) -> dict:
    if not FORECAST_CLI.exists():
        raise HTTPException(status_code=500, detail="arc/forecast-market.mjs is missing")
    command = ["node", str(FORECAST_CLI), *args]
    env = os.environ.copy()
    env.setdefault("ARC_RPC_URL", "https://rpc.testnet.arc.network")
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Node.js is required for forecast contract operations") from exc
    if completed.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "action": action,
                "command": command,
                "stdout": completed.stdout.strip(),
                "stderr": completed.stderr.strip(),
                "returncode": completed.returncode,
            },
        )
    stdout = completed.stdout.strip()
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        data = {"output": stdout}
    return {
        "ok": True,
        "action": action,
        "command": command,
        "data": data,
    }


def _winner_to_outcome(winner: str, *, home_team: str, away_team: str) -> str:
    value = winner.strip().lower().replace("_", " ")
    home = home_team.strip().lower()
    away = away_team.strip().lower()
    if value in {"home", "home win", "home qualifies"} or value == home:
        return "home"
    if value in {"away", "away win", "away qualifies"} or value == away:
        return "away"
    if value in {"draw", "tie", "null", "nul"}:
        return "draw"
    raise HTTPException(status_code=400, detail=f"Winner must be home, away, draw, {home_team}, or {away_team}")


def _default_demo_stakes(market_type: str) -> list[ForecastStakeInstruction]:
    if market_type == "binary":
        return [
            ForecastStakeInstruction(agent="ant_0001", outcome="home", amount="0.001"),
            ForecastStakeInstruction(agent="ant_0002", outcome="away", amount="0.001"),
            ForecastStakeInstruction(agent="ant_0003", outcome="home", amount="0.002"),
        ]
    return [
        ForecastStakeInstruction(agent="ant_0001", outcome="home", amount="0.001"),
        ForecastStakeInstruction(agent="ant_0002", outcome="draw", amount="0.001"),
        ForecastStakeInstruction(agent="ant_0003", outcome="away", amount="0.001"),
    ]


def _winning_agents_for(stakes: list[ForecastStakeInstruction], outcome: str) -> list[str]:
    return [stake.agent for stake in stakes if stake.outcome == outcome]


def _wallet_agent_ids(wallet_store: str) -> set[str]:
    path = Path(wallet_store)
    if not path.is_absolute():
        path = REPO_ROOT / wallet_store
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    wallets = payload.get("wallets") or {}
    return {
        agent_id
        for agent_id, wallet in wallets.items()
        if wallet.get("private_key") or wallet.get("privateKey")
    }


def _format_usdc_amount(value: float) -> str:
    text = f"{max(value, 0.0):.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _stake_instructions_from_run(
    *,
    run_id: str,
    wallet_store: str,
    market_type: str,
    max_stakers: int,
    stake_scale: float,
) -> list[ForecastStakeInstruction]:
    signable_agents = _wallet_agent_ids(wallet_store)
    if not signable_agents:
        return []
    forecasts = [
        event
        for event in _read_events(run_id)
        if event.get("event_type") == "forecast" and event.get("agent_id") in signable_agents
    ]
    forecasts.sort(key=lambda item: (float(item.get("stake") or 0.0), abs(float(item.get("edge") or 0.0))), reverse=True)
    stakes: list[ForecastStakeInstruction] = []
    seen: set[str] = set()
    for forecast in forecasts:
        agent_id = str(forecast.get("agent_id") or "")
        if not agent_id or agent_id in seen:
            continue
        side = str(forecast.get("side") or "pass")
        if side not in {"home", "draw", "away"}:
            continue
        if market_type == "binary" and side == "draw":
            continue
        raw_stake = float(forecast.get("stake") or 0.0)
        amount = min(max(raw_stake * stake_scale, 0.0001), 0.002)
        stakes.append(ForecastStakeInstruction(agent=agent_id, outcome=side, amount=_format_usdc_amount(amount)))
        seen.add(agent_id)
        if len(stakes) >= max_stakers:
            break
    return stakes


def _validate_forecast_run_match(run_id: str, expected_match_id: str | None) -> dict:
    metadata = _read_metadata(run_id)
    if not expected_match_id:
        return metadata
    actual = str(metadata.get("match_id") or "").strip()
    if not actual:
        command = [str(part) for part in metadata.get("command") or []]
        for index, part in enumerate(command):
            if part == "--match-id" and index + 1 < len(command):
                actual = command[index + 1].strip()
                break
    expected = str(expected_match_id).strip()
    if actual != expected:
        raise HTTPException(
            status_code=409,
            detail=(
                "Forecast run mismatch: "
                f"run {run_id} is for match_id {actual or 'unknown'}, "
                f"but the selected market expects {expected}."
            ),
        )
    return metadata


def _wait_for_run_stakes(
    *,
    run_id: str,
    wallet_store: str,
    market_type: str,
    max_stakers: int,
    stake_scale: float,
    timeout_seconds: int,
) -> tuple[list[ForecastStakeInstruction], str]:
    deadline = time.time() + max(timeout_seconds, 0)
    last_status = "unknown"
    best_stakes: list[ForecastStakeInstruction] = []
    while True:
        stakes = _stake_instructions_from_run(
            run_id=run_id,
            wallet_store=wallet_store,
            market_type=market_type,
            max_stakers=max_stakers,
            stake_scale=stake_scale,
        )
        if len(stakes) > len(best_stakes):
            best_stakes = stakes
        if len(stakes) >= max_stakers:
            return stakes, f"run:{run_id}"
        try:
            metadata = _read_metadata(run_id)
            last_status = str(metadata.get("status") or "unknown")
        except HTTPException:
            raise
        except Exception:
            last_status = "unknown"
        if last_status in {"succeeded", "failed"} or time.time() >= deadline:
            if best_stakes:
                return best_stakes, f"run:{run_id}:{last_status}"
            return [], f"fallback:no-forecasts:{last_status}"
        time.sleep(2.0)


def _x402_services() -> list[dict]:
    return [
        {
            "service": "finding_private",
            "price_usdc": "0.00012",
            "resource": "private KG/scout signal",
            "money_flow": "buyer ant -> seller scout ant via Circle Gateway",
        },
        {
            "service": "finding_shared",
            "price_usdc": "0.00005",
            "resource": "shared KG/scout signal",
            "money_flow": "buyer ant -> seller scout ant via Circle Gateway",
        },
        {
            "service": "summary",
            "price_usdc": "0.0003",
            "resource": "room summary",
            "money_flow": "buyer ant -> seller representative ant via Circle Gateway",
        },
        {
            "service": "audit",
            "price_usdc": "0.0005",
            "resource": "grounded challenge/audit",
            "money_flow": "buyer ant -> seller auditor ant via Circle Gateway",
        },
    ]


def _api_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", normalized.lower()).strip("_")


def _match_pair_slug(home: str, away: str) -> str:
    return f"{_api_slug(home)}_vs_{_api_slug(away)}"


def _relative_repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _prematch_source_match_slug(source_path: Path, payload: dict, documents_payload: dict | None) -> str:
    match = (documents_payload or {}).get("match") or {}
    home = str(match.get("home_team") or "").strip()
    away = str(match.get("away_team") or "").strip()
    if home and away:
        return _match_pair_slug(home, away)

    for finding in payload.get("findings") or []:
        finding_id = str(finding.get("finding_id") or "")
        matched = re.search(r":([a-z0-9_]+_vs_[a-z0-9_]+)$", finding_id)
        if matched:
            return matched.group(1)

    parent_slug = _api_slug(source_path.parents[1].name)
    matched = re.search(r"([a-z0-9_]+_vs_[a-z0-9_]+)", parent_slug)
    return matched.group(1) if matched else parent_slug


def _prematch_claim_count(payload: dict) -> int:
    total = 0
    for finding in payload.get("findings") or []:
        total += len(finding.get("evidence_claims") or finding.get("claims") or [])
    return total


def _prematch_test_data_index() -> dict[str, dict]:
    if not PREMATCH_SCRAPE_ROOT.exists():
        return {}
    index: dict[str, dict] = {}
    for source_path in sorted(PREMATCH_SCRAPE_ROOT.glob("**/kg/prematch_kg_source.json")):
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scrape_dir = source_path.parents[1]
        documents_path = scrape_dir / "normalized" / "prematch_documents.json"
        documents_payload: dict | None = None
        if documents_path.exists():
            try:
                loaded = json.loads(documents_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    documents_payload = loaded
            except (OSError, json.JSONDecodeError):
                documents_payload = None
        summary = (documents_payload or {}).get("summary") or {}
        match = (documents_payload or {}).get("match") or {}
        claim_count = _prematch_claim_count(payload)
        usable_documents = int(summary.get("usable") or 0)
        candidate = {
            "kind": "prematch_scrape",
            "source": _relative_repo_path(source_path),
            "run_dir": _relative_repo_path(scrape_dir),
            "created_at_utc": (documents_payload or {}).get("created_at_utc"),
            "kickoff_utc": match.get("kickoff_utc"),
            "prediction_cutoff_utc": match.get("prediction_cutoff_utc"),
            "finding_count": len(payload.get("findings") or []),
            "evidence_claim_count": claim_count,
            "usable_document_count": usable_documents,
            "document_count": int(summary.get("total") or 0),
            "source_count": int(summary.get("source_count") or 0),
            "usable_by_source_type": summary.get("usable_by_source_type") or {},
            "usable_by_signal_type": summary.get("usable_by_signal_type") or {},
        }
        if claim_count <= 0 and usable_documents <= 0:
            continue
        slug = _prematch_source_match_slug(source_path, payload, documents_payload)
        previous = index.get(slug)
        if not previous:
            index[slug] = candidate
            continue
        previous["_artifact_count"] = int(previous.get("_artifact_count") or 1) + 1
        candidate["_artifact_count"] = previous["_artifact_count"]
        previous_score = (int(previous.get("usable_document_count") or 0), int(previous.get("evidence_claim_count") or 0))
        candidate_score = (usable_documents, claim_count)
        if candidate_score >= previous_score:
            index[slug] = candidate
    for value in index.values():
        value["artifact_count"] = int(value.pop("_artifact_count", 1))
    return index


def _forecast_games_from_kg(limit: int = 104, *, include_previous_test_data: bool = True) -> list[dict]:
    if not WORLD_CUP_KG.exists():
        return []
    graph = json.loads(WORLD_CUP_KG.read_text(encoding="utf-8"))
    previous_test_data = _prematch_test_data_index() if include_previous_test_data else {}
    games: list[dict] = []
    for entity in graph.get("entities") or []:
        if entity.get("entity_type") != "match":
            continue
        attrs = entity.get("attributes") or {}
        home = str(attrs.get("team1") or "").strip()
        away = str(attrs.get("team2") or "").strip()
        if not home or not away:
            continue
        score = attrs.get("score")
        if score not in (None, "", {}):
            continue
        group = str(attrs.get("group") or "").strip()
        market_type = "three_way" if group else "binary"
        test_data = previous_test_data.get(_match_pair_slug(home, away))
        games.append(
            {
                "match_id": entity.get("entity_id"),
                "market_key": entity.get("entity_id"),
                "name": entity.get("name") or f"{home} vs {away}",
                "home_team": home,
                "away_team": away,
                "market_type": market_type,
                "outcomes": ["home", "draw", "away"] if market_type == "three_way" else ["home", "away"],
                "date": attrs.get("date"),
                "time": attrs.get("time"),
                "stage": attrs.get("round"),
                "group": group,
                "venue": attrs.get("ground"),
                "score": score,
                "has_previous_test_data": bool(test_data),
                "previous_test_data": test_data,
            }
        )
    games.sort(key=lambda item: (str(item.get("date") or ""), str(item.get("time") or ""), str(item.get("name") or "")))
    return games[:limit]


def _cors_origins() -> list[str]:
    raw = os.environ.get("COLONY_API_CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="Colony Pipeline API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "colony-api",
        "runs_root": str(RUNS_ROOT),
        "run_demo_exists": RUN_DEMO.exists(),
        "kg_runner_exists": SCOUTING_MATRIX.exists(),
    }


@app.get("/config")
def get_config() -> dict:
    wallet_provider = os.environ.get("COLONY_API_DEFAULT_WALLET_PROVIDER") or os.environ.get(
        "COLONY_WALLET_PROVIDER",
        "dynamic",
    )
    return {
        "service": "colony-api",
        "endpoints": {
            "health": "/health",
            "config": "/config",
            "ants": "/ants",
            "world_cup_kg": "/kg/world-cup",
            "world_cup_kg_summary": "/kg/world-cup/summary",
            "start_kg_run": "/kg/run",
            "kg_modules": "/kg/modules",
            "start_scouting_run": "/scouting/run",
            "start_demo_run": "/runs/demo",
            "colony": "/colonies/{pubkey}",
            "create_colony": "/colonies",
            "colony_ants": "/colonies/{pubkey}/ants",
            "colony_ant_status": "/colonies/{pubkey}/ants/{agent_id}/status",
            "start_colony_run": "/colonies/{pubkey}/run",
            "list_runs": "/runs",
            "predictions": "/predictions",
            "run": "/runs/{run_id}",
            "run_prediction": "/runs/{run_id}/prediction",
            "events": "/runs/{run_id}/events",
            "stream": "/runs/{run_id}/stream",
            "agents": "/runs/{run_id}/agents",
            "rooms": "/runs/{run_id}/rooms",
            "run_kg": "/runs/{run_id}/kg",
            "run_kg_manifest": "/runs/{run_id}/kg/manifest",
            "run_scouting_audit": "/runs/{run_id}/scouting-audit",
            "forecast_config": "/forecast/config",
            "forecast_deploy": "/forecast/deploy",
            "forecast_games": "/forecast/games",
            "forecast_market": "/forecast/market",
            "forecast_demo_setup": "/forecast/demo-setup",
            "forecast_settle": "/forecast/settle",
            "forecast_totals": "/forecast/totals",
            "x402_config": "/x402/config",
            "x402_demo_payment": "/x402/demo-payment",
        },
        "defaults": {
            "agents": _env_int("COLONY_API_DEFAULT_AGENTS", 200),
            "rooms": _env_int("COLONY_API_DEFAULT_ROOMS", 12),
            "seed": _env_int("COLONY_API_DEFAULT_SEED", 205),
            "voice_mode": os.environ.get("COLONY_API_DEFAULT_VOICE_MODE", "llm"),
            "agent_wallets": _env_bool("COLONY_API_DEFAULT_AGENT_WALLETS", True),
            "wallet_provider": wallet_provider,
            "wallet_store": _default_wallet_store(),
        },
        "kg_run_defaults": {
            "mode": "fast",
            "modules": DEFAULT_KG_RUN_MODULES,
            "timeout": 120,
            "camel_agents": 4,
        },
        "limits": {
            "agents": {"min": 1, "max": 500},
            "rooms": {"min": 1, "max": 50},
            "voice_modes": ["template", "llm"],
            "wallet_providers": ["local", "dynamic"],
        },
        "identity_fields": [
            "agent_id",
            "name",
            "ens_name",
            "wallet_address",
            "world_status",
            "world_access_tier",
            "genome_id",
            "lineage_id",
        ],
    }


@app.get("/colonies/{pubkey}")
def get_user_colony(pubkey: str) -> dict:
    cleaned = _clean_pubkey(pubkey)
    settings = _supabase_settings_or_503()
    return _run_supabase_call(lambda: _colony_payload(settings, cleaned))


@app.post("/colonies")
def upsert_user_colony(request: UserColonyUpsertRequest) -> dict:
    settings = _supabase_settings_or_503()
    pubkey = _clean_pubkey(request.pubkey)
    config = _colony_config_from_request(request.config)
    row = {
        "pubkey": pubkey,
        "angle": request.angle,
        "dist": request.dist,
        "accent": int(request.accent),
        "name": request.name or _default_colony_name(pubkey),
        "config": config,
        "visibility": request.visibility,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
    }
    written = _run_supabase_call(lambda: upsert_colony(settings, row))
    payload = _run_supabase_call(lambda: _colony_payload(settings, pubkey))
    payload["written"] = written
    return payload


@app.delete("/colonies/{pubkey}")
def delete_user_colony(pubkey: str) -> dict:
    cleaned = _clean_pubkey(pubkey)
    settings = _supabase_settings_or_503()
    deleted_ants = _run_supabase_call(lambda: delete_colony_ants(settings, cleaned))
    deleted_colonies = _run_supabase_call(lambda: delete_colony(settings, cleaned))
    return {
        "pubkey": cleaned,
        "deleted": len(deleted_colonies),
        "deleted_ants": len(deleted_ants),
        "rows": deleted_colonies,
        "ants": deleted_ants,
    }


@app.get("/colonies/{pubkey}/ants")
def get_user_colony_ants(
    pubkey: str,
    status: Literal["alive", "dead", "inactive", "retired", "all"] = "all",
    limit: int = 200,
) -> dict:
    cleaned = _clean_pubkey(pubkey)
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    settings = _supabase_settings_or_503()
    colony = _run_supabase_call(lambda: fetch_colony(settings, cleaned, select="pubkey"))
    if colony is None:
        return {"pubkey": cleaned, "ants": [], "ant_summary": _colony_ant_summary([])}
    rows = _run_supabase_call(lambda: fetch_colony_ants(settings, cleaned, status=status, limit=limit))
    return {"pubkey": cleaned, "ants": rows, "ant_summary": _colony_ant_summary(rows)}


@app.post("/colonies/{pubkey}/ants")
def ensure_user_colony_ants(pubkey: str, request: UserColonyAntRosterRequest) -> dict:
    cleaned = _clean_pubkey(pubkey)
    settings = _supabase_settings_or_503()
    return _run_supabase_call(lambda: _ensure_colony_ant_roster(settings, cleaned, request))


@app.patch("/colonies/{pubkey}/ants/{agent_id}/status")
def set_user_colony_ant_status(pubkey: str, agent_id: str, request: UserColonyAntStatusRequest) -> dict:
    cleaned = _clean_pubkey(pubkey)
    cleaned_agent_id = str(agent_id or "").strip()
    if not cleaned_agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")
    settings = _supabase_settings_or_503()
    colony = _run_supabase_call(lambda: fetch_colony(settings, cleaned, select="pubkey"))
    if colony is None:
        raise HTTPException(status_code=404, detail=f"Colony not found: {cleaned}")
    rows = _run_supabase_call(
        lambda: update_ant_status(settings, pubkey=cleaned, agent_id=cleaned_agent_id, status=request.status)
    )
    return {"pubkey": cleaned, "agent_id": cleaned_agent_id, "updated": len(rows), "ants": rows}


@app.post("/colonies/{pubkey}/run", response_model=RunRecord, status_code=202)
def start_user_colony_run(pubkey: str, request: UserColonyRunRequest, background_tasks: BackgroundTasks) -> dict:
    cleaned = _clean_pubkey(pubkey)
    if not RUN_SUPABASE_COLONY.exists():
        raise HTTPException(status_code=500, detail="colony/tools/run_supabase_colony.py is missing")
    settings = _supabase_settings_or_503()
    colony = _run_supabase_call(lambda: fetch_colony(settings, cleaned, select="pubkey,name,config"))
    if colony is None:
        raise HTTPException(status_code=404, detail=f"Colony not found: {cleaned}")

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = f"colony_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    market_override = _latest_market_override_for_match(request.match, request.match_id)
    command = _build_colony_run_command(cleaned, request, run_dir, market_override=market_override)
    metadata = {
        "id": run_id,
        "kind": "colony",
        "status": "queued",
        "created_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "returncode": None,
        "command": command,
        "run_dir": str(run_dir),
        "events_path": str(run_dir / "events.jsonl"),
        "compact_runs_dir": str(run_dir / "compact"),
        "pubkey": cleaned,
        "colony_name": colony.get("name"),
        "match": request.match,
        "match_id": request.match_id,
        "data_mode": request.data_mode,
        "market_override": market_override,
    }
    _write_metadata(run_id, metadata)
    if market_override:
        _append_run_event(
            run_id,
            {
                "event_type": "kg_stage",
                "stage": "market_anchor_loaded",
                "match": request.match,
                "market_override": market_override,
            },
        )
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "colony_run_queued",
            "pubkey": cleaned,
            "match": request.match,
            "match_id": request.match_id,
            "data_mode": request.data_mode,
        },
    )
    background_tasks.add_task(_execute_run, run_id, command)
    return metadata


@app.get("/forecast/config")
def get_forecast_config() -> dict:
    contract = _forecast_contract_address()
    return {
        "network": {
            "name": "Arc Testnet",
            "chain_id": 5042002,
            "rpc_url": os.environ.get("ARC_RPC_URL", "https://rpc.testnet.arc.network"),
            "explorer": os.environ.get("ARC_EXPLORER", "https://explorer.testnet.arc.network"),
            "usdc": os.environ.get("ARC_USDC_ADDRESS", "0x3600000000000000000000000000000000000000"),
        },
        "contract": contract,
        "default_market": {
            "market_key": "worldcup:2026:brazil-morocco:frontend-demo",
            "market_type": "three_way",
            "home_team": "Brazil",
            "away_team": "Morocco",
            "fee_bps": 1000,
            "stakes": [_model_dump(stake) for stake in _default_demo_stakes("three_way")],
        },
        "endpoints": {
            "deploy": "/forecast/deploy",
            "games": "/forecast/games",
            "market": "/forecast/market",
            "demo_setup": "/forecast/demo-setup",
            "settle": "/forecast/settle",
            "totals": "/forecast/totals",
        },
    }


@app.get("/forecast/games")
def get_forecast_games(limit: int = 104, include_previous_test_data: bool = False) -> dict:
    games = _forecast_games_from_kg(
        limit=max(1, min(limit, 104)),
        include_previous_test_data=include_previous_test_data,
    )
    return {
        "count": len(games),
        "previous_test_count": sum(1 for game in games if game.get("has_previous_test_data")),
        "source": str(WORLD_CUP_KG.relative_to(REPO_ROOT)),
        "previous_test_source": _relative_repo_path(PREMATCH_SCRAPE_ROOT) if include_previous_test_data else None,
        "include_previous_test_data": include_previous_test_data,
        "games": games,
    }


@app.post("/forecast/deploy")
def deploy_forecast_contract(request: ForecastDeployRequest) -> dict:
    args = ["deploy"]
    if request.treasury:
        args.extend(["--treasury", request.treasury])
    result = _run_forecast_cli(args, action="deploy", timeout=180)
    receipt = result.get("receipt") or {}
    if receipt.get("contract_address"):
        result["contract"] = receipt["contract_address"]
    return result


@app.post("/forecast/market")
def create_forecast_market(request: ForecastCreateMarketRequest) -> dict:
    contract = _forecast_contract_address(request.contract)
    args = [
        "create-market",
        "--contract",
        contract,
        "--market-key",
        request.market_key,
        "--market-type",
        request.market_type,
        "--close-time",
        str(request.close_time),
        "--fee-bps",
        str(request.fee_bps),
        "--metadata-uri",
        request.metadata_uri,
    ]
    result = _run_forecast_cli(args, action="create-market", timeout=120)
    result["contract"] = contract
    return result


@app.post("/forecast/demo-setup")
def setup_forecast_demo(request: ForecastDemoSetupRequest) -> dict:
    contract = _forecast_contract_address(request.contract)
    wallet_store = _forecast_wallet_store_argument(request.wallet_store)
    stakes = request.stakes
    stake_source = "request"
    run_metadata: dict | None = None
    if stakes is None and request.run_id:
        run_metadata = _validate_forecast_run_match(request.run_id, request.expected_match_id)
        should_wait = request.wait_for_run_forecasts
        if should_wait is None:
            should_wait = _env_bool("COLONY_API_FORECAST_WAIT_FOR_RUN", True)
        if should_wait:
            stakes, stake_source = _wait_for_run_stakes(
                run_id=request.run_id,
                wallet_store=wallet_store,
                market_type=request.market_type,
                max_stakers=request.max_stakers,
                stake_scale=request.stake_scale,
                timeout_seconds=request.run_forecast_timeout_seconds,
            )
        else:
            stakes = _stake_instructions_from_run(
                run_id=request.run_id,
                wallet_store=wallet_store,
                market_type=request.market_type,
                max_stakers=request.max_stakers,
                stake_scale=request.stake_scale,
            )
            stake_source = f"run:{request.run_id}" if stakes else "fallback"
    if stakes is None or not stakes:
        if not request.allow_fallback_stakes:
            raise HTTPException(
                status_code=400,
                detail="No signable forecast stakes found for this run; refusing fallback demo stakes.",
            )
        stakes = _default_demo_stakes(request.market_type)
        stake_source = "fallback"
    steps: list[dict] = []

    market_request = ForecastCreateMarketRequest(
        contract=contract,
        market_key=request.market_key,
        market_type=request.market_type,
        close_time=request.close_time,
        fee_bps=request.fee_bps,
        metadata_uri=request.metadata_uri if request.metadata_uri != DEFAULT_FORECAST_MARKET_KEY else request.market_key,
    )
    steps.append(create_forecast_market(market_request))

    should_fund_stakers = request.fund_stakers
    if should_fund_stakers is None:
        should_fund_stakers = _env_bool("COLONY_API_FORECAST_PREFUND_STAKERS", True)
    if should_fund_stakers:
        steps.append(
            _fund_forecast_stakers(
                wallet_store,
                stakes,
                request.fund_amount,
                _env_bool("COLONY_API_FORECAST_BROADCAST_FUNDING", True),
            )
        )

    for stake in stakes:
        if request.market_type == "binary" and stake.outcome == "draw":
            raise HTTPException(status_code=400, detail="Binary markets do not accept draw stakes")
        args = [
            "stake",
            "--contract",
            contract,
            "--wallet-store",
            wallet_store,
            "--agent",
            stake.agent,
            "--market-key",
            request.market_key,
            "--outcome",
            stake.outcome,
            "--amount",
            stake.amount,
        ]
        steps.append(_run_forecast_cli(args, action=f"stake-{stake.agent}", timeout=120))

    totals = _run_forecast_cli_read(
        ["totals", "--contract", contract, "--market-key", request.market_key],
        action="totals",
    )
    return {
        "ok": True,
        "contract": contract,
        "market_key": request.market_key,
        "market_type": request.market_type,
        "stake_source": stake_source,
        "source_run": {
            "run_id": request.run_id,
            "match": (run_metadata or {}).get("match"),
            "match_id": (run_metadata or {}).get("match_id"),
            "status": (run_metadata or {}).get("status"),
        } if request.run_id else None,
        "stakes": [_model_dump(stake) for stake in stakes],
        "steps": steps,
        "totals": totals.get("data"),
    }


@app.post("/forecast/settle")
def settle_forecast_demo(request: ForecastSettleRequest) -> dict:
    contract = _forecast_contract_address(request.contract)
    wallet_store = _forecast_wallet_store_argument(request.wallet_store)
    outcome = _winner_to_outcome(request.winner, home_team=request.home_team, away_team=request.away_team)
    steps: list[dict] = []

    steps.append(
        _run_forecast_cli(
            [
                "settle",
                "--contract",
                contract,
                "--market-key",
                request.market_key,
                "--result",
                outcome,
            ],
            action="settle",
            timeout=120,
        )
    )

    winning_agents = request.winning_agents
    if winning_agents is None:
        winning_agents = _winning_agents_for(_default_demo_stakes("three_way"), outcome)
    if request.claim_winners:
        for agent_id in winning_agents:
            steps.append(
                _run_forecast_cli(
                    [
                        "claim",
                        "--contract",
                        contract,
                        "--wallet-store",
                        wallet_store,
                        "--agent",
                        agent_id,
                        "--market-key",
                        request.market_key,
                    ],
                    action=f"claim-{agent_id}",
                    timeout=120,
                )
            )

    if request.withdraw_treasury:
        steps.append(
            _run_forecast_cli(
                [
                    "withdraw-treasury",
                    "--contract",
                    contract,
                    "--market-key",
                    request.market_key,
                ],
                action="withdraw-treasury",
                timeout=120,
            )
        )

    totals = _run_forecast_cli_read(
        ["totals", "--contract", contract, "--market-key", request.market_key],
        action="totals",
    )
    return {
        "ok": True,
        "contract": contract,
        "market_key": request.market_key,
        "winner": request.winner,
        "result": outcome,
        "claimed_agents": winning_agents if request.claim_winners else [],
        "steps": steps,
        "totals": totals.get("data"),
    }


@app.get("/forecast/totals")
def get_forecast_totals(contract: str | None = None, market_key: str = "worldcup:2026:brazil-morocco:frontend-demo") -> dict:
    resolved_contract = _forecast_contract_address(contract)
    result = _run_forecast_cli_read(
        ["totals", "--contract", resolved_contract, "--market-key", market_key],
        action="totals",
    )
    return {
        "ok": True,
        "contract": resolved_contract,
        "market_key": market_key,
        "totals": result.get("data"),
    }


@app.get("/x402/config")
def get_x402_config() -> dict:
    return {
        "rail": "x402_circle_gateway",
        "network": {
            "name": "Arc Testnet",
            "chain_id": 5042002,
            "gateway_network": "eip155:5042002",
            "facilitator": os.environ.get("CIRCLE_GATEWAY_FACILITATOR_URL", "https://gateway-api-testnet.circle.com"),
        },
        "purpose": "Agent-to-agent services: KG/scout data, summaries, and grounded audits.",
        "settlement_contract_role": "Forecast staking and winner redistribution stay in ColonyForecastMarket; x402 is not the betting escrow.",
        "default_demo": {
            "buyer": "ant_0001",
            "seller": "ant_0002",
            "service": "finding_private",
            "resource_id": "kg:worldcup:brazil-morocco:private-scout-signal",
            "money_flow": "ant_0001 pays ant_0002 through Circle Gateway for a private KG/scout signal.",
        },
        "services": _x402_services(),
        "endpoints": {
            "config": "/x402/config",
            "demo_payment": "/x402/demo-payment",
        },
    }


@app.post("/x402/demo-payment")
def run_x402_demo_payment(request: X402DemoPaymentRequest) -> dict:
    if not X402_SERVICE_CLI.exists():
        raise HTTPException(status_code=500, detail="arc/x402-agent-service.mjs is missing")
    if not X402_PAY_CLI.exists():
        raise HTTPException(status_code=500, detail="arc/x402-agent-pay.mjs is missing")

    wallet_store = _x402_wallet_store_argument(request.wallet_store)
    port = _free_local_port()
    base_url = f"http://127.0.0.1:{port}"
    service_receipts = _x402_receipt_path("service", "jsonl")
    stdout_path = _x402_receipt_path("service-stdout", "log")
    stderr_path = _x402_receipt_path("service-stderr", "log")
    body = {
        "round_id": request.round_id,
        "resource_id": request.resource_id,
        "topic": request.topic,
        "room_id": "room_forecast_demo",
        "finding_id": request.resource_id,
        "payload": {
            "kind": "kg_signal",
            "match": request.topic,
            "signal": "private_scout_signal",
            "confidence": 0.72,
        },
    }
    service_process: subprocess.Popen | None = None

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        try:
            service_process = subprocess.Popen(
                [
                    "node",
                    str(X402_SERVICE_CLI),
                    "--wallet-store",
                    wallet_store,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--receipts",
                    str(service_receipts),
                ],
                cwd=str(REPO_ROOT),
                env=_x402_env(),
                stdout=stdout,
                stderr=stderr,
                text=True,
            )
            health = _wait_for_x402_service(base_url, service_process)
            pay_args = [
                "--wallet-store",
                wallet_store,
                "--buyer",
                request.buyer,
                "--seller",
                request.seller,
                "--service",
                request.service,
                "--base-url",
                base_url,
                "--body-json",
                json.dumps(body, separators=(",", ":")),
            ]
            if request.deposit:
                pay_args.extend(["--deposit", request.deposit])
            payment = _run_x402_pay(pay_args, timeout=180)
        finally:
            if service_process is not None and service_process.poll() is None:
                service_process.terminate()
                try:
                    service_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    service_process.kill()
                    service_process.wait(timeout=3)

    buyer_receipt = payment.get("receipt") or {}
    service_receipt = _latest_jsonl(service_receipts)
    receipt = service_receipt or ((buyer_receipt.get("response") or {}).get("receipt") if isinstance(buyer_receipt.get("response"), dict) else None)
    metadata = (receipt or {}).get("metadata") or {}
    transfer_id = buyer_receipt.get("transaction") or metadata.get("transaction") or metadata.get("gateway_transfer_id") or ""
    amount = buyer_receipt.get("paid_amount_usdc") or (receipt or {}).get("amount")
    product = ((buyer_receipt.get("response") or {}).get("product") if isinstance(buyer_receipt.get("response"), dict) else None) or {}

    return {
        "ok": True,
        "rail": "x402_circle_gateway",
        "network": "Arc Testnet",
        "buyer": {
            "agent_id": request.buyer,
            "wallet": buyer_receipt.get("buyer_wallet") or metadata.get("payer_wallet") or "",
        },
        "seller": {
            "agent_id": request.seller,
            "wallet": metadata.get("payee_wallet") or "",
        },
        "service": request.service,
        "resource_id": request.resource_id,
        "amount_usdc": amount,
        "money_flow": f"{request.buyer} -> {request.seller} via Circle Gateway",
        "gateway_transfer_id": transfer_id,
        "receipt": receipt,
        "product": product,
        "health": health,
        "artifacts": {
            "buyer_receipt": payment.get("receipt_path"),
            "service_receipts": str(service_receipts),
            "service_stdout": str(stdout_path),
            "service_stderr": str(stderr_path),
        },
    }


@app.get("/ants")
def get_ants() -> dict:
    ants = _read_public_ants()
    return {
        "count": len(ants),
        "source": _default_wallet_store(),
        "children_source": str(CHILD_ANTS_PATH),
        "agents": ants,
    }


@app.get("/ants/children")
def get_child_ants() -> dict:
    state = _read_ant_state()
    children = [_apply_ant_state(child, state) for child in _read_child_ants()]
    return {
        "count": len(children),
        "source": str(CHILD_ANTS_PATH),
        "exists": CHILD_ANTS_PATH.exists(),
        "agents": children,
    }


@app.get("/ants/{agent_id}.json")
def get_ant_profile(agent_id: str) -> dict:
    ant = _find_parent_ant(agent_id)
    return {
        "schema": "ensip-26",
        "kind": "colony_ant",
        "profile": ant,
    }


@app.get("/ants/{agent_id}/avatar.svg")
def get_ant_avatar(agent_id: str) -> Response:
    return Response(
        content=_avatar_svg(agent_id),
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=86400",
        },
    )


@app.post("/ants/reproduce")
def reproduce_ant(request: AntReproduceRequest) -> dict:
    parent = _find_parent_ant(request.parent_agent_id)
    children = _read_child_ants()
    child_agent_id = _next_child_agent_id(children)
    parent_key = "|".join(str(parent.get(key) or "") for key in ("agent_id", "ens_name", "wallet_address", "genome_hash"))
    parent_genome = _personality_genome(parent_key)
    rng_seed = hashlib.sha256(f"{parent_key}|{child_agent_id}|{time.time_ns()}".encode("utf-8")).hexdigest()
    child_genome = mutate_genome(parent_genome, random.Random(rng_seed), mutation_rate=request.mutation_rate)
    child_wallet, wallet_store = _create_child_wallet(child_agent_id, request)

    parent_generation = int(parent.get("generation") or 0)
    parent_ens_name = str(parent.get("ens_name") or _root_ens_name(str(parent.get("agent_id") or request.parent_agent_id)))
    lineage_ens_name = str(parent.get("lineage_ens_name") or parent.get("lineage") or parent_ens_name)
    child = {
        "agent_id": child_agent_id,
        "name": child_agent_id.replace("_", "-"),
        "ens_name": _child_ens_name(child_agent_id, child_genome.stable_id()),
        "wallet_address": str(child_wallet.get("wallet_address") or ""),
        "wallet_provider": child_wallet.get("wallet_provider") or request.wallet_provider or "",
        "chains": child_wallet.get("chains") or {},
        "parent_agent_id": parent.get("agent_id") or request.parent_agent_id,
        "parent_ens_name": parent_ens_name,
        "lineage_ens_name": lineage_ens_name,
        "generation": parent_generation + 1,
        "bankroll": request.initial_bankroll,
        "accuracy": parent.get("accuracy", 0),
        "status": "alive",
        "genome_id": child_genome.stable_id(),
        "genome_hash": child_genome.public_hash(),
        "parent_genome_id": parent.get("genome_id") or "",
        "personality": child_genome.to_dict(),
        "created_at": _utc_now(),
    }
    child.update(_avatar_record_fields(child))
    child["ens_text_records"] = _child_identity_text(child)
    child["funding"] = _fund_child_wallet(child_agent_id, wallet_store, request)
    child["ens_publication"] = _publish_child_ens(child, request)
    children.append(child)
    _write_child_ants(children)
    return {
        "status": "created",
        "parent": parent,
        "child": child,
        "wallet_store": wallet_store,
        "ens_parent": _ens_parent(),
        "source": str(CHILD_ANTS_PATH),
    }


@app.post("/ants/{agent_id}/avatar/random")
def randomize_ant_avatar(agent_id: str, request: AntAvatarRequest | None = None) -> dict:
    ant = _find_parent_ant(agent_id)
    requested = (request.variant if request else None) or ""
    variant = requested.strip() if requested else random.choice(AVATAR_VARIANTS)
    if variant not in AVATAR_VARIANTS:
        raise HTTPException(status_code=400, detail=f"Unknown avatar variant: {variant}")
    _avatar_asset_path(variant)
    agent_id = str(ant.get("agent_id") or agent_id)
    state = _read_ant_state()
    agent_state = dict(state.get(agent_id) or {})
    agent_state.update(
        {
            "avatar": _avatar_url(agent_id),
            "avatar_trait": variant,
            "avatar_updated_at": _utc_now(),
        }
    )
    state[agent_id] = agent_state
    _write_ant_state(state)
    children = _read_child_ants()
    changed = False
    for child in children:
        if str(child.get("agent_id") or "") == agent_id:
            child.update(agent_state)
            if isinstance(child.get("ens_text_records"), dict):
                child["ens_text_records"]["avatar"] = agent_state["avatar"]
                child["ens_text_records"]["com.colony.avatar"] = agent_state["avatar"]
                child["ens_text_records"]["com.colony.avatar_trait"] = variant
            changed = True
            break
    if changed:
        _write_child_ants(children)
    ant.update(agent_state)
    return {
        "status": "avatar_updated",
        "ant": ant,
        "variant": variant,
        "source": str(ANT_STATE_PATH),
    }


@app.post("/ants/{agent_id}/kill")
def kill_ant(agent_id: str, request: AntKillRequest | None = None) -> dict:
    ant = _find_parent_ant(agent_id)
    state = _read_ant_state()
    reason = (request.reason if request else "manual").strip() or "manual"
    resolved_agent_id = str(ant.get("agent_id") or agent_id)
    killed_at = _utc_now()
    agent_state = dict(state.get(str(ant.get("agent_id") or agent_id)) or {})
    agent_state.update(
        {
            "status": "dead",
            "killed_at": killed_at,
            "kill_reason": reason,
        }
    )
    state[resolved_agent_id] = agent_state
    _write_ant_state(state)
    ant.update(agent_state)
    ens_text_records = _ant_identity_text(ant, active=False, status="dead", killed_at=killed_at, kill_reason=reason)
    ant["ens_text_records"] = ens_text_records
    children = _read_child_ants()
    changed = False
    for child in children:
        if str(child.get("agent_id") or "") == resolved_agent_id:
            child.update(agent_state)
            child["ens_text_records"] = ens_text_records
            changed = True
            break
    if changed:
        _write_child_ants(children)
    ens_publication = _publish_ant_ens_update(
        ant,
        action="kill",
        text_records=ens_text_records,
        publish=request.publish_ens if request else True,
        broadcast=request.broadcast_ens if request else None,
    )
    return {
        "status": "killed",
        "ant": ant,
        "ens_publication": ens_publication,
        "source": str(ANT_STATE_PATH),
    }


@app.get("/kg/world-cup")
def get_world_cup_kg() -> dict:
    path = _safe_repo_path(str(WORLD_CUP_KG.relative_to(REPO_ROOT)))
    graph = json.loads(path.read_text(encoding="utf-8"))
    graph["entity_count"] = len(graph.get("entities") or [])
    graph["relationship_count"] = len(graph.get("relationships") or [])
    return graph


@app.get("/kg/world-cup/summary", response_class=PlainTextResponse)
def get_world_cup_kg_summary() -> PlainTextResponse:
    path = _safe_repo_path(str(WORLD_CUP_KG_SUMMARY.relative_to(REPO_ROOT)))
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/markdown")


@app.get("/kg/modules")
def get_kg_modules() -> dict:
    modules = _kg_module_records()
    configured_defaults = [
        module["id"]
        for module in modules
        if module["default_enabled"] and module["configured"]
    ]
    return {
        "defaults": {
            "mode": "fast",
            "modules": configured_defaults or ["fixture"],
            "timeout": 120,
            "camel_agents": 4,
        },
        "modules": modules,
    }


@app.post("/kg/run", response_model=RunRecord, status_code=202)
def start_kg_run(request: KGRunRequest, background_tasks: BackgroundTasks) -> dict:
    if not SCOUTING_MATRIX.exists():
        raise HTTPException(status_code=500, detail="colony/scouting_matrix.py is missing")
    if not WORLD_CUP_KG.exists():
        raise HTTPException(status_code=500, detail="World Cup KG is missing")
    if not SCOUTING_SOURCE_CATALOG.exists():
        raise HTTPException(status_code=500, detail="scouting source catalog is missing")
    catalog_modules = (_load_scouting_source_catalog().get("modules") or {})
    unknown_modules = [module for module in request.modules if module not in catalog_modules]
    if unknown_modules:
        raise HTTPException(status_code=400, detail=f"Unknown KG module(s): {', '.join(unknown_modules)}")
    configured_env = _configured_env_names()
    not_configured = [
        module
        for module in request.modules
        if not _module_setup_state(module, catalog_modules, configured_env)["configured"]
    ]
    if not_configured:
        raise HTTPException(status_code=400, detail=f"KG module(s) require setup: {', '.join(not_configured)}")

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = f"kg_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    command = _build_kg_command(request, run_dir)
    metadata = {
        "id": run_id,
        "kind": "kg",
        "status": "queued",
        "created_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "returncode": None,
        "command": command,
        "run_dir": str(run_dir),
        "events_path": str(run_dir / "events.jsonl"),
        "compact_runs_dir": str(run_dir / "compact"),
        "match": request.match,
        "match_id": request.match_id,
        "kg_mode": request.mode,
        "modules": request.modules,
        "timeout": request.timeout,
        "camel_agents": request.camel_agents,
    }
    _write_metadata(run_id, metadata)
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "kg_queued",
            "match": request.match,
            "match_id": request.match_id,
            "mode": request.mode,
            "modules": request.modules,
        },
    )
    background_tasks.add_task(_execute_run, run_id, command)
    return metadata


@app.post("/scouting/run", response_model=RunRecord, status_code=202)
def start_scouting_run(request: ScoutingRunRequest, background_tasks: BackgroundTasks) -> dict:
    if not RUN_MATCH.exists():
        raise HTTPException(status_code=500, detail="colony/run_match.py is missing")
    if request.data_mode != "openfootball" and not WORLD_CUP_KG.exists():
        raise HTTPException(status_code=500, detail="World Cup KG is missing")

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = f"scout_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    command = _build_scouting_command(request, run_dir)
    metadata = {
        "id": run_id,
        "kind": "scouting",
        "status": "queued",
        "created_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "returncode": None,
        "command": command,
        "run_dir": str(run_dir),
        "events_path": str(run_dir / "events.jsonl"),
        "compact_runs_dir": str(run_dir / "compact"),
        "match": request.match,
        "match_id": request.match_id,
        "data_mode": request.data_mode,
    }
    _write_metadata(run_id, metadata)
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "scouting_queued",
            "match": request.match,
            "match_id": request.match_id,
            "data_mode": request.data_mode,
            "include_deepseek_scout": request.include_deepseek_scout,
        },
    )
    background_tasks.add_task(_execute_run, run_id, command)
    return metadata


@app.post("/runs/demo", response_model=RunRecord, status_code=202)
def start_demo_run(request: DemoRunRequest, background_tasks: BackgroundTasks) -> dict:
    if not RUN_DEMO.exists():
        raise HTTPException(status_code=500, detail="colony/run_demo.py is missing")

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    command = _build_command(request, run_dir)
    metadata = {
        "id": run_id,
        "status": "queued",
        "created_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "returncode": None,
        "command": command,
        "run_dir": str(run_dir),
        "events_path": str(run_dir / "events.jsonl"),
        "compact_runs_dir": str(run_dir / "compact"),
        "match": request.match,
        "match_id": request.match_id,
        "home_team": request.home_team,
        "away_team": request.away_team,
    }
    _write_metadata(run_id, metadata)
    background_tasks.add_task(_execute_run, run_id, command)
    return metadata


@app.get("/runs")
def list_runs() -> dict:
    if not RUNS_ROOT.exists():
        return {"runs": []}
    runs = []
    for path in RUNS_ROOT.iterdir():
        if not path.is_dir():
            continue
        metadata_path = path / "metadata.json"
        if metadata_path.exists():
            runs.append(json.loads(metadata_path.read_text(encoding="utf-8")))
    runs.sort(key=_run_created_sort_key, reverse=True)
    return {"runs": runs}


@app.get("/predictions")
def list_predictions(limit: int = 50, include_incomplete: bool = True) -> dict:
    if not RUNS_ROOT.exists():
        return {"count": 0, "predictions": []}
    metadata_rows = []
    for path in RUNS_ROOT.iterdir():
        if not path.is_dir():
            continue
        metadata_path = path / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata_rows.append(json.loads(metadata_path.read_text(encoding="utf-8")))
    metadata_rows.sort(key=_run_created_sort_key, reverse=True)

    records = []
    for metadata in metadata_rows:
        record = _prediction_record(metadata, include_incomplete=include_incomplete)
        if record is not None:
            records.append(record)
        if limit > 0 and len(records) >= limit:
            break
    return {
        "count": len(records),
        "runs_root": str(RUNS_ROOT),
        "predictions": records,
    }


@app.get("/recent_communications")
def recent_communications(limit: int = 60) -> dict:
    """
    Return the most recent ant-to-ant communication events (debate_claim,
    social_action, forecast) from the latest run's events.jsonl. The
    frontend polls this endpoint to drive its arc visualization and log
    terminal — no run_id required.
    """
    if not RUNS_ROOT.exists():
        return {"run_id": None, "events": []}
    latest_run = None
    for path in sorted(RUNS_ROOT.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        if (path / "events.jsonl").exists():
            latest_run = path
            break
    if latest_run is None:
        return {"run_id": None, "events": []}
    events_path = latest_run / "events.jsonl"
    interesting = {"debate_claim", "social_action", "forecast"}
    out: list[dict] = []
    try:
        with events_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if ev.get("event_type") in interesting:
                    out.append(ev)
    except OSError:
        return {"run_id": latest_run.name, "events": []}
    # Keep only the trailing N — the JSONL is append-only so the tail is
    # the most recent.
    if limit > 0 and len(out) > limit:
        out = out[-limit:]
    return {"run_id": latest_run.name, "events": out}


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    latest = _latest_compact_dir(run_id)
    metadata["artifacts"] = {
        "events": f"/runs/{run_id}/events",
        "stream": f"/runs/{run_id}/stream",
        "stdout": f"/runs/{run_id}/artifacts/stdout.log",
        "stderr": f"/runs/{run_id}/artifacts/stderr.log",
    }
    if latest is not None:
        relative = latest.relative_to(_run_dir(run_id))
        metadata["artifacts"].update(
            {
                "summary": f"/runs/{run_id}/artifacts/{relative}/summary.md",
                "decision": f"/runs/{run_id}/artifacts/{relative}/decision.compact.json",
                "social_feed": f"/runs/{run_id}/artifacts/{relative}/social_feed.md",
                "kg": f"/runs/{run_id}/kg",
                "kg_manifest": f"/runs/{run_id}/kg/manifest",
                "scouting_audit": f"/runs/{run_id}/scouting-audit",
            }
        )
    return metadata


@app.get("/runs/{run_id}/prediction")
def get_run_prediction(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    record = _prediction_record(metadata, include_incomplete=True, include_agents=True)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Prediction not found for run: {run_id}")
    return record


@app.get("/runs/{run_id}/events", response_class=PlainTextResponse)
def get_events(run_id: str) -> PlainTextResponse:
    path = _safe_artifact_path(run_id, "events.jsonl")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="application/x-ndjson")


@app.get("/runs/{run_id}/agents")
def get_run_agents(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    events = _read_events(run_id)
    agents = [event for event in events if event.get("event_type") == "agent_record"]
    forecasts_by_agent = {
        event.get("agent_id"): event
        for event in events
        if event.get("event_type") == "forecast" and event.get("agent_id")
    }
    for agent in agents:
        forecast = forecasts_by_agent.get(agent.get("agent_id"))
        if forecast:
            agent["latest_forecast"] = {
                "side": forecast.get("side"),
                "stake": forecast.get("stake"),
                "home_probability": forecast.get("home_probability"),
                "edge": forecast.get("edge"),
                "prediction": forecast.get("prediction"),
            }
    return {
        "run_id": run_id,
        "status": metadata["status"],
        "count": len(agents),
        "agents": agents,
    }


@app.get("/runs/{run_id}/rooms")
def get_run_rooms(run_id: str) -> dict:
    metadata = _read_metadata(run_id)
    events = _read_events(run_id)
    rooms = [event for event in events if event.get("event_type") == "debate_room"]
    return {
        "run_id": run_id,
        "status": metadata["status"],
        "count": len(rooms),
        "rooms": rooms,
    }


@app.get("/runs/{run_id}/kg")
def get_run_kg(run_id: str) -> dict:
    _read_metadata(run_id)
    path = _latest_compact_artifact(run_id, "world_graph.json")
    graph = json.loads(path.read_text(encoding="utf-8"))
    graph["entity_count"] = len(graph.get("entities") or [])
    graph["relationship_count"] = len(graph.get("relationships") or [])
    return graph


@app.get("/runs/{run_id}/kg/manifest")
def get_run_kg_manifest(run_id: str) -> dict:
    _read_metadata(run_id)
    path = _latest_compact_artifact(run_id, "kg_manifest.json")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/runs/{run_id}/scouting-audit")
def get_run_scouting_audit(run_id: str) -> dict:
    _read_metadata(run_id)
    path = _latest_compact_artifact(run_id, "scouting_audit.json")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    _read_metadata(run_id)

    async def event_source():
        offset = 0
        last_status_payload = ""
        while True:
            metadata = _read_metadata(run_id)
            status_payload = json.dumps(metadata, sort_keys=True)
            if status_payload != last_status_payload:
                last_status_payload = status_payload
                yield f"event: status\ndata: {status_payload}\n\n"

            events_path = _run_dir(run_id) / "events.jsonl"
            if events_path.exists():
                with events_path.open("r", encoding="utf-8") as handle:
                    handle.seek(offset)
                    for line in handle:
                        line = line.strip()
                        if line:
                            yield f"event: colony_event\ndata: {line}\n\n"
                    offset = handle.tell()

            if metadata["status"] in {"succeeded", "failed"}:
                yield f"event: done\ndata: {status_payload}\n\n"
                break

            yield "event: heartbeat\ndata: {}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@app.get("/runs/{run_id}/artifacts/{relative_path:path}")
def get_artifact(run_id: str, relative_path: str) -> FileResponse:
    path = _safe_artifact_path(run_id, relative_path)
    return FileResponse(path)
