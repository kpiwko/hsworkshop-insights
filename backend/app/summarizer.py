import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

MODEL_URL = os.environ.get(
    "MODEL_URL",
    "http://gpt-oss-20b-service-predictor.hsworkshop.svc.cluster.local:8080/v1",
)
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-oss-20b-service")

_CHUNK_SIZE = 8   # sessions per map-reduce chunk
_MAX_MSG_CHARS = 500  # truncate individual messages to limit context size
_MAP_WORKERS = 8  # parallel LLM calls during the map phase


def _chat(messages: list[dict], max_tokens: int = 512) -> str:
    resp = httpx.post(
        f"{MODEL_URL}/chat/completions",
        json={"model": MODEL_NAME, "messages": messages, "max_tokens": max_tokens},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _summarize_session(session_messages: list[str]) -> str:
    joined = "\n".join(f"- {m[:_MAX_MSG_CHARS]}" for m in session_messages[:20])
    return _chat([
        {"role": "system", "content": "You are a concise analyst. Summarize the key topics of these user messages in 2-3 sentences. Detect the predominant language of the messages and write your summary in that language."},
        {"role": "user", "content": f"User messages from one chat session:\n{joined}"},
    ])


def _summarize_summaries(summaries: list[str]) -> str:
    joined = "\n\n".join(f"{i+1}. {s}" for i, s in enumerate(summaries))
    return _chat([
        {"role": "system", "content": "You are a concise analyst. Synthesize these session summaries into one overall summary covering the main themes and topics discussed across all sessions. Be concrete and specific. Write in the predominant language of the summaries."},
        {"role": "user", "content": joined},
    ], max_tokens=768)


def summarize_project(generations: list[dict[str, Any]]) -> str:
    """Map-reduce summarization: one summary per session, then reduce."""
    import json

    # Group user messages by trace_id (≈ session)
    sessions: dict[str, list[str]] = {}
    for gen in generations:
        tid = gen.get("trace_id", "unknown")
        try:
            messages = json.loads(gen.get("input") or "[]")
        except Exception:
            continue
        user_msgs = [
            m["content"] for m in messages
            if isinstance(m, dict)
            and m.get("role") == "user"
            and "Suggest 3-5 relevant follow-up" not in m.get("content", "")
            and "### Task:" not in m.get("content", "")
        ]
        if user_msgs:
            sessions.setdefault(tid, []).extend(user_msgs)

    if not sessions:
        return "No conversation data available for this project."

    # Map: summarize each session in parallel
    session_list = list(sessions.values())[:40]  # cap at 40 sessions
    session_summaries = [None] * len(session_list)
    with ThreadPoolExecutor(max_workers=_MAP_WORKERS) as pool:
        futures = {pool.submit(_summarize_session, msgs): i for i, msgs in enumerate(session_list)}
        for future in as_completed(futures):
            i = futures[future]
            try:
                session_summaries[i] = future.result()
            except Exception as exc:
                session_summaries[i] = f"(session summary failed: {exc})"

    if len(session_summaries) == 1:
        return session_summaries[0]

    # Reduce in chunks if many sessions
    while len(session_summaries) > _CHUNK_SIZE:
        chunks = [session_summaries[i:i+_CHUNK_SIZE]
                  for i in range(0, len(session_summaries), _CHUNK_SIZE)]
        session_summaries = [_summarize_summaries(c) for c in chunks]

    return _summarize_summaries(session_summaries)
