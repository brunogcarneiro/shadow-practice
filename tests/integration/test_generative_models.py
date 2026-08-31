import os
import unittest
from unittest.mock import patch

from shadow_practice.infrastructure.generative import GenerativeModelError, GenerativeModelManager


class FakeResponse:
    def __init__(self, *, ok=True, payload=None, content=b"", text="", status_code=200, headers=None):
        self.ok = ok
        self._payload = payload
        self.content = content
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttpClient:
    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_response = None
        self.get_response = None

    def post(self, *args, **kwargs):
        self.posts.append((args, kwargs))
        return self.post_response

    def get(self, *args, **kwargs):
        self.gets.append((args, kwargs))
        return self.get_response


class GenerativeModelManagerTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeHttpClient()
        self.manager = GenerativeModelManager(
            openai_responses_url="https://openai.test/responses",
            openai_rewrite_model="test-model",
            qwen_tts_service_url="http://qwen.test",
            http_client=self.http,
        )

    def test_rewrite_extracts_output_text_and_sends_prompt(self):
        self.http.post_response = FakeResponse(payload={
            "output": [
                {"content": [{"type": "output_text", "text": "First paragraph."}]},
                {"content": [{"type": "output_text", "text": "\n\nSecond paragraph."}]},
            ]
        })

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            result = self.manager.rewrite_meeting_speech("We need to align.")

        self.assertEqual(result, "First paragraph.\n\nSecond paragraph.")
        args, kwargs = self.http.posts[0]
        self.assertEqual(args, ("https://openai.test/responses",))
        self.assertEqual(kwargs["json"]["model"], "test-model")
        self.assertIn("MUST be in English", kwargs["json"]["input"])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")

    def test_rewrite_requires_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(GenerativeModelError, "OPENAI_API_KEY"):
                self.manager.rewrite_meeting_speech("Text")

    def test_rewrite_formats_api_error(self):
        self.http.post_response = FakeResponse(
            ok=False,
            status_code=429,
            text="rate limit",
            payload={"error": {"code": "insufficient_quota", "message": "Quota exceeded"}},
            headers={"x-request-id": "req_test"},
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            with self.assertRaisesRegex(GenerativeModelError, r"(?s)429.*insufficient_quota.*req_test"):
                self.manager.rewrite_meeting_speech("Text")

    def test_tts_health_returns_payload(self):
        self.http.get_response = FakeResponse(payload={"status": "ready", "speaker": "Aiden"})

        result = self.manager.get_tts_health()

        self.assertEqual(result["speaker"], "Aiden")
        self.assertEqual(self.http.gets[0][0], ("http://qwen.test/health",))
        self.assertEqual(self.http.gets[0][1]["timeout"], 2)

    def test_tts_synthesis_returns_audio_bytes(self):
        self.http.post_response = FakeResponse(content=b"RIFF-wav")

        result = self.manager.synthesize_speech("Hello")

        self.assertEqual(result, b"RIFF-wav")
        args, kwargs = self.http.posts[0]
        self.assertEqual(args, ("http://qwen.test/synthesize",))
        self.assertEqual(kwargs["json"], {"text": "Hello"})
        self.assertEqual(kwargs["timeout"], 300)

    def test_tts_synthesis_rejects_empty_audio(self):
        self.http.post_response = FakeResponse(content=b"")

        with self.assertRaisesRegex(GenerativeModelError, "áudio vazio"):
            self.manager.synthesize_speech("Hello")


if __name__ == "__main__":
    unittest.main()
