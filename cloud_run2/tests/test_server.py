import asyncio
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError

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


def generated_response(text="안녕하세요!"):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(
            content=SimpleNamespace(parts=[SimpleNamespace(executable_code=True)]),
            grounding_metadata=SimpleNamespace(web_search_queries=["test"]),
        )],
        usage_metadata=SimpleNamespace(thoughts_token_count=10),
    )


class ChatAPITests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-adc-project", "GOOGLE_CLOUD_LOCATION": "global"})
        env.start()
        self.addCleanup(env.stop)
        adc = patch.object(server.google.auth, "default", return_value=(AnonymousCredentials(), "test-adc-project"))
        adc.start()
        self.addCleanup(adc.stop)
        self.http = TestClient(server.app)
        self.http.__enter__()
        self.addCleanup(self.http.__exit__, None, None, None)
        self.interactions = SimpleNamespace(
            create=AsyncMock(return_value=interaction()),
            get=AsyncMock(return_value=interaction()),
        )

        self.models = SimpleNamespace(generate_content=AsyncMock(return_value=generated_response()))

    def enable_chat(self):
        server.app.state.genai_client = SimpleNamespace(interactions=self.interactions, models=self.models)

    def test_adc_startup_serves_health_status_and_static_files(self):
        self.assertEqual(self.http.get("/healthz").json(), {"status": "ok"})
        self.assertEqual(self.http.get("/api/health").json(), {"status": "ok"})
        status = self.http.get("/api/status").json()
        self.assertEqual(status["authMode"], "ADC")
        self.assertTrue(status["credentialsConfigured"])
        self.assertEqual(status["project"], "test-adc-project")
        self.assertEqual(status["location"], "global")
        self.assertNotIn("hasApiKey", status)
        self.assertEqual(status["defaultModel"], "gemini-3.8-flash")
        self.assertEqual(len(status["models"]), 3)
        for path in ("/", "/app.js", "/style.css"):
            response = self.http.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn("136-111-157-64.sslip.io", response.text)
        self.assertEqual(self.http.get("/.env").status_code, 404)
        self.assertEqual(self.http.get("/server.py").status_code, 404)

    def test_missing_adc_fails_startup_instead_of_falling_back_to_api_key(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "dummy-key"}):
            with patch.object(server.google.auth, "default", side_effect=DefaultCredentialsError("ADC missing")):
                with self.assertRaises(DefaultCredentialsError):
                    with TestClient(server.app):
                        pass

    def test_rejects_bad_input_before_calling_gemini(self):
        self.enable_chat()
        for payload, status in (
            ({"input": " \n "}, 400),
            ({"input": "가" * 10001}, 422),
            ({"input": "질문", "model": "unknown-model"}, 400),
            ({"input": "질문", "previousInteractionId": "x" * 513}, 422),
            ({}, 422),
            ({"input": 42}, 422),
            ({"input": "질문", "history": [{"role":"system","text":"invalid"}]}, 422),
            ({"input": "질문", "history": [{"role":"user","text":"x"}]*21}, 422),
        ):
            with self.subTest(payload_type=str(payload)[:60]):
                self.assertEqual(self.http.post("/api/chat", json=payload).status_code, status)
        self.interactions.create.assert_not_awaited()
        self.models.generate_content.assert_not_awaited()

    def test_completed_chat_preserves_response_contract_and_skips_poll(self):
        self.enable_chat()
        response = self.http.post("/api/chat", json={"input": " 안녕하세요 "})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["reply"], "안녕하세요!")
        self.assertIsNone(data["interactionId"])
        self.assertTrue(data["hasThought"])
        self.assertEqual(data["toolsUsed"], {"googleSearch": True, "codeExecution": True})
        self.models.generate_content.assert_awaited_once_with(
            model=server.DEFAULT_MODEL,
            contents=[{"role":"user","parts":[{"text":"안녕하세요"}]}],
            config={"tools":server.MODEL_TOOLS},
        )
        self.interactions.create.assert_not_awaited()
        self.interactions.get.assert_not_awaited()

    def test_model_conversation_history_is_forwarded_without_server_session_state(self):
        self.enable_chat()
        response = self.http.post("/api/chat", json={
            "input":"내 별명은?", "model":"gemini-3.7-flash",
            "history":[{"role":"user","text":"내 별명은 구름이야"}, {"role":"model","text":"알겠습니다"}],
        })
        self.assertEqual(response.status_code,200)
        kwargs = self.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"],"gemini-3.7-flash")
        self.assertEqual([c["role"] for c in kwargs["contents"]],["user","model","user"])
        self.assertEqual(kwargs["contents"][0]["parts"][0]["text"],"내 별명은 구름이야")
        self.interactions.create.assert_not_awaited()

    def test_empty_model_response_does_not_report_success(self):
        self.enable_chat()
        self.models.generate_content.return_value = generated_response("")
        self.assertEqual(self.http.post("/api/chat",json={"input":"질문"}).status_code,502)

    def test_polls_pending_interaction_and_forwards_conversation_id(self):
        self.enable_chat()
        self.interactions.create.return_value = interaction("in_progress")
        with patch.object(server.asyncio, "sleep", new=AsyncMock()):
            response = self.http.post("/api/chat", json={
                "input": "이어서 설명해줘", "model": "antigravity-preview-05-2026",
                "previousInteractionId": "previous-turn",
            })
        self.assertEqual(response.status_code, 200)
        self.interactions.get.assert_awaited_once_with("interaction-1")
        kwargs = self.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["agent"], "antigravity-preview-05-2026")
        self.assertEqual(kwargs["previous_interaction_id"], "previous-turn")

    def test_agent_uses_remote_environment_and_keeps_conversation(self):
        self.enable_chat()
        response = self.http.post("/api/chat", json={
            "input": "분석해줘", "model": "antigravity-preview-05-2026",
            "previousInteractionId": "agent-turn",
        })
        self.assertEqual(response.status_code, 200)
        kwargs = self.interactions.create.call_args.kwargs
        self.assertEqual(kwargs["agent"], "antigravity-preview-05-2026")
        self.assertEqual(kwargs["environment"], {"type": "remote"})
        self.assertEqual(kwargs["previous_interaction_id"], "agent-turn")
        self.assertNotIn("model", kwargs)
        self.assertNotIn("tools", kwargs)
        self.http.post("/api/chat", json={"input":"계속", "model":"antigravity-preview-05-2026", "environmentId":"env-test"})
        self.assertEqual(self.interactions.create.call_args.kwargs["environment"], "env-test")

    def test_terminal_failure_does_not_poll_forever(self):
        self.enable_chat()
        for status in ("failed", "cancelled", "requires_action"):
            with self.subTest(status=status):
                self.interactions.create.return_value = interaction(status)
                response = self.http.post("/api/chat", json={"input": "질문", "model":"antigravity-preview-05-2026"})
                self.assertEqual(response.status_code, 502)
        self.interactions.get.assert_not_awaited()

    def test_upstream_errors_do_not_expose_details(self):
        self.enable_chat()
        self.models.generate_content.side_effect = RuntimeError("secret-key-sensitive-value")
        response = self.http.post("/api/chat", json={"input": "질문"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret-key-sensitive-value", response.text)

    def test_timeout_includes_initial_create_request(self):
        self.enable_chat()

        async def slow_create(**kwargs):
            await asyncio.sleep(1)

        self.models.generate_content.side_effect = slow_create
        with patch.object(server, "CHAT_TIMEOUT_SECONDS", 0.02):
            response = self.http.post("/api/chat", json={"input": "질문"})
        self.assertEqual(response.status_code, 504)

    def test_timeout_also_bounds_polling(self):
        self.enable_chat()
        self.interactions.create.return_value = interaction("in_progress")
        with patch.object(server, "CHAT_TIMEOUT_SECONDS", 0.02):
            response = self.http.post("/api/chat", json={"input": "질문", "model":"antigravity-preview-05-2026"})
        self.assertEqual(response.status_code, 504)

    def test_waiting_chat_does_not_block_health_or_another_chat(self):
        self.enable_chat()

        async def scenario():
            started = asyncio.Event()
            release = asyncio.Event()

            async def create(**kwargs):
                text = kwargs["contents"][-1]["parts"][0]["text"]
                if text == "느린 질문":
                    started.set()
                    await release.wait()
                return generated_response(text)

            self.models.generate_content.side_effect = create
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
                    self.assertEqual(other.json()["reply"], "다른 질문")
                    self.assertFalse(pending.done())
                finally:
                    release.set()
                    slow = await pending
                self.assertEqual(slow.json()["reply"], "느린 질문")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
