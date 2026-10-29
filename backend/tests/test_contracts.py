"""Offline contract tests for the Insights backend.

No real database, HTTP, or LLM access: ClickHouse, PostgreSQL, and the model
endpoint are all stubbed at module boundaries. Environment variables are set
BEFORE importing app modules because app/main.py and app/clickhouse.py read
them at import time.
"""

import asyncio
import json
import os
import unittest
from unittest import mock

import httpx

# Dummy env must exist before app import (main.py / clickhouse.py read at import time)
os.environ.setdefault("LANGFUSE_HOST", "http://langfuse:3000")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-test")



os.environ.setdefault("MODEL_URL", "http://model.example/v1")
os.environ.setdefault("MODEL_NAME", "test-model")
# Short SSE interval so a lingering generator never stalls test teardown.
os.environ.setdefault("SSE_INTERVAL_SECONDS", "1")

from fastapi.testclient import TestClient  # noqa: E402

from app import clickhouse, summarizer, text  # noqa: E402
from app.main import _get_data, app  # noqa: E402


def _generation(trace_id: str, content: str) -> dict:
    return {
        "trace_id": trace_id,
        "input": json.dumps([{"role": "user", "content": content}]),
        "output": "[]",
    }


class HealthContract(unittest.TestCase):
    def test_health_status_ok(self):
        with TestClient(app) as client:
            resp = client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})


class ResponseShapeContracts(unittest.TestCase):
    def test_projects_shape(self):
        rows = [{"id": "p-1", "name": "run-1"}, {"id": "p-2", "name": "run-2"}]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_projects", return_value=rows), \
             TestClient(app) as client:
            resp = client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIsInstance(body, list)
        for item in body:
            self.assertEqual(set(item), {"id", "name"})

    def test_wordcloud_shape(self):
        gens = [_generation("t-1", "kubernetes openshift kubernetes")]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_generations", return_value=gens) as gg, \
             TestClient(app) as client:
            resp = client.get("/api/wordcloud?project_id=p-1&filter=valid")
        self.assertEqual(resp.status_code, 200)
        gg.assert_called_once_with("p-1", "valid")
        body = resp.json()
        self.assertIsInstance(body, list)
        for item in body:
            self.assertEqual(set(item), {"word", "count"})
        words = {item["word"]: item["count"] for item in body}
        self.assertEqual(words.get("kubernetes"), 2)
        self.assertEqual(words.get("openshift"), 1)

    def test_wordgraph_shape(self):
        gens = [_generation("t-1", "kubernetes openshift kafka")]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_generations", return_value=gens), \
             TestClient(app) as client:
            resp = client.get("/api/wordgraph?project_id=p-1&filter=all")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(set(body), {"nodes", "edges"})
        for node in body["nodes"]:
            self.assertEqual(set(node), {"id", "word", "count"})
        for edge in body["edges"]:
            self.assertEqual(set(edge), {"source", "target", "weight"})

    def test_invalid_filter_rejected(self):
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_generations", return_value=[]), \
             TestClient(app) as client:
            resp = client.get("/api/wordcloud?project_id=p-1&filter=nope")
        self.assertEqual(resp.status_code, 422)


class GetDataRouting(unittest.TestCase):
    def test_blocked_filter_uses_traces(self):
        blocked = [{"id": "t-9", "timestamp": "2026-01-01", "input": "{}", "output": ""}]
        with mock.patch.object(
            clickhouse, "get_blocked_traces", return_value=blocked
        ) as gt, mock.patch.object(
            clickhouse, "get_generations", return_value=[]
        ) as gg:
            result = _get_data("p-1", "blocked")
        self.assertEqual(result, blocked)
        gt.assert_called_once_with("p-1")
        gg.assert_not_called()

    def test_valid_filter_uses_generations(self):
        gens = [_generation("t-1", "hello world")]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]) as gt, \
             mock.patch.object(clickhouse, "get_generations", return_value=gens) as gg:
            result = _get_data("p-1", "valid")
        self.assertEqual(result, gens)
        gg.assert_called_once_with("p-1", "valid")
        gt.assert_not_called()

    def test_all_filter_uses_generations(self):
        gens = [_generation("t-1", "hello world")]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_generations", return_value=gens) as gg:
            result = _get_data("p-1", "all")
        self.assertEqual(result, gens)
        gg.assert_called_once_with("p-1", "all")


