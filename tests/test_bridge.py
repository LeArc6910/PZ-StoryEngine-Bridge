"""브릿지 프로토콜 테스트. 실행: python -m unittest discover -s bridge/tests"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bridge as bridge_mod  # noqa: E402
from modules import LLMRequest  # noqa: E402
from providers import LLMResult, ProviderError  # noqa: E402


def make_bridge(tmp: Path, **overrides) -> bridge_mod.Bridge:
    cfg = bridge_mod.deep_merge(bridge_mod.DEFAULT_CONFIG, overrides)
    b = bridge_mod.Bridge(cfg, tmp, inline=True)
    b.prepare()
    return b


def write_request(tmp: Path, rid: str, module: str = "debug", payload=None, priority: int = 0, age: float = 0.0):
    # 게임(Lua Json.encode)이 쓰는 형태와 같게 공백 없는 한 줄 JSON
    body = {"v": 1, "id": rid, "module": module, "priority": priority, "payload": payload or {"text": "들리나?"}}
    path = tmp / "requests" / f"{rid}.json"
    path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


def read_response(tmp: Path, rid: str) -> dict:
    return json.loads((tmp / "responses" / f"{rid}.json").read_text(encoding="utf-8"))


class BridgeProtocolTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_round_trip_with_mock(self):
        b = make_bridge(self.tmp)
        req_path = write_request(self.tmp, "debug-1-1")
        b.tick()

        self.assertFalse(req_path.exists(), "브릿지는 처리한 요청 파일을 지워야 한다")
        res = read_response(self.tmp, "debug-1-1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["id"], "debug-1-1")
        self.assertIn("들리나?", res["text"])
        self.assertEqual(res["model"], "mock")
        hb = json.loads((self.tmp / "heartbeat.json").read_text(encoding="utf-8"))
        self.assertEqual(hb["seq"], 1)

    def test_response_is_utf8_without_escapes(self):
        # Lua 디코더 부담을 줄이려고 한글을 \\u 이스케이프 없이 쓴다.
        b = make_bridge(self.tmp)
        write_request(self.tmp, "debug-1-2")
        b.tick()
        raw = (self.tmp / "responses" / "debug-1-2.json").read_text(encoding="utf-8")
        self.assertIn("들리나?", raw)
        self.assertNotIn("\\u", raw)

    def test_partial_file_waits_then_errors(self):
        b = make_bridge(self.tmp)
        path = self.tmp / "requests" / "debug-1-3.json"
        path.write_text('{"v":1,"id":"debug-1-3","modu', encoding="utf-8")
        b.tick()
        self.assertTrue(path.exists(), "쓰는 중일 수 있는 파일은 유예 시간 동안 건드리지 않는다")

        old = time.time() - 60
        os.utime(path, (old, old))
        b.tick()
        self.assertFalse(path.exists())
        self.assertEqual(read_response(self.tmp, "debug-1-3")["error"], "bad_request")

    def test_unknown_module(self):
        b = make_bridge(self.tmp)
        write_request(self.tmp, "weather-1-1", module="weather")
        b.tick()
        self.assertEqual(read_response(self.tmp, "weather-1-1")["error"], "unknown_module")

    def test_id_mismatch_rejected(self):
        b = make_bridge(self.tmp)
        path = self.tmp / "requests" / "debug-1-4.json"
        path.write_text(json.dumps({"id": "other", "module": "debug", "payload": {"text": "x"}}), encoding="utf-8")
        b.tick()
        self.assertEqual(read_response(self.tmp, "debug-1-4")["error"], "bad_request")

    def test_empty_text_rejected(self):
        b = make_bridge(self.tmp)
        write_request(self.tmp, "debug-1-5", payload={"text": "   "})
        b.tick()
        self.assertEqual(read_response(self.tmp, "debug-1-5")["error"], "empty_text")

    def test_rate_limit(self):
        b = make_bridge(self.tmp, limits={"requests_per_hour": 1})
        write_request(self.tmp, "debug-1-6")
        write_request(self.tmp, "debug-1-7")
        b.tick()
        results = sorted(read_response(self.tmp, r).get("error", "ok") for r in ("debug-1-6", "debug-1-7"))
        self.assertEqual(results, ["ok", "rate_limited"])

    def test_old_request_ignored(self):
        b = make_bridge(self.tmp)
        path = write_request(self.tmp, "debug-1-8", age=600)
        b.tick()
        self.assertFalse(path.exists())
        self.assertFalse((self.tmp / "responses" / "debug-1-8.json").exists())

    def test_consumed_response_is_cleaned(self):
        b = make_bridge(self.tmp)
        write_request(self.tmp, "debug-1-9")
        b.tick()
        resp = self.tmp / "responses" / "debug-1-9.json"
        resp.write_text("", encoding="utf-8")   # 게임이 읽고 비움
        b.tick()
        self.assertFalse(resp.exists())

    def test_priority_order(self):
        b = make_bridge(self.tmp, modules={"monologue": {"provider": "mock"}, "director": {"provider": "mock"}})
        order: list[str] = []

        class Recorder:
            def complete(self, req: LLMRequest) -> LLMResult:
                order.append(req.messages[-1]["content"])
                return LLMResult(text="ok", model="rec")

        b.providers["mock"] = Recorder()
        import modules
        saved = dict(modules.BUILDERS)
        modules.BUILDERS["monologue"] = modules.BUILDERS["debug"]
        modules.BUILDERS["director"] = modules.BUILDERS["debug"]
        try:
            write_request(self.tmp, "monologue-1-1", module="monologue", priority=3, payload={"text": "mono"})
            write_request(self.tmp, "director-1-1", module="director", priority=0, payload={"text": "dir"})
            b.tick()
        finally:
            modules.BUILDERS.clear()
            modules.BUILDERS.update(saved)
        self.assertEqual(order, ["dir", "mono"])

    def test_provider_error_code_passed_to_game(self):
        b = make_bridge(self.tmp)

        class Failing:
            def complete(self, req):
                raise ProviderError("auth", "bad key")

        b.providers["mock"] = Failing()
        write_request(self.tmp, "debug-1-10")
        b.tick()
        self.assertEqual(read_response(self.tmp, "debug-1-10"), {"v": 1, "id": "debug-1-10", "ok": False, "error": "auth"})

    def test_prepare_clears_previous_session_responses(self):
        (self.tmp / "responses").mkdir(parents=True)
        leftover = self.tmp / "responses" / "debug-0-1.json"
        leftover.write_text("{}", encoding="utf-8")
        make_bridge(self.tmp)
        self.assertFalse(leftover.exists())


class FakeAnthropicTest(unittest.TestCase):
    """anthropic 패키지 없이 요청 구성과 오류 매핑을 확인한다."""

    def setUp(self):
        fake = types.ModuleType("anthropic")

        class APIError(Exception):
            def __init__(self, message="err", status_code=500):
                super().__init__(message)
                self.message = message
                self.status_code = status_code

        for name in ["APIConnectionError", "APIStatusError"]:
            setattr(fake, name, type(name, (APIError,), {}))
        fake.APITimeoutError = type("APITimeoutError", (fake.APIConnectionError,), {})
        for name in ["AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError", "BadRequestError"]:
            setattr(fake, name, type(name, (fake.APIStatusError,), {}))

        calls = self.calls = []
        response = self.response = types.SimpleNamespace(
            stop_reason="end_turn",
            model="claude-opus-5",
            content=[types.SimpleNamespace(type="text", text='{"event":"quiet_day"}')],
        )
        self.raise_exc = None
        test = self

        class Messages:
            def __init__(self, beta):
                self.beta = beta

            def create(self, **kw):
                calls.append((self.beta, kw))
                if test.raise_exc:
                    raise test.raise_exc
                return response

        class Anthropic:
            def __init__(self, **kw):
                self.init = kw
                self.messages = Messages(False)
                self.beta = types.SimpleNamespace(messages=Messages(True))

        fake.Anthropic = Anthropic
        self.fake = fake
        sys.modules["anthropic"] = fake
        sys.modules.pop("providers.anthropic_provider", None)
        from providers.anthropic_provider import AnthropicProvider
        self.Provider = AnthropicProvider

    def tearDown(self):
        sys.modules.pop("anthropic", None)
        sys.modules.pop("providers.anthropic_provider", None)

    def req(self, model="claude-opus-5", schema=None):
        return LLMRequest(module="director", model=model, system="sys",
                          messages=[{"role": "user", "content": "hi"}], max_tokens=100, json_schema=schema)

    def test_opus5_uses_default_fallbacks(self):
        self.Provider({}).complete(self.req())
        beta, kw = self.calls[0]
        self.assertTrue(beta)
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])

    def test_haiku_uses_plain_endpoint(self):
        self.Provider({}).complete(self.req(model="claude-haiku-4-5"))
        beta, kw = self.calls[0]
        self.assertFalse(beta)
        self.assertNotIn("fallbacks", kw)

    def test_json_schema_parsed(self):
        schema = {"type": "object", "properties": {"event": {"type": "string"}}, "required": ["event"], "additionalProperties": False}
        result = self.Provider({}).complete(self.req(schema=schema))
        self.assertEqual(result.json, {"event": "quiet_day"})
        self.assertEqual(self.calls[0][1]["output_config"]["format"]["type"], "json_schema")

    def test_refusal_becomes_error(self):
        self.response.stop_reason = "refusal"
        with self.assertRaises(ProviderError) as cm:
            self.Provider({}).complete(self.req())
        self.assertEqual(cm.exception.code, "refusal")

    def test_error_mapping(self):
        cases = [
            (self.fake.APITimeoutError("t"), "timeout"),
            (self.fake.APIConnectionError("c"), "network"),
            (self.fake.AuthenticationError("a", 401), "auth"),
            (self.fake.RateLimitError("r", 429), "rate_limited"),
            (self.fake.APIStatusError("s", 529), "server_error"),
        ]
        for exc, code in cases:
            self.raise_exc = exc
            with self.assertRaises(ProviderError) as cm:
                self.Provider({}).complete(self.req())
            self.assertEqual(cm.exception.code, code, type(exc).__name__)


if __name__ == "__main__":
    unittest.main()
