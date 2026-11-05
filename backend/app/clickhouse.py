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


# The reply the guardrails proxy substitutes for a blocked prompt (English and
# Czech halves). A GENERATION whose output is this reply was a blocked turn.
_BLOCK_REPLY_MARKERS = (
    "blocked because it contained inappropriate language",
    "byl zablokován",
)


def _user_messages(raw_input: Any) -> list[str]:
    """User messages of a GENERATION input (a JSON chat array)."""
    try:
        data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [
        m["content"] for m in data
        if isinstance(m, dict) and m.get("role") == "user"
        and isinstance(m.get("content"), str)
    ]


def _prompt_of_blocked_span(obs: dict[str, Any]) -> str | None:
    try:
        data = json.loads(obs.get("input") or "")
    except Exception:
        return None
    msg = data.get("user_message") if isinstance(data, dict) else None
    return msg if isinstance(msg, str) and msg else None


def _is_block_reply(output: Any) -> bool:
    if not isinstance(output, str):
        return False
    low = output.lower()
    return any(marker in low for marker in _BLOCK_REPLY_MARKERS)


def _blocked_by_containment(turns: list[dict[str, Any]], spans: set[str]) -> set[str]:
    """OpenWebUI task prompts (title generation etc.) embed the chat history,
    so a blocked span can be a long text containing the offending message
    instead of equalling it. When a span contains exactly one of this chat's
    messages, that message is the blocked one; spans containing several are
    ambiguous and ignored."""
    msgs = {m for r in turns for m in _user_messages(r.get("input")) if len(m) >= 5}
    found: set[str] = set()
    for span in spans:
        hit = {m for m in msgs if m in span and m != span}
        if len(hit) == 1:
            found |= hit
    return found


def _new_user_messages(rows: list[dict[str, Any]], blocked_prompts: set[str],
                       drop_blocked: bool) -> list[dict[str, Any]]:
    """Collapse the repeated chat history in GENERATION observations.

    OpenWebUI resends the whole conversation with every turn, so each turn's
    GENERATION input contains all earlier user messages again. Counting every
    observation's messages counts early messages once per later turn, and it
    also re-counts a blocked prompt in every later turn of the same chat.

    Per chat (trace), keep each distinct user message once, drop any message
    that was blocked (matched by the guardrail span's prompt, or by a turn
    whose reply is the block message when the span was not recorded), and
    emit one row per chat.
    """
    by_chat: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_chat.setdefault(r.get("traceId") or r.get("id") or "", []).append(r)

    out: list[dict[str, Any]] = []
    for chat_id, turns in by_chat.items():
        turns.sort(key=lambda r: r.get("startTime") or "")
        blocked = set(blocked_prompts)
        for r in turns if drop_blocked else ():
            if _is_block_reply(r.get("output")):
                msgs = _user_messages(r.get("input"))
                if msgs:
                    blocked.add(msgs[-1])  # the turn's own prompt
        if drop_blocked:
            blocked |= _blocked_by_containment(turns, blocked_prompts)
        kept: list[str] = []
        seen: set[str] = set()
        for r in turns:
            for m in _user_messages(r.get("input")):
                if m in seen or m in blocked:
                    continue
                seen.add(m)
                kept.append(m)
        if kept:
            out.append({
                "traceId": chat_id,
                "input": json.dumps([{"role": "user", "content": m} for m in kept]),
                "output": turns[-1].get("output"),
            })
    return out


def get_generations(project_id: str, filter: Filter = "valid") -> list[dict]:
    """
    Return one row per chat with its distinct user messages.
    filter: "valid" → exclude blocked prompts, "blocked" → only blocked,
    "all" → everything (blocked prompts included, history still deduplicated).
    Blocked detection uses the guardrail spans tagged 'blocked' by the
    guardrails proxy, plus the substituted reply as a fallback.
    """
    if filter == "blocked":
        rows = _fetch_observations(project_id, "blocked")
        return [_to_generation_row(r) for r in rows]

    rows = _fetch_observations(project_id, "all")
    blocked_prompts: set[str] = set()
    if filter == "valid":
        blocked_prompts = {
            p for p in map(_prompt_of_blocked_span, _fetch_observations(project_id, "blocked")) if p
        }
    return [
        _to_generation_row(r)
        for r in _new_user_messages(rows, blocked_prompts, drop_blocked=(filter == "valid"))
    ]


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