class BlockedEndpoint(unittest.TestCase):
    def test_blocked_returns_tagged_and_detected(self):
        tagged = [{"id": "t-9", "timestamp": "2026-01-01", "input": "{}", "output": ""}]
        detected = [_generation("t-1", "message")]
        with mock.patch.object(
            clickhouse, "get_blocked_traces", return_value=tagged
        ) as gt, mock.patch.object(
            clickhouse, "get_generations", return_value=detected
        ) as gg, TestClient(app) as client:
            resp = client.get("/api/blocked?project_id=p-1")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"tagged": tagged, "detected": detected})
        gt.assert_called_once_with("p-1")
        gg.assert_called_once_with("p-1", "blocked")


class SummaryEndpoint(unittest.TestCase):
    def test_empty_summary_existing_message(self):
        with mock.patch.object(
            clickhouse, "get_generations", return_value=[]
        ) as gg, TestClient(app) as client:
            resp = client.get("/api/summary?project_id=p-1&filter=valid")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp.json(), {"summary": "No data available for this project."}
        )
        gg.assert_called_once_with("p-1", "valid")

    def test_summarizer_failure_returns_500(self):
        gens = [_generation("t-1", "hello")]
        with mock.patch.object(
            clickhouse, "get_generations", return_value=gens
        ), mock.patch.object(
            summarizer, "summarize_project", side_effect=RuntimeError("model down")
        ) as sp, TestClient(app) as client:
            resp = client.get("/api/summary?project_id=p-1&filter=valid")
        sp.assert_called_once_with(gens)
        self.assertEqual(resp.status_code, 500)
        self.assertIn("model down", resp.json()["detail"])


class LangfuseApiContract(unittest.TestCase):
    """v2 observations API call contract: auth, path, filters, pagination."""

    def _fake_pages(self, pages):
        it = iter(pages)

        class FakeResp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        def fake_get(url, params=None, auth=None, timeout=None):
            if "calls" not in captured:
                captured["calls"] = []
            captured["calls"].append({"url": url, "params": params, "auth": auth, "timeout": timeout})
            captured.update(url=url, params=params, auth=auth, timeout=timeout)
            return FakeResp(next(it))

        captured = {}

        class FakeHttpx:
            @staticmethod
            def get(*a, **kw):
                return fake_get(*a, **kw)

        return captured, FakeHttpx

    def test_get_generations_requests_generations_and_excludes_blocked(self):
        pages = [
            {"data": [
                {"traceId": "t-1", "input": "[]", "output": "[]", "type": "GENERATION"},
                {"traceId": "t-2", "input": "[]", "output": "[]", "type": "GENERATION"},
            ], "meta": {}},
            {"data": [
                {"traceId": "t-1", "id": "b-1", "startTime": "2026-10-29T00:00:00Z",
                 "input": "{\"user_message\": \"x\"}", "output": "BLOCKED"},
            ], "meta": {}},
        ]
        captured, FakeHttpx = self._fake_pages(pages)
        with mock.patch.object(clickhouse.httpx, "get", side_effect=lambda *a, **kw: FakeHttpx.get(*a, **kw)):
            rows = clickhouse.get_generations("p-1", "valid")
        self.assertEqual([r["trace_id"] for r in rows], ["t-2"])
        self.assertEqual(captured["url"], "http://langfuse:3000/api/public/v2/observations")
        self.assertEqual(captured["auth"], ("pk-lf-test", "sk-lf-test"))
        first_params = captured["calls"][0]["params"]
        self.assertEqual(first_params["type"], "GENERATION")
        self.assertIn("fromStartTime", first_params)
        self.assertIn("fields", first_params)

    def test_blocked_uses_tag_filter(self):
        pages = [{"data": [], "meta": {}}]
        captured, FakeHttpx = self._fake_pages(pages)
        with mock.patch.object(clickhouse.httpx, "get", side_effect=lambda *a, **kw: FakeHttpx.get(*a, **kw)):
            clickhouse.get_blocked_traces("p-1")
        self.assertIn('"blocked"', captured["params"]["filter"])
        self.assertNotIn("type", captured["params"])

    def test_projects_maps_id_and_name(self):
        pages = [{"data": [{"id": "p-1", "name": "Projekt"}], "meta": {}}]
        captured, FakeHttpx = self._fake_pages(pages)
        with mock.patch.object(clickhouse.httpx, "get", side_effect=lambda *a, **kw: FakeHttpx.get(*a, **kw)):
            rows = clickhouse.get_projects()
        self.assertEqual(rows, [{"id": "p-1", "name": "Projekt"}])


