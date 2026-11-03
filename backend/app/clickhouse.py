"""Langfuse v4 Observations API v2 client.

Replaces direct ClickHouse/PostgreSQL queries (v3 data model, removed in v4).
All reads go through the public API with basic auth (project API keys).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

LANGFUSE_HOST = os.environ["LANGFUSE_HOST"]                     # http://langfuse:3000
LANGFUSE_PUBLIC_KEY = os.environ["LANGFUSE_PUBLIC_KEY"]         # pk-lf-...
LANGFUSE_SECRET_KEY = os.environ["LANGFUSE_SECRET_KEY"]         # sk-lf-...

Filter = Literal["valid", "all", "blocked"]

_FIELDS = "core,basic,io,trace_context"

# v3 kept blocked traces in the `traces` table with input {"user_message": ...}.
# In v4 the guardrails proxy sends one root GUARDRAIL observation tagged
# "blocked" with the same input shape, so consumers keep working unchanged.
_BLOCKED_FILTER = [{"type": "arrayOptions", "column": "tags",
                    "operator": "any of", "value": ["blocked"]}]


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    resp = httpx.get(
        f"{LANGFUSE_HOST}{path}",
        params=params,
        auth=(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def get_projects() -> list[dict[str, Any]]:
    """Return [{"id", "name"}] — projects visible to the API key."""
    data = _get("/api/public/projects")
    return [{"id": p["id"], "name": p["name"]} for p in data.get("data", [])]


def _fetch_observations(project_id: str, filter: Filter, page_limit: int = 1000,
                        max_rows: int = 5000) -> list[dict[str, Any]]:
    """Fetch GENERATION observations (or blocked guardrail rows) for a project."""
    to_time = datetime.now(timezone.utc)
    from_time = to_time - timedelta(days=30)

    params: dict[str, Any] = {
        "fromStartTime": from_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "toStartTime": to_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fields": _FIELDS,
        "limit": page_limit,
    }
    if filter == "blocked":
        params["filter"] = json.dumps(_BLOCKED_FILTER)
    else:
        params["type"] = "GENERATION"

    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    while len(rows) < max_rows:
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        page = _get("/api/public/v2/observations", page_params)
        rows.extend(page.get("data", []))
        cursor = page.get("meta", {}).get("cursor")
        if not cursor:
            break
    return rows[:max_rows]


def _to_generation_row(obs: dict[str, Any]) -> dict[str, Any]:
    """Map an observation to the row shape the app already consumes:
    {"trace_id", "input", "output"} with JSON-string input/output."""
    return {
        "trace_id": obs.get("traceId", ""),
        "input": obs.get("input"),
        "output": obs.get("output"),
    }


def get_generations(project_id: str, filter: Filter = "valid") -> list[dict]:
    """
    Return GENERATION observations for a project.
    filter: "valid" → exclude blocked, "blocked" → only blocked, "all" → everything.
    Blocked detection uses the 'blocked' tag set by the guardrails proxy.
    """
    if filter == "blocked":
        rows = _fetch_observations(project_id, "blocked")
    else:
        rows = _fetch_observations(project_id, "all")
        if filter == "valid":
            blocked_ids = {
                r.get("traceId") for r in _fetch_observations(project_id, "blocked")
            }
            rows = [r for r in rows if r.get("traceId") not in blocked_ids]
    return [_to_generation_row(r) for r in rows]


def get_blocked_traces(project_id: str) -> list[dict]:
    """Return blocked requests (root guardrail observations tagged 'blocked')."""
    rows = _fetch_observations(project_id, "blocked")
    out = []
    for r in rows:
        out.append({
            "id": r.get("id", ""),
            "timestamp": r.get("startTime", ""),
            "input": r.get("input"),
            "output": r.get("output"),
        })
    return out
