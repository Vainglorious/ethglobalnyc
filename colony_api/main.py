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
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = REPO_ROOT / "colony" / "runs" / "api"
RUNS_ROOT = Path(os.environ.get("COLONY_API_RUNS_DIR", str(DEFAULT_RUNS_ROOT))).resolve()
RUN_DEMO = REPO_ROOT / "colony" / "run_demo.py"
RUN_MATCH = REPO_ROOT / "colony" / "run_match.py"
WORLD_CUP_KG = REPO_ROOT / "colony" / "data" / "world_cup_kg.json"
WORLD_CUP_KG_SUMMARY = REPO_ROOT / "colony" / "data" / "world_cup_kg.summary.md"
DEFAULT_PUBLIC_WALLET_STORE = "colony/data/agent-wallets.dynamic.200.public.json"
DEFAULT_LOCAL_WALLET_STORE = "colony/secrets/agent-wallets.local.json"
FORECAST_CLI = REPO_ROOT / "arc" / "forecast-market.mjs"
X402_SERVICE_CLI = REPO_ROOT / "arc" / "x402-agent-service.mjs"
X402_PAY_CLI = REPO_ROOT / "arc" / "x402-agent-pay.mjs"
DEFAULT_FORECAST_CONTRACT = "0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87"

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
    voice_mode: Literal["template", "llm"] = "llm"
    debug: bool = False
    agent_wallets: bool = True
    wallet_provider: Literal["local", "dynamic"] | None = "dynamic"
    wallet_store: str | None = DEFAULT_PUBLIC_WALLET_STORE


class ScoutingRunRequest(BaseModel):
    match: str = "Brazil vs Morocco"
    match_id: str | None = None
    data_mode: Literal["synthetic", "public"] = "public"
    refresh_data: bool = False
    include_deepseek_scout: bool = True
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
    market_key: str = "worldcup:2026:brazil-morocco:frontend-demo"
    market_type: Literal["three_way", "binary"] = "three_way"
    close_time: int = Field(default=0, ge=0)
    fee_bps: int = Field(default=1000, ge=0, le=2000)
    metadata_uri: str = "worldcup:2026:brazil-morocco:frontend-demo"


class ForecastStakeInstruction(BaseModel):
    agent: str
    outcome: Literal["home", "draw", "away"]
    amount: str = "0.001"


class ForecastDemoSetupRequest(ForecastCreateMarketRequest):
    wallet_store: str = DEFAULT_LOCAL_WALLET_STORE
    stakes: list[ForecastStakeInstruction] | None = None
    run_id: str | None = None
    max_stakers: int = Field(default=3, ge=1, le=25)
    stake_scale: float = Field(default=0.0001, gt=0.0, le=1.0)


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
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


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


def _read_public_ants() -> list[dict]:
    store_path = _safe_repo_path(_default_wallet_store())
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    wallets = payload.get("wallets") or {}
    ants = []
    for agent_id, wallet in sorted(wallets.items()):
        address = str(wallet.get("address") or "")
        ants.append(
            {
                "agent_id": agent_id,
                "name": agent_id.replace("_", "-"),
                "ens_name": _root_ens_name(agent_id),
                "wallet_address": address,
                "wallet_provider": str(wallet.get("provider") or payload.get("provider") or ""),
                "chains": wallet.get("chains") or {},
            }
        )
    return ants


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


def _execute_run(run_id: str, command: list[str]) -> None:
    metadata = _read_metadata(run_id)
    metadata["status"] = "running"
    metadata["started_at"] = _utc_now()
    _write_metadata(run_id, metadata)
    if metadata.get("kind") == "scouting":
        _append_run_event(
            run_id,
            {
                "event_type": "kg_stage",
                "stage": "scouting_process_started",
                "match": metadata.get("match"),
                "data_mode": metadata.get("data_mode"),
            },
        )

    run_dir = _run_dir(run_id)
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{REPO_ROOT / 'colony'}{os.pathsep}{env.get('PYTHONPATH', '')}"

    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=stdout,
            stderr=stderr,
            check=False,
        )

    metadata = _read_metadata(run_id)
    metadata["completed_at"] = _utc_now()
    metadata["returncode"] = completed.returncode
    metadata["status"] = "succeeded" if completed.returncode == 0 else "failed"
    latest = _latest_compact_dir(run_id)
    if latest is not None:
        metadata["latest_compact_dir"] = str(latest)
        compact_events = latest / "events.compact.jsonl"
        root_events = run_dir / "events.jsonl"
        if compact_events.exists() and not root_events.exists():
            root_events.write_text(compact_events.read_text(encoding="utf-8"), encoding="utf-8")
        if metadata.get("kind") == "scouting" and completed.returncode == 0:
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


