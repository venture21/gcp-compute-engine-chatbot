"""실제 SDK 전송 계층에서 API 키 대신 ADC Bearer 인증을 사용하는지 확인한다."""

import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx
from google import genai
from google.oauth2.credentials import Credentials


class ADCTransportTests(unittest.TestCase):
    def test_generate_content_uses_project_endpoint_and_oauth_despite_ambient_api_key(self):
        seen = []

        def respond(request):
            seen.append(request)
            return httpx.Response(200, json={
                "candidates": [{"content":{"role":"model","parts":[{"text":"테스트 응답"}]}}],
            })

        async def scenario():
            with patch.dict(os.environ, {"GEMINI_API_KEY": "unused-dummy-key", "GOOGLE_API_KEY": "unused-dummy-key"}):
                client = genai.Client(
                    enterprise=True, project="test-project", location="global",
                    credentials=Credentials(token="synthetic-test-token"),
                    http_options={"async_client_args": {"transport": httpx.MockTransport(respond)}},
                )
                try:
                    result = await client.aio.models.generate_content(model="gemini-3.8-flash", contents="테스트")
                    self.assertEqual(result.text, "테스트 응답")
                finally:
                    await client.aio.aclose()
                    client.close()

        asyncio.run(scenario())
        self.assertEqual(len(seen), 1)
        request = seen[0]
        self.assertEqual(request.url.host, "aiplatform.googleapis.com")
        self.assertIn("/projects/test-project/locations/global/publishers/google/models/gemini-3.8-flash:generateContent", request.url.path)
        self.assertEqual(request.headers["authorization"], "Bearer synthetic-test-token")
        self.assertNotIn("x-goog-api-key", request.headers)
        self.assertNotIn("key", request.url.params)
        self.assertEqual(json.loads(request.content)["contents"][0]["parts"][0]["text"], "테스트")


if __name__ == "__main__":
    unittest.main()
