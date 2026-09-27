"""OpenAI 제공자: 실제 SDK 는 쓰되 HTTP 호출만 가짜로 바꿔 요청 구성과 응답 처리를 확인한다."""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import openai  # noqa: F401
except ImportError:  # pragma: no cover
    openai = None

from modules import LLMRequest  # noqa: E402
from providers import ProviderError  # noqa: E402


def text_item(text):
    return types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="output_text", text=text)])


def fake_response(text="", status="completed", reason=None, output=None, model="gpt-6-luna"):
    return types.SimpleNamespace(
        output_text=text, status=status, model=model,
        incomplete_details=types.SimpleNamespace(reason=reason) if reason else None,
        output=output if output is not None else [text_item(text)],
    )


@unittest.skipIf(openai is None, "openai 패키지 없음")
class OpenAIProviderTest(unittest.TestCase):
    def setUp(self):
        from providers.openai_provider import OpenAIProvider
        self.provider = OpenAIProvider({"api_key": "test"})
        self.calls = []
        self.next = fake_response("일기 본문")
        test = self

        def create(**kw):
            test.calls.append(kw)
            if isinstance(test.next, Exception):
                raise test.next
            return test.next

        self.provider.client = types.SimpleNamespace(responses=types.SimpleNamespace(create=create))

    def req(self, schema=None, effort=None):
        return LLMRequest(module="journal", model="gpt-6-luna", system="sys",
                          messages=[{"role": "user", "content": "facts"}], max_tokens=500,
                          effort=effort, json_schema=schema)

    def test_request_shape(self):
        result = self.provider.complete(self.req(effort="low"))
        kw = self.calls[0]
        self.assertEqual(kw["model"], "gpt-6-luna")
        self.assertEqual(kw["instructions"], "sys")
        self.assertEqual(kw["input"], [{"role": "user", "content": "facts"}])
        self.assertEqual(kw["max_output_tokens"], 500)
        self.assertEqual(kw["reasoning"], {"effort": "low"})
        self.assertFalse(kw["store"])
        self.assertEqual(result.text, "일기 본문")
        self.assertEqual(result.model, "gpt-6-luna")

    def test_no_effort_omits_reasoning(self):
        self.provider.complete(self.req())
        self.assertNotIn("reasoning", self.calls[0])

    def test_json_schema(self):
        self.next = fake_response('{"event":"storm"}')
        schema = {"type": "object", "properties": {"event": {"type": "string"}}, "required": ["event"],
                  "additionalProperties": False}
        result = self.provider.complete(self.req(schema=schema))
        fmt = self.calls[0]["text"]["format"]
        self.assertEqual((fmt["type"], fmt["strict"], fmt["name"]), ("json_schema", True, "journal_output"))
        self.assertEqual(result.json, {"event": "storm"})

    def test_refusal(self):
        refusal = types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="refusal", refusal="no")])
        self.next = fake_response("", output=[refusal])
        with self.assertRaises(ProviderError) as cm:
            self.provider.complete(self.req())
        self.assertEqual(cm.exception.code, "refusal")

    def test_incomplete_without_text(self):
        self.next = fake_response("", status="incomplete", reason="max_output_tokens", output=[])
        with self.assertRaises(ProviderError) as cm:
            self.provider.complete(self.req())
        self.assertEqual(cm.exception.code, "incomplete")

    def test_incomplete_with_text_is_kept(self):
        self.next = fake_response("잘린 일기", status="incomplete", reason="max_output_tokens")
        self.assertEqual(self.provider.complete(self.req()).text, "잘린 일기")

    def test_error_mapping(self):
        import httpx2
        request = httpx2.Request("POST", "https://api.openai.com/v1/responses")

        def status_error(cls, code):
            return cls("err", response=httpx2.Response(code, request=request), body=None)

        cases = [
            (openai.APITimeoutError(request=request), "timeout"),
            (openai.APIConnectionError(request=request), "network"),
            (status_error(openai.AuthenticationError, 401), "auth"),
            (status_error(openai.NotFoundError, 404), "bad_model"),
            (status_error(openai.RateLimitError, 429), "rate_limited"),
            (status_error(openai.InternalServerError, 500), "server_error"),
        ]
        for exc, code in cases:
            self.next = exc
            with self.assertRaises(ProviderError) as cm:
                self.provider.complete(self.req())
            self.assertEqual(cm.exception.code, code, type(exc).__name__)


if __name__ == "__main__":
    unittest.main()
