"""DeepSeek 제공자: 요청 구성(사고량·JSON 모드·스키마 안내)과 응답 검사·재시도·오류 처리. 실제 API 는 부르지 않는다."""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import openai  # noqa: E402

from modules import LLMRequest  # noqa: E402
from providers import ProviderError, create_provider  # noqa: E402
from providers.deepseek_provider import check_schema  # noqa: E402

SCHEMA = {"type": "object", "properties": {"reply": {"type": "string"},
                                           "trade": {"type": "string", "enum": ["none", "offer"]}},
          "required": ["reply", "trade"], "additionalProperties": False}


def request(effort="low", schema=SCHEMA):
    return LLMRequest(module="radio", model="deepseek-flash", system="You are Ray.",
                      messages=[{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"},
                                {"role": "user", "content": "trade?"}],
                      max_tokens=4000, effort=effort, json_schema=schema)


def answer(text, finish="stop"):
    return SimpleNamespace(model="deepseek-flash",
                           choices=[SimpleNamespace(finish_reason=finish, message=SimpleNamespace(content=text))])


class FakeCompletions:
    def __init__(self, *results, error=None):
        self.results, self.error, self.calls = list(results), error, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.results.pop(0)


def provider(completions, **cfg):
    p = create_provider("deepseek", {"api_key": "test-key", **cfg})
    p.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return p


def status_error(cls, code, message="boom"):
    resp = httpx.Response(code, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"))
    return cls(message, response=resp, body=None)


class DeepSeekProviderTest(unittest.TestCase):
    def test_request_shape(self):
        c = FakeCompletions(answer('{"reply": "Sure.", "trade": "none"}'))
        res = provider(c).complete(request("xhigh"))
        call = c.calls[0]
        self.assertEqual(call["model"], "deepseek-flash")
        self.assertEqual(call["max_tokens"], 4000)
        self.assertEqual(call["response_format"], {"type": "json_object"})
        self.assertEqual([m["role"] for m in call["messages"]], ["system", "user", "assistant", "user"])
        system = call["messages"][0]["content"]
        self.assertTrue(system.startswith("You are Ray."))
        self.assertIn("json", system)
        self.assertIn('"required": ["reply", "trade"]', system)
        self.assertEqual(call["extra_body"], {"thinking": {"type": "enabled"}, "reasoning_effort": "max"})
        self.assertEqual(res.json, {"reply": "Sure.", "trade": "none"})
        self.assertEqual(res.model, "deepseek-flash")

    def test_effort_mapping(self):
        for effort, body in (("none", {"thinking": {"type": "disabled"}}),
                             ("low", {"thinking": {"type": "enabled"}, "reasoning_effort": "low"}),
                             ("medium", {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}),
                             ("max", {"thinking": {"type": "enabled"}, "reasoning_effort": "max"})):
            c = FakeCompletions(answer("plain"))
            provider(c).complete(request(effort, schema=None))
            self.assertEqual(c.calls[0]["extra_body"], body, effort)
            self.assertNotIn("response_format", c.calls[0])
        # 설정으로 사고를 끄면 effort 와 무관하게 끈다
        c = FakeCompletions(answer("plain"))
        provider(c, thinking=False).complete(request("high", schema=None))
        self.assertEqual(c.calls[0]["extra_body"], {"thinking": {"type": "disabled"}})
        # effort 가 없으면 서버 기본값
        c = FakeCompletions(answer("plain"))
        provider(c).complete(request(None, schema=None))
        self.assertNotIn("extra_body", c.calls[0])

    def test_plain_text(self):
        res = provider(FakeCompletions(answer("  Hello there.  "))).complete(request(schema=None))
        self.assertEqual(res.text, "Hello there.")
        self.assertIsNone(res.json)

    def test_schema_mismatch_retries_once(self):
        c = FakeCompletions(answer('{"reply": "Sure.", "trade": "maybe"}'),
                            answer('{"reply": "Sure.", "trade": "offer"}'))
        res = provider(c).complete(request())
        self.assertEqual(res.json["trade"], "offer")
        self.assertEqual(len(c.calls), 2)
        retry = c.calls[1]["messages"]
        self.assertEqual(retry[-2], {"role": "assistant", "content": '{"reply": "Sure.", "trade": "maybe"}'})
        self.assertIn("$.trade must be one of", retry[-1]["content"])

    def test_schema_mismatch_twice_is_bad_json(self):
        c = FakeCompletions(answer('{"reply": 3, "trade": "none"}'), answer('{"reply": "x"}'))
        with self.assertRaises(ProviderError) as e:
            provider(c).complete(request())
        self.assertEqual(e.exception.code, "bad_json")

    def test_invalid_json_and_empty_content_retry(self):
        c = FakeCompletions(answer("not json"), answer('{"reply": "ok", "trade": "none"}'))
        self.assertEqual(provider(c).complete(request()).json["reply"], "ok")
        self.assertIn("not valid JSON", c.calls[1]["messages"][-1]["content"])
        # 빈 응답 (공식 문서: JSON 모드에서 가끔) 은 같은 요청을 한 번 더
        c = FakeCompletions(answer(""), answer('{"reply": "ok", "trade": "none"}'))
        self.assertEqual(provider(c).complete(request()).json["reply"], "ok")
        self.assertEqual(len(c.calls[1]["messages"]), 4)

    def test_truncated_is_incomplete_without_retry(self):
        c = FakeCompletions(answer('{"reply": "Su', "length"))
        with self.assertRaises(ProviderError) as e:
            provider(c).complete(request())
        self.assertEqual(e.exception.code, "incomplete")
        self.assertEqual(len(c.calls), 1)

    def test_finish_reasons(self):
        for finish, code in (("content_filter", "refusal"), ("insufficient_system_resource", "server_error")):
            with self.assertRaises(ProviderError) as e:
                provider(FakeCompletions(answer("", finish))).complete(request())
            self.assertEqual(e.exception.code, code)

    def test_error_mapping(self):
        for err, code in ((status_error(openai.AuthenticationError, 401), "auth"),
                          (status_error(openai.RateLimitError, 429), "rate_limited"),
                          (status_error(openai.BadRequestError, 400), "bad_request"),
                          (status_error(openai.APIStatusError, 402), "no_balance"),
                          (status_error(openai.InternalServerError, 503), "server_error")):
            with self.assertRaises(ProviderError) as e:
                provider(FakeCompletions(error=err)).complete(request())
            self.assertEqual(e.exception.code, code)

    def test_missing_key(self):
        saved = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            with self.assertRaises(ProviderError) as e:
                create_provider("deepseek", {})
            self.assertEqual(e.exception.code, "auth")
        finally:
            if saved is not None:
                os.environ["DEEPSEEK_API_KEY"] = saved

    def test_check_schema(self):
        schema = {"type": "object", "required": ["lines"], "properties": {
            "lines": {"type": "array", "minItems": 1, "maxItems": 2,
                      "items": {"type": "object", "properties": {"n": {"type": "integer"}}}}}}
        self.assertIsNone(check_schema(schema, {"lines": [{"n": 1}]}))
        self.assertIn("at least", check_schema(schema, {"lines": []}))
        self.assertIn("at most", check_schema(schema, {"lines": [{}, {}, {}]}))
        self.assertIn("integer", check_schema(schema, {"lines": [{"n": True}]}))


if __name__ == "__main__":
    unittest.main()
