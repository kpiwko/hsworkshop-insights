import json
import os
from typing import Any, Literal

import httpx

CLICKHOUSE_URL  = os.environ["CLICKHOUSE_URL"]   # http://clickhouse:8123
CLICKHOUSE_USER = os.environ["CLICKHOUSE_USER"]
CLICKHOUSE_PASS = os.environ["CLICKHOUSE_PASSWORD"]

Filter = Literal["valid", "all", "blocked"]

_BLOCKED_SUBQUERY = (
    "SELECT id FROM traces"
    " WHERE project_id = {project_id:String}"
    "   AND has(tags, 'blocked')"
    "   AND is_deleted = 0"
)


def _query(sql: str, params: dict[str, str] | None = None) -> list[dict[str, Any]]:
    url_params: dict[str, str] = {"default_format": "JSONEachRow"}
    if params:
        for k, v in params.items():
            url_params[f"param_{k}"] = v
    resp = httpx.post(
        CLICKHOUSE_URL,
        content=sql,
        params=url_params,
        auth=(CLICKHOUSE_USER, CLICKHOUSE_PASS),
        timeout=30,
    )
    resp.raise_for_status()
    rows = []
    for line in resp.text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def get_generations(project_id: str, filter: Filter = "valid") -> list[dict]:
    """
    Return GENERATION observations for a project.
    filter: "valid" → exclude blocked, "blocked" → only blocked, "all" → everything.
    Blocked detection uses traces.tags=['blocked'] set by the guardrails proxy.
    """
    if filter == "blocked":
        extra = f"AND trace_id IN ({_BLOCKED_SUBQUERY})"
    elif filter == "valid":
        extra = f"AND trace_id NOT IN ({_BLOCKED_SUBQUERY})"
    else:
        extra = ""

    return _query(
        f"""
        SELECT trace_id, input, output
        FROM observations
        WHERE project_id = {{project_id:String}}
          AND type = 'GENERATION'
          AND is_deleted = 0
          AND input IS NOT NULL
          {extra}
        ORDER BY start_time DESC
        FORMAT JSONEachRow
        """,
        params={"project_id": project_id},
    )


def get_blocked_traces(project_id: str) -> list[dict]:
    """Return traces tagged as 'blocked' (created by guardrails proxy)."""
    return _query(
        """
        SELECT id, timestamp, input, output
        FROM traces
        WHERE project_id = {project_id:String}
          AND has(tags, 'blocked')
          AND is_deleted = 0
        ORDER BY timestamp DESC
        FORMAT JSONEachRow
        """,
        params={"project_id": project_id},
    )
