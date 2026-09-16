import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def interaction(status="completed", interaction_id="interaction-1"):
    return SimpleNamespace(
        id=interaction_id,
        status=status,
        output_text="안녕하세요!",
        steps=[SimpleNamespace(type=kind) for kind in (
            "thought", "google_search_call", "code_execution_call",
        )],
    )


class ChatAPITests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GEMINI_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.http = TestClient(server.app)
        self.http.__enter__()
        self.addCleanup(self.http.__exit__, None, None, None)
        self.interactions = SimpleNamespace(
            create=AsyncMock(return_value=interaction()),
            get=AsyncMock(return_value=interaction()),
        )

    def enable_chat(self):
        server.app.state.genai_client = SimpleNamespace(interactions=self.interactions)

    def test_startup_without_key_serves_health_status_and_static_files(self):
        self.assertEqual(self.http.get("/healthz").json(), {"status": "ok"})
        status = self.http.get("/api/status").json()
        self.assertFalse(status["hasApiKey"])
        self.assertEqual(status["defaultModel"], "gemini-3.8-flash")
        self.assertEqual(len(status["models"]), 3)
        for path in ("/", "/app.js", "/style.css"):
            response = self.http.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn("136-111-157-64.sslip.io", response.text)
        self.assertEqual(self.http.get("/.env").status_code, 404)
        self.assertEqual(self.http.get("/server.py").status_code, 404)

    def test_missing_key_returns_service_unavailable(self):
        response = self.http.post("/api/chat", json={"input": "안녕"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("GEMINI_API_KEY", response.json()["detail"])

    def test_rejects_bad_input_before_calling_gemini(self):
        self.enable_chat()
        for payload, status in (
            ({"input": " \n "}, 400),
            ({"input": "가" * 10001}, 422),
            ({"input": "질문", "model": "unknown-model"}, 400),
            ({"input": "질문", "previousInteractionId": "x" * 513}, 422),
            ({}, 422),
            ({"input": 42}, 422),
        ):
            with self.subTest(payload_type=str(payload)[:60]):
                self.assertEqual(self.http.post("/api/chat", json=payload).status_code, status)
        self.interactions.create.assert_not_awaited()

    def test_completed_chat_preserves_response_contract_and_skips_poll(self):
        self.enable_chat()
        response = self.http.post("/api/chat", json={"input": " 안녕하세요 "})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["reply"], "안녕하세요!")
        self.assertEqual(data["interactionId"], "interaction-1")
        self.assertTrue(data["hasThought"])
        self.assertEqual(data["toolsUsed"], {"googleSearch": True, "codeExecution": True})
        self.interactions.create.assert_awaited_once_with(
            model=server.DEFAULT_MODEL, input="안녕하세요", background=True, tools=server.TOOLS,
        )
        self.interactions.get.assert_not_awaited()

    def test_polls_pending_interaction_and_forwards_conversation_id(self):
        self.enable_chat()
        self.interactions.create.return_value = interaction("in_progress")
        with patch.object(server.asyncio, "sleep", new=AsyncMock()):
            response = self.http.post("/api/chat", json={
                "input": "이어서 설명해줘", "model": "gemini-3.7-flash",
                "previousInteractionId": "previous-turn",
            })
        self.assertEqual(response.status_code, 200)
        self.interactions.get.assert_awaited_once_with("interaction-1")
        kwargs = self.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-3.7-flash")
        self.assertEqual(kwargs["previous_interaction_id"], "previous-turn")

    def test_agent_uses_remote_environment_and_keeps_conversation(self):
        self.enable_chat()
        response = self.http.post("/api/chat", json={
            "input": "분석해줘", "model": "antigravity-preview-05-2026",
            "previousInteractionId": "agent-turn",
        })
        self.assertEqual(response.status_code, 200)
        kwargs = self.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "antigravity-preview-05-2026")
        self.assertEqual(kwargs["environment"], "remote")
        self.assertEqual(kwargs["previous_interaction_id"], "agent-turn")

    def test_terminal_failure_does_not_poll_forever(self):
        self.enable_chat()
        for status in ("failed", "cancelled", "requires_action"):
            with self.subTest(status=status):
                self.interactions.create.return_value = interaction(status)
                response = self.http.post("/api/chat", json={"input": "질문"})
                self.assertEqual(response.status_code, 502)
        self.interactions.get.assert_not_awaited()

    def test_upstream_errors_do_not_expose_details(self):
        self.enable_chat()
        self.interactions.create.side_effect = RuntimeError("secret-key-sensitive-value")
        response = self.http.post("/api/chat", json={"input": "질문"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-key-sensitive-value", response.text)

    def test_timeout_includes_initial_create_request(self):
        self.enable_chat()

        async def slow_create(**kwargs):
            await asyncio.sleep(1)

        self.interactions.create.side_effect = slow_create
        with patch.object(server, "CHAT_TIMEOUT_SECONDS", 0.02):
            response = self.http.post("/api/chat", json={"input": "질문"})
        self.assertEqual(response.status_code, 504)

    def test_timeout_also_bounds_polling(self):
        self.enable_chat()
        self.interactions.create.return_value = interaction("in_progress")
        with patch.object(server, "CHAT_TIMEOUT_SECONDS", 0.02):
            response = self.http.post("/api/chat", json={"input": "질문"})
        self.assertEqual(response.status_code, 504)

    def test_waiting_chat_does_not_block_health_or_another_chat(self):
        self.enable_chat()

        async def scenario():
            started = asyncio.Event()
            release = asyncio.Event()

            async def create(**kwargs):
                if kwargs["input"] == "느린 질문":
                    started.set()
                    await release.wait()
                return interaction(interaction_id=kwargs["input"])

            self.interactions.create.side_effect = create
            transport = httpx.ASGITransport(app=server.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                pending = asyncio.create_task(client.post("/api/chat", json={"input": "느린 질문"}))
                try:
                    await asyncio.wait_for(started.wait(), timeout=1)
                    health = await asyncio.wait_for(client.get("/healthz"), timeout=1)
                    other = await asyncio.wait_for(
                        client.post("/api/chat", json={"input": "다른 질문"}), timeout=1,
                    )
                    self.assertEqual(health.status_code, 200)
                    self.assertEqual(other.json()["interactionId"], "다른 질문")
                    self.assertFalse(pending.done())
                finally:
                    release.set()
                    slow = await pending
                self.assertEqual(slow.json()["interactionId"], "느린 질문")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
