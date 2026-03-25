import asyncio
import json
import os
from typing import AsyncIterator, Literal

import psycopg2
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from . import clickhouse, text, summarizer

app = FastAPI(title="HSWorkshop Insights API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

POSTGRES_URL = os.environ["POSTGRES_URL"]
SSE_INTERVAL = int(os.environ.get("SSE_INTERVAL_SECONDS", "30"))

Filter = Literal["valid", "all", "blocked"]


def _pg_projects() -> list[dict]:
    conn = psycopg2.connect(POSTGRES_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM projects ORDER BY name")
            return [{"id": row[0], "name": row[1]} for row in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/projects")
def get_projects():
    try:
        return _pg_projects()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def _get_data(project_id: str, filter: Filter) -> list[dict]:
    """Fetch conversation data for the given filter.

    For 'blocked', uses traces.input ({"user_message": "..."}) since blocked
    requests never reach the LLM and have no GENERATION observations.
    For 'valid'/'all', uses observations of type GENERATION.
    """
    if filter == "blocked":
        return clickhouse.get_blocked_traces(project_id)
    return clickhouse.get_generations(project_id, filter)


@app.get("/api/wordcloud")
def get_wordcloud(
    project_id: str = Query(...),
    filter: Filter = Query("valid"),
):
    return text.compute_word_frequencies(_get_data(project_id, filter))


@app.get("/api/wordgraph")
def get_wordgraph(
    project_id: str = Query(...),
    filter: Filter = Query("valid"),
):
    return text.compute_word_graph(_get_data(project_id, filter))


@app.get("/api/blocked")
def get_blocked(project_id: str = Query(...)):
    tagged = clickhouse.get_blocked_traces(project_id)
    detected = clickhouse.get_generations(project_id, "blocked")
    return {"tagged": tagged, "detected": detected}


@app.get("/api/summary")
def get_summary(
    project_id: str = Query(...),
    filter: Filter = Query("valid"),
):
    generations = clickhouse.get_generations(project_id, filter)
    if not generations:
        return {"summary": "No data available for this project."}
    try:
        return {"summary": summarizer.summarize_project(generations)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/stream")
async def stream(
    project_id: str = Query(...),
    filter: Filter = Query("valid"),
):
    async def generator() -> AsyncIterator[dict]:
        while True:
            try:
                generations = await asyncio.to_thread(_get_data, project_id, filter)
                words = text.compute_word_frequencies(generations)
                graph = text.compute_word_graph(generations)
                yield {
                    "event": "update",
                    "data": json.dumps({"wordcloud": words, "wordgraph": graph}),
                }
            except Exception as exc:
                yield {"event": "error", "data": json.dumps({"error": str(exc)})}
            await asyncio.sleep(SSE_INTERVAL)

    return EventSourceResponse(generator())


@app.get("/health")
def health():
    return {"status": "ok"}
