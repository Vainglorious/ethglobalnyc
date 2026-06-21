"""Tiny dependency-free Supabase REST client for Colony tools."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .env import load_env_file


@dataclass(frozen=True)
class SupabaseSettings:
    url: str
    key: str


class SupabaseRequestError(RuntimeError):
    pass


def load_supabase_settings(env_path: str | Path) -> SupabaseSettings:
    load_env_file(env_path)
    url = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        or os.environ.get("SUPABASE_ANON_KEY")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY")
    )
    if not url:
        raise SupabaseRequestError("Missing SUPABASE_URL in colony/.env")
    if not key:
        raise SupabaseRequestError("Missing SUPABASE_PUBLISHABLE_KEY in colony/.env")
    return SupabaseSettings(url=url.rstrip("/"), key=key)


def fetch_colony(settings: SupabaseSettings, pubkey: str, *, select: str = "*") -> dict[str, Any] | None:
    rows = request_json(
        settings,
        f"colonies?select={select}&pubkey=eq.{_quote(pubkey)}&limit=1",
    )
    if not rows:
        return None
    return rows[0]


def upsert_colony(settings: SupabaseSettings, row: dict[str, Any]) -> list[dict[str, Any]]:
    return request_json(
        settings,
        "colonies?on_conflict=pubkey",
        method="POST",
        body=row,
        prefer="resolution=merge-duplicates,return=representation",
    )


def delete_colony(settings: SupabaseSettings, pubkey: str) -> list[dict[str, Any]]:
    return request_json(
        settings,
        f"colonies?pubkey=eq.{_quote(pubkey)}",
        method="DELETE",
        prefer="return=representation",
    )


def fetch_colony_ants(
    settings: SupabaseSettings,
    pubkey: str,
    *,
    status: str | None = None,
    select: str = "*",
    limit: int | None = None,
) -> list[dict[str, Any]]:
    path = f"colony_ants?select={select}&pubkey=eq.{_quote(pubkey)}&order=agent_id.asc"
    if status and status != "all":
        path += f"&status=eq.{_quote(status)}"
    if limit is not None:
        path += f"&limit={int(limit)}"
    return request_json(settings, path)


def upsert_colony_ants(settings: SupabaseSettings, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    return request_json(
        settings,
        "colony_ants?on_conflict=pubkey,agent_id",
        method="POST",
        body=rows,
        prefer="resolution=merge-duplicates,return=representation",
    )


def update_ant_status(
    settings: SupabaseSettings,
    *,
    pubkey: str,
    agent_id: str,
    status: str,
) -> list[dict[str, Any]]:
    return request_json(
        settings,
        f"colony_ants?pubkey=eq.{_quote(pubkey)}&agent_id=eq.{_quote(agent_id)}",
        method="PATCH",
        body={"status": status},
        prefer="return=representation",
    )


def delete_colony_ants(settings: SupabaseSettings, pubkey: str) -> list[dict[str, Any]]:
    return request_json(
        settings,
        f"colony_ants?pubkey=eq.{_quote(pubkey)}",
        method="DELETE",
        prefer="return=representation",
    )


def request_json(
    settings: SupabaseSettings,
    path: str,
    *,
    method: str = "GET",
    body: Any = None,
    prefer: str = "",
) -> Any:
    endpoint = f"{settings.url}/rest/v1/{path.lstrip('/')}"
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "apikey": settings.key,
        "Authorization": f"Bearer {settings.key}",
        "Accept": "application/json",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer

    request = urllib.request.Request(endpoint, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - user-configured Supabase URL.
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise SupabaseRequestError(f"Supabase {method} failed with HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseRequestError(f"Supabase {method} failed: {exc}") from exc
    return json.loads(payload) if payload.strip() else []


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")
