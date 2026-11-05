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
from app.main import _get_data, app, stream  # noqa: E402


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
                {"traceId": "t-2", "type": "GENERATION", "output": "[]",
                 "input": json.dumps([{"role": "user", "content": "ahoj"}])},
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



BLOCK_REPLY = (
    "\u26a0\ufe0f Your message was blocked because it contained inappropriate language. "
    "Please rephrase your question without swear words."
)


def _obs(trace_id, user_messages, output="fine", start="2026-11-05T10:00:00Z"):
    return {
        "traceId": trace_id,
        "startTime": start,
        "type": "GENERATION",
        "output": output,
        "input": json.dumps([{"role": "user", "content": m} for m in user_messages]),
    }


def _guardrail(prompt, trace_id="guard-1"):
    return {
        "traceId": trace_id,
        "id": "g-" + trace_id,
        "startTime": "2026-11-05T10:00:00Z",
        "type": "GUARDRAIL",
        "input": json.dumps({"user_message": prompt}),
        "output": "BLOCKED",
    }


class FilteringContract(unittest.TestCase):
    """Valid/all filtering as seen through the public get_generations()."""

    def _run(self, pages, flt):
        it = iter(pages)

        class Resp:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self.payload

        with mock.patch.object(clickhouse.httpx, "get",
                               side_effect=lambda *a, **kw: Resp(next(it))):
            return clickhouse.get_generations("p-1", flt)

    @staticmethod
    def _messages(rows):
        out = []
        for r in rows:
            out.append([m["content"] for m in json.loads(r["input"])])
        return out

    def test_valid_drops_blocked_prompt_from_the_blocked_turn_and_later_history(self):
        # One chat: turn 1 was blocked; turn 2 repeats the whole history.
        gens = {"data": [
            _obs("chat-1", ["rude words"], output=BLOCK_REPLY, start="2026-11-05T10:00:01Z"),
            _obs("chat-1", ["rude words", "nice question"], start="2026-11-05T10:00:09Z"),
        ], "meta": {}}
        blocked = {"data": [_guardrail("rude words")], "meta": {}}
        rows = self._run([gens, blocked], "valid")
        self.assertEqual(self._messages(rows), [["nice question"]])

    def test_valid_detects_blocked_turn_by_its_reply_when_the_span_is_missing(self):
        # Telemetry fails open: the guardrail span may be dropped under load.
        gens = {"data": [
            _obs("chat-1", ["rude words"], output=BLOCK_REPLY, start="2026-11-05T10:00:01Z"),
            _obs("chat-1", ["rude words", "nice question"], start="2026-11-05T10:00:09Z"),
        ], "meta": {}}
        rows = self._run([gens, {"data": [], "meta": {}}], "valid")
        self.assertEqual(self._messages(rows), [["nice question"]])

    def test_each_message_counted_once_per_chat_despite_repeated_history(self):
        gens = {"data": [
            _obs("chat-1", ["one"], start="2026-11-05T10:00:01Z"),
            _obs("chat-1", ["one", "two"], start="2026-11-05T10:00:02Z"),
            _obs("chat-1", ["one", "two", "three"], start="2026-11-05T10:00:03Z"),
        ], "meta": {}}
        rows = self._run([gens, {"data": [], "meta": {}}], "valid")
        self.assertEqual(self._messages(rows), [["one", "two", "three"]])
        freqs = {w["word"]: w["count"] for w in text.compute_word_frequencies(rows)}
        self.assertEqual(freqs, {"one": 1, "two": 1, "three": 1})

    def test_same_text_in_different_chats_still_counts_per_chat(self):
        gens = {"data": [
            _obs("chat-1", ["hello there"]),
            _obs("chat-2", ["hello there"]),
        ], "meta": {}}
        rows = self._run([gens, {"data": [], "meta": {}}], "valid")
        freqs = {w["word"]: w["count"] for w in text.compute_word_frequencies(rows)}
        self.assertEqual(freqs["hello"], 2)

    def test_all_keeps_blocked_prompts_but_still_dedupes_history(self):
        gens = {"data": [
            _obs("chat-1", ["rude words"], output=BLOCK_REPLY, start="2026-11-05T10:00:01Z"),
            _obs("chat-1", ["rude words", "nice question"], start="2026-11-05T10:00:09Z"),
        ], "meta": {}}
        rows = self._run([gens], "all")
        self.assertEqual(self._messages(rows), [["rude words", "nice question"]])

    def test_valid_drops_message_found_inside_a_long_task_prompt_span(self):
        gens = {"data": [
            _obs("chat-1", ["rude words", "nice question"]),
        ], "meta": {}}
        blocked = {"data": [_guardrail("<chat_history>USER: rude words</chat_history>")], "meta": {}}
        rows = self._run([gens, blocked], "valid")
        self.assertEqual(self._messages(rows), [["nice question"]])

    def test_span_containing_several_messages_is_ambiguous_and_ignored(self):
        gens = {"data": [_obs("chat-1", ["rude words", "nice question"])], "meta": {}}
        blocked = {"data": [_guardrail("USER: rude words USER: nice question")], "meta": {}}
        rows = self._run([gens, blocked], "valid")
        self.assertEqual(self._messages(rows), [["rude words", "nice question"]])

    def test_legitimate_answer_mentioning_swearing_is_not_treated_as_blocked(self):
        gens = {"data": [
            _obs("chat-1", ["how do I report abuse"],
                 output="Avoid inappropriate language when you write the report."),
        ], "meta": {}}
        rows = self._run([gens, {"data": [], "meta": {}}], "valid")
        self.assertEqual(self._messages(rows), [["how do I report abuse"]])


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

    The /api/stream response is an infinite event stream. Consuming it through
    httpx's ASGITransport hangs, because the transport buffers the response
    body and the stream never ends. Instead we call the endpoint function
    directly and consume the returned EventSourceResponse.body_iterator:
    read only the first yielded event under a hard asyncio.wait_for timeout,
    and always close the iterator in a finally block.
    """

    TIMEOUT = 5.0

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    async def _first_event(self, filter: str) -> dict:
        response = await stream(project_id="p-1", filter=filter)
        body = response.body_iterator
        try:
            return await asyncio.wait_for(
                self._read_first_event(body), timeout=self.TIMEOUT
            )
        finally:
            await body.aclose()

    async def _read_first_event(self, body) -> dict:
        async for event in body:
            return json.loads(event["data"])
        self.fail("stream ended before any data event")

    def test_stream_update_payload_contract(self):
        gens = [_generation("t-1", "kubernetes openshift kubernetes kafka")]
        with mock.patch.object(clickhouse, "get_blocked_traces", return_value=[]), \
             mock.patch.object(clickhouse, "get_generations", return_value=gens) as gg:
            payload = self._run(self._first_event("valid"))
        gg.assert_called_once_with("p-1", "valid")
        self.assertEqual(set(payload), {"wordcloud", "wordgraph"})
        for item in payload["wordcloud"]:
            self.assertEqual(set(item), {"word", "count"})
        self.assertEqual(set(payload["wordgraph"]), {"nodes", "edges"})

    def test_stream_error_payload_contract(self):
        def boom(project_id):
            raise RuntimeError("clickhouse exploded")

        with mock.patch.object(clickhouse, "get_blocked_traces", side_effect=boom):
            payload = self._run(self._first_event("blocked"))
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