class SummarizerChatContract(unittest.TestCase):
    def test_chat_posts_openai_contract(self):
        captured = {}

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "choices": [
                        {"message": {"content": "  summary text  "}}
                    ]
                }

        def fake_post(url, json=None, timeout=None):
            captured.update(url=url, json=json, timeout=timeout)
            return FakeResp()

        with mock.patch.object(summarizer.httpx, "post", side_effect=fake_post):
            result = summarizer._chat(
                [{"role": "user", "content": "hi"}], max_tokens=99
            )

        self.assertEqual(result, "summary text")
        self.assertEqual(captured["url"], "http://model.example/v1/chat/completions")
        self.assertEqual(
            captured["json"],
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 99,
            },
        )
        self.assertEqual(captured["timeout"], 120)


class SSEStreamContract(unittest.TestCase):
    """Consume the SSE stream as a bounded async body iterator.

    The /api/stream response is an infinite event stream, so it must never be
    consumed through TestClient's eager request/response cycle. Instead we
    drive the ASGI app directly with httpx.AsyncClient, read only the first
    `data:` line under a hard asyncio.wait_for timeout, and always close the
    response in a finally block.
    """

    TIMEOUT = 5.0

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _first_event(self) -> dict:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            async with client.stream(
                "GET", "/api/stream?project_id=p-1&filter=valid"
            ) as response:
                self.assertEqual(response.status_code, 200)
                try:
                    payload = await asyncio.wait_for(
                        self._read_first_event(response), timeout=self.TIMEOUT
                    )
                finally:
                    await response.aclose()
        return payload

    async def _read_first_event(self, response) -> dict:
        async for chunk in response.aiter_raw():
            text = chunk.decode("utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[len("data:"):].strip())
        self.fail("stream ended before any data event")

    def test_stream_update_payload_contract(self):
        gens = [_generation("t-1", "kubernetes openshift kubernetes kafka")]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_generations", return_value=gens) as gg:
            payload = self._run(self._first_event())
        gg.assert_called_once_with("p-1", "valid")
        self.assertEqual(set(payload), {"wordcloud", "wordgraph"})
        for item in payload["wordcloud"]:
            self.assertEqual(set(item), {"word", "count"})
        self.assertEqual(set(payload["wordgraph"]), {"nodes", "edges"})

    def test_stream_error_payload_contract(self):
        def boom(project_id, filter):
            raise RuntimeError("clickhouse exploded")

        async def first_error_event() -> dict:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                async with client.stream(
                    "GET", "/api/stream?project_id=p-1&filter=blocked"
                ) as response:
                    self.assertEqual(response.status_code, 200)
                    try:
                        payload = await asyncio.wait_for(
                            self._read_first_event(response), timeout=self.TIMEOUT
                        )
                    finally:
                        await response.aclose()
            return payload

        with mock.patch.object(clickhouse, "get_blocked_traces", side_effect=boom):
            payload = self._run(first_error_event())
        self.assertEqual(set(payload), {"error"})
        self.assertIn("clickhouse exploded", payload["error"])


class TextContract(unittest.TestCase):
    def test_extract_user_messages_blocked_trace_format(self):
        msgs = text._extract_user_messages(
            json.dumps({"user_message": "ahoj světe"})
        )
        self.assertEqual(msgs, ["ahoj světe"])

    def test_extract_user_messages_skips_autogen(self):
        msgs = text._extract_user_messages(
            json.dumps([{"role": "user", "content": "Suggest 3-5 relevant follow-up"}])
        )
        self.assertEqual(msgs, [])


if __name__ == "__main__":
    unittest.main()