def _forecast_wallet_store_argument(wallet_store: str) -> str:
    env_payload = os.environ.get("COLONY_API_FORECAST_WALLETS_JSON")
    if env_payload:
        try:
            parsed = json.loads(env_payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="COLONY_API_FORECAST_WALLETS_JSON is not valid JSON") from exc
        target = RUNS_ROOT / "forecast_wallets" / "agent-wallets.env.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return str(target)

    configured = os.environ.get("COLONY_API_FORECAST_WALLET_STORE") or wallet_store
    return str(_safe_repo_path(configured).relative_to(REPO_ROOT))


def _x402_wallet_store_argument(wallet_store: str) -> str:
    env_payload = os.environ.get("COLONY_API_X402_WALLETS_JSON") or os.environ.get("COLONY_API_FORECAST_WALLETS_JSON")
    if env_payload:
        try:
            parsed = json.loads(env_payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail="COLONY_API_X402_WALLETS_JSON is not valid JSON") from exc
        target = RUNS_ROOT / "x402_wallets" / "agent-wallets.env.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(parsed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return str(target)

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


def _forecast_games_from_kg(limit: int = 104) -> list[dict]:
    if not WORLD_CUP_KG.exists():
        return []
    graph = json.loads(WORLD_CUP_KG.read_text(encoding="utf-8"))
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
            "start_scouting_run": "/scouting/run",
            "start_demo_run": "/runs/demo",
            "list_runs": "/runs",
            "run": "/runs/{run_id}",
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
def get_forecast_games(limit: int = 104) -> dict:
    games = _forecast_games_from_kg(limit=max(1, min(limit, 104)))
    return {
        "count": len(games),
        "source": str(WORLD_CUP_KG.relative_to(REPO_ROOT)),
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
    if stakes is None and request.run_id:
        stakes = _stake_instructions_from_run(
            run_id=request.run_id,
            wallet_store=wallet_store,
            market_type=request.market_type,
            max_stakers=request.max_stakers,
            stake_scale=request.stake_scale,
        )
        stake_source = f"run:{request.run_id}" if stakes else "fallback"
    if stakes is None or not stakes:
        stakes = _default_demo_stakes(request.market_type)
        stake_source = "fallback"
    steps: list[dict] = []

    market_request = ForecastCreateMarketRequest(
        contract=contract,
        market_key=request.market_key,
        market_type=request.market_type,
        close_time=request.close_time,
        fee_bps=request.fee_bps,
        metadata_uri=request.metadata_uri,
    )
    steps.append(create_forecast_market(market_request))

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
        "agents": ants,
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


@app.post("/scouting/run", response_model=RunRecord, status_code=202)
def start_scouting_run(request: ScoutingRunRequest, background_tasks: BackgroundTasks) -> dict:
    if not RUN_MATCH.exists():
        raise HTTPException(status_code=500, detail="colony/run_match.py is missing")
    if not WORLD_CUP_KG.exists():
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
        "data_mode": request.data_mode,
    }
    _write_metadata(run_id, metadata)
    _append_run_event(
        run_id,
        {
            "event_type": "kg_stage",
            "stage": "scouting_queued",
            "match": request.match,
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
    }
    _write_metadata(run_id, metadata)
    background_tasks.add_task(_execute_run, run_id, command)
    return metadata


@app.get("/runs")
def list_runs() -> dict:
    if not RUNS_ROOT.exists():
        return {"runs": []}
    runs = []
    for path in sorted(RUNS_ROOT.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        metadata_path = path / "metadata.json"
        if metadata_path.exists():
            runs.append(json.loads(metadata_path.read_text(encoding="utf-8")))
    return {"runs": runs}


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
