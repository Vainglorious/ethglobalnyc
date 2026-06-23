#!/usr/bin/env python3
"""Run one scheduled prematch snapshot collection tick.

This script is designed for cron-style execution. Run it every few minutes; it
selects matches whose collection target, by default kickoff minus 30 minutes,
falls inside the current tick window. For each due match it runs the existing
prematch scrape/KG pipeline and optionally imports the snapshot into Supabase.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any


COLONY_DIR = Path(__file__).resolve().parent
REPO_ROOT = COLONY_DIR.parent

if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

from collect_upcoming_prematch_batch import collect_match, match_summary  # noqa: E402
from colony_harness.supabase_client import (  # noqa: E402
    SupabaseRequestError,
    load_supabase_service_settings,
    load_supabase_settings,
    request_json,
)
from scouting_matrix import _iso_utc, _match_kickoff_utc  # noqa: E402


DEFAULT_KG = COLONY_DIR / "data" / "world_cup_kg.json"
DEFAULT_ENV = COLONY_DIR / ".env"
DEFAULT_OUT_ROOT = COLONY_DIR / "runs" / "prematch_scrape" / "automated"
IMPORT_SCRIPT = COLONY_DIR / "tools" / "import_prematch_snapshot_supabase.py"
TERMINAL_IMPORTED_STATUSES = {"imported", "supabase_existing"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg", type=Path, default=DEFAULT_KG)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--competition", default="worldcup_2026")
    parser.add_argument("--lead-minutes", type=float, default=30.0)
    parser.add_argument("--lookahead-minutes", type=float, default=0.0)
    parser.add_argument("--grace-minutes", type=float, default=15.0)
    parser.add_argument("--stale-lock-minutes", type=float, default=90.0)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--window-days", type=int, default=21)
    parser.add_argument("--max-records", type=int, default=30)
    parser.add_argument("--x-max-queries", type=int, default=11)
    parser.add_argument("--polymarket-timeout", type=int, default=30)
    parser.add_argument("--polymarket-raw-clob-limit", type=int, default=12)
    parser.add_argument("--import-timeout", type=int, default=180)
    parser.add_argument("--skip-google-news", action="store_true")
    parser.add_argument("--skip-gdelt", action="store_true")
    parser.add_argument("--skip-scrapecreators-x", action="store_true")
    parser.add_argument("--skip-polymarket", action="store_true")
    parser.add_argument("--skip-supabase-import", action="store_true")
    parser.add_argument("--keep-existing", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print machine-readable tick output.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    payload = run_tick(args)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(format_tick_report(payload))
    if any(row.get("status") == "failed" for row in payload.get("rows", [])):
        raise SystemExit(1)


def run_tick(args: argparse.Namespace | SimpleNamespace, *, now: datetime | None = None) -> dict[str, Any]:
    tick_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    kg_path = _repo_path(args.kg)
    out_root = _repo_path(args.out_root)
    env_file = _repo_path(args.env_file)
    import_supabase = not bool(getattr(args, "skip_supabase_import", False))
    matches = select_due_matches(
        kg_path=kg_path,
        now=tick_now,
        lead_minutes=float(args.lead_minutes),
        lookahead_minutes=float(args.lookahead_minutes),
        grace_minutes=float(args.grace_minutes),
        limit=int(args.limit),
    )
    rows: list[dict[str, Any]] = []
    for match in matches:
        snapshot_id = snapshot_id_for_match(match, competition=str(args.competition))
        base_row = {
            **match_summary(match),
            "snapshot_id": snapshot_id,
            "collection_due_utc": match["prediction_cutoff_utc"],
        }
        marker = read_marker(out_root, snapshot_id)
        marker_status = str((marker or {}).get("status") or "")
        if not args.force and marker_status in TERMINAL_IMPORTED_STATUSES:
            rows.append({**base_row, "status": "skipped", "action": "already_done", "marker_status": marker_status})
            continue
        if not args.force and not import_supabase and marker_status == "collected":
            rows.append({**base_row, "status": "skipped", "action": "already_collected", "marker_status": marker_status})
            continue
        if args.dry_run:
            rows.append({**base_row, "status": "dry_run", "action": "would_collect"})
            continue
        if import_supabase and not args.force and snapshot_exists_in_supabase(snapshot_id, env_file=env_file):
            row = {**base_row, "status": "skipped", "action": "supabase_existing"}
            write_marker(out_root, snapshot_id, {**row, "status": "supabase_existing", "updated_at_utc": _iso_utc(tick_now)})
            rows.append(row)
            continue

        lock_path = _lock_path(out_root, snapshot_id)
        if not acquire_lock(lock_path, stale_after=timedelta(minutes=float(args.stale_lock_minutes))):
            rows.append({**base_row, "status": "skipped", "action": "locked"})
            continue
        try:
            if import_supabase and marker_status == "collected" and marker and marker.get("source_dir"):
                row = import_existing_collection(
                    args=args,
                    env_file=env_file,
                    match=match,
                    snapshot_id=snapshot_id,
                    source_dir=Path(str(marker["source_dir"])),
                    base_row=base_row,
                )
            else:
                row = collect_and_import_match(
                    args=args,
                    env_file=env_file,
                    out_root=out_root,
                    now=tick_now,
                    match=match,
                    snapshot_id=snapshot_id,
                    import_supabase=import_supabase,
                    base_row=base_row,
                )
            rows.append(row)
            write_marker(out_root, snapshot_id, {**row, "updated_at_utc": _iso_utc(datetime.now(timezone.utc))})
        finally:
            release_lock(lock_path)

    return {
        "schema_version": "prematch-automation-tick-v1",
        "created_at_utc": _iso_utc(tick_now),
        "lead_minutes": float(args.lead_minutes),
        "lookahead_minutes": float(args.lookahead_minutes),
        "grace_minutes": float(args.grace_minutes),
        "kg": str(kg_path),
        "out_root": str(out_root),
        "selected": len(matches),
        "rows": rows,
    }


def select_due_matches(
    *,
    kg_path: Path,
    now: datetime,
    lead_minutes: float,
    lookahead_minutes: float,
    grace_minutes: float,
    limit: int,
) -> list[dict[str, Any]]:
    payload = json.loads(kg_path.read_text(encoding="utf-8"))
    window_start = now - timedelta(minutes=grace_minutes)
    window_end = now + timedelta(minutes=lookahead_minutes)
    matches: list[dict[str, Any]] = []
    for entity in payload.get("entities") or []:
        if entity.get("entity_type") != "match":
            continue
        attrs = dict(entity.get("attributes") or {})
        score = attrs.get("score")
        if score not in (None, "", {}):
            continue
        kickoff = _match_kickoff_utc(
            match_date=str(attrs.get("date") or ""),
            match_time=str(attrs.get("time") or ""),
        )
        if kickoff is None or kickoff <= now:
            continue
        due = kickoff - timedelta(minutes=lead_minutes)
        if due < window_start or due > window_end:
            continue
        home = str(attrs.get("team1") or "").strip()
        away = str(attrs.get("team2") or "").strip()
        if not home or not away:
            continue
        matches.append(
            {
                "entity_id": str(entity.get("entity_id") or ""),
                "name": str(entity.get("name") or f"{home} vs {away}"),
                "home_team": home,
                "away_team": away,
                "kickoff": kickoff,
                "kickoff_utc": _iso_utc(kickoff),
                "prediction_cutoff": due,
                "prediction_cutoff_utc": _iso_utc(due),
                "ground": str(attrs.get("ground") or ""),
                "group": str(attrs.get("group") or ""),
                "round": str(attrs.get("round") or ""),
            }
        )
    matches.sort(key=lambda item: (item["prediction_cutoff"], item["name"]))
    return matches if limit <= 0 else matches[:limit]


def collect_and_import_match(
    *,
    args: argparse.Namespace | SimpleNamespace,
    env_file: Path,
    out_root: Path,
    now: datetime,
    match: dict[str, Any],
    snapshot_id: str,
    import_supabase: bool,
    base_row: dict[str, Any],
) -> dict[str, Any]:
    run_root = out_root / f"tick_{now.strftime('%Y%m%d_%H%M%S')}"
    run_root.mkdir(parents=True, exist_ok=True)
    collect_args = _collect_args(args, env_file=env_file)
    old_cwd = Path.cwd()
    os.chdir(REPO_ROOT)
    try:
        collected = collect_match(match=match, args=collect_args, run_root=run_root)
    finally:
        os.chdir(old_cwd)
    row = {**base_row, **collected, "action": "collected", "status": "collected"}
    if collected.get("prematch_status") != "ok":
        return {**row, "status": "failed", "error": "prematch_scrape_failed"}
    source_dir = Path(str(collected.get("out_dir") or ""))
    if not import_supabase:
        return row
    return import_existing_collection(
        args=args,
        env_file=env_file,
        match=match,
        snapshot_id=snapshot_id,
        source_dir=source_dir,
        base_row=row,
    )


def import_existing_collection(
    *,
    args: argparse.Namespace | SimpleNamespace,
    env_file: Path,
    match: dict[str, Any],
    snapshot_id: str,
    source_dir: Path,
    base_row: dict[str, Any],
) -> dict[str, Any]:
    result = import_snapshot_to_supabase(
        env_file=env_file,
        source_dir=source_dir,
        snapshot_id=snapshot_id,
        competition=str(args.competition),
        match_id=str(match.get("entity_id") or ""),
        keep_existing=bool(args.keep_existing),
        timeout=int(args.import_timeout),
    )
    if result["returncode"] == 0:
        return {**base_row, "status": "imported", "action": "imported", "import": result, "source_dir": str(source_dir)}
    return {**base_row, "status": "failed", "action": "import_failed", "import": result, "source_dir": str(source_dir)}


def import_snapshot_to_supabase(
    *,
    env_file: Path,
    source_dir: Path,
    snapshot_id: str,
    competition: str,
    match_id: str,
    keep_existing: bool,
    timeout: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(IMPORT_SCRIPT),
        "--env",
        str(env_file),
        "--source-dir",
        str(source_dir),
        "--snapshot-id",
        snapshot_id,
        "--competition",
        competition,
        "--match-id",
        match_id,
    ]
    if keep_existing:
        command.append("--keep-existing")
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except Exception as exc:
        return {"returncode": -1, "command": command, "stdout": "", "stderr": str(exc)}
    return {
        "returncode": completed.returncode,
        "command": command,
        "stdout": _tail(completed.stdout),
        "stderr": _tail(completed.stderr),
    }


def snapshot_exists_in_supabase(snapshot_id: str, *, env_file: Path) -> bool:
    try:
        settings = load_supabase_service_settings(env_file)
    except SupabaseRequestError:
        try:
            settings = load_supabase_settings(env_file)
        except SupabaseRequestError:
            return False
    try:
        rows = request_json(
            settings,
            "prematch_snapshots?"
            f"select=snapshot_id,status&snapshot_id=eq.{_quote(snapshot_id)}&status=eq.ready&limit=1",
        )
    except SupabaseRequestError:
        return False
    return isinstance(rows, list) and bool(rows)


def snapshot_id_for_match(match: dict[str, Any], *, competition: str) -> str:
    return (
        f"{competition}_{_slug(match['home_team'])}_vs_{_slug(match['away_team'])}_"
        f"{_timestamp_slug(match['prediction_cutoff_utc'])}"
    )


def read_marker(out_root: Path, snapshot_id: str) -> dict[str, Any] | None:
    path = _marker_path(out_root, snapshot_id)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_marker(out_root: Path, snapshot_id: str, payload: dict[str, Any]) -> None:
    path = _marker_path(out_root, snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def acquire_lock(path: Path, *, stale_after: timedelta) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if age > stale_after:
            path.unlink()
        else:
            return False
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        file.write(json.dumps({"pid": os.getpid(), "created_at_utc": _iso_utc(datetime.now(timezone.utc))}) + "\n")
    return True


def release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def format_tick_report(payload: dict[str, Any]) -> str:
    rows = payload.get("rows") or []
    lines = [
        (
            "Prematch automation tick: "
            f"{payload.get('selected', 0)} due match(es), "
            f"lead={payload.get('lead_minutes')}m, "
            f"window=-{payload.get('grace_minutes')}m/+{payload.get('lookahead_minutes')}m"
        )
    ]
    if not rows:
        lines.append("No prematch snapshots due in this tick.")
        return "\n".join(lines)
    for row in rows:
        lines.append(
            f"- {row.get('name')}: {row.get('status')} "
            f"({row.get('action')}) snapshot={row.get('snapshot_id')}"
        )
    return "\n".join(lines)


def _collect_args(args: argparse.Namespace | SimpleNamespace, *, env_file: Path) -> SimpleNamespace:
    return SimpleNamespace(
        kg=_repo_path(args.kg),
        cutoff_hours=float(args.lead_minutes) / 60.0,
        window_days=int(args.window_days),
        max_records=int(args.max_records),
        x_max_queries=int(args.x_max_queries),
        polymarket_timeout=int(args.polymarket_timeout),
        polymarket_raw_clob_limit=int(args.polymarket_raw_clob_limit),
        env_file=env_file,
        skip_google_news=bool(args.skip_google_news),
        skip_gdelt=bool(args.skip_gdelt),
        skip_scrapecreators_x=bool(args.skip_scrapecreators_x),
        skip_polymarket=bool(args.skip_polymarket),
    )


def _marker_path(out_root: Path, snapshot_id: str) -> Path:
    return _repo_path(out_root) / "_automation" / f"{_file_slug(snapshot_id)}.json"


def _lock_path(out_root: Path, snapshot_id: str) -> Path:
    return _repo_path(out_root) / "_automation" / "locks" / f"{_file_slug(snapshot_id)}.lock"


def _repo_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def _file_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return slug or "snapshot"


def _timestamp_slug(value: str) -> str:
    text = value.strip().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        cleaned = re.sub(r"[^0-9A-Za-z]+", "", text)
        return cleaned or "unknown_cutoff"
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def _quote(value: str) -> str:
    import urllib.parse

    return urllib.parse.quote(str(value), safe="")


def _tail(value: str, max_chars: int = 1600) -> str:
    text = value.strip()
    return text[-max_chars:] if len(text) > max_chars else text


if __name__ == "__main__":
    main()
