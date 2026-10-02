"""Gemini 제공자: 요청 구성(사고량·JSON 스키마·역할)과 응답·오류 처리. 실제 API 는 부르지 않는다."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import errors, types  # noqa: E402

from modules import LLMRequest  # noqa: E402
from providers import ProviderError, create_provider  # noqa: E402

SCHEMA = {"type": "object", "properties": {"reply": {"type": "string"}}, "required": ["reply"],
          "additionalProperties": False}


def request(effort="low", schema=SCHEMA):
    return LLMRequest(module="radio", model="gemini-3.8-flash", system="You are Ray.",
                      messages=[{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"},
                                {"role": "user", "content": "trade?"}],
                      max_tokens=4000, effort=effort, json_schema=schema)


class FakeModels:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def answer(text, finish="STOP", blocked=None):
    return SimpleNamespace(
        text=text, model_version="gemini-3.8-flash-001",
        candidates=[SimpleNamespace(finish_reason=types.FinishReason[finish])],
        prompt_feedback=SimpleNamespace(block_reason=blocked) if blocked else None)


def provider(models, **cfg):
    p = create_provider("gemini", {"api_key": "test-key", **cfg})
    p.client = SimpleNamespace(models=models)
    return p


class GeminiProviderTest(unittest.TestCase):
    def test_request_shape(self):
        models = FakeModels(answer('{"reply": "Sure."}'))
        res = provider(models).complete(request("xhigh"))
        call = models.calls[0]
        cfg = call["config"]
        self.assertEqual(call["model"], "gemini-3.8-flash")
        self.assertEqual([c.role for c in call["contents"]], ["user", "model", "user"])
        self.assertEqual(cfg.system_instruction, "You are Ray.")
        self.assertEqual(cfg.max_output_tokens, 4000)
        self.assertEqual(cfg.response_mime_type, "application/json")
        self.assertEqual(cfg.response_json_schema, SCHEMA)
        self.assertEqual(cfg.thinking_config.thinking_level, types.ThinkingLevel.HIGH)
        self.assertEqual(res.json, {"reply": "Sure."})
        self.assertEqual(res.model, "gemini-3.8-flash-001")

    def test_effort_mapping_and_thinking_off(self):
        p = provider(FakeModels())
        self.assertEqual(p.config_for(request("none")).thinking_config.thinking_level, types.ThinkingLevel.MINIMAL)
        self.assertIsNone(p.config_for(request(None)).thinking_config)
        off = provider(FakeModels(), thinking=False)
        self.assertIsNone(off.config_for(request("high")).thinking_config)
        self.assertIsNone(p.config_for(request("low", schema=None)).response_mime_type)

    def test_blocked_and_truncated(self):
        with self.assertRaises(ProviderError) as e:
            provider(FakeModels(answer("", blocked="SAFETY"))).complete(request())
        self.assertEqual(e.exception.code, "refusal")
        with self.assertRaises(ProviderError) as e:
            provider(FakeModels(answer('{"reply": "Su', finish="MAX_TOKENS"))).complete(request())
        self.assertEqual(e.exception.code, "incomplete")
        with self.assertRaises(ProviderError) as e:
            provider(FakeModels(answer("not json"))).complete(request())
        self.assertEqual(e.exception.code, "bad_json")

    def test_api_errors(self):
        cases = {429: "rate_limited", 404: "bad_model", 400: "bad_request", 503: "server_error"}
        for status, code in cases.items():
            err = errors.APIError(status, {"error": {"code": status, "message": "x", "status": "X"}})
            with self.assertRaises(ProviderError) as e:
                provider(FakeModels(error=err)).complete(request())
            self.assertEqual(e.exception.code, code, status)
        with self.assertRaises(ProviderError) as e:
            provider(FakeModels(error=ConnectionError("down"))).complete(request())
        self.assertEqual(e.exception.code, "network")


if __name__ == "__main__":
    unittest.main()
