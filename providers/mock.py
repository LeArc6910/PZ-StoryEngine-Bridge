"""API 호출 없이 고정 응답을 돌려주는 제공자. 파이프라인 검증과 테스트용.

JSON 스키마가 있는 요청(디렉터)에는 스키마를 만족하는 값을 무작위로 만들어 돌려준다.
enum 은 무작위로 고르므로 mock 으로도 여러 이벤트 경로를 시험할 수 있다.
"""

from __future__ import annotations

import json
import random
import time

from . import LLMResult


def sample(schema: dict, rng: random.Random):
    if "enum" in schema:
        return rng.choice(schema["enum"])
    kind = schema.get("type")
    if kind == "object":
        return {k: sample(v, rng) for k, v in schema.get("properties", {}).items()}
    if kind == "array":
        return [sample(schema.get("items", {}), rng)]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.0
    if kind == "boolean":
        return False
    return "mock"


class MockProvider:
    def __init__(self, cfg: dict):
        self.delay = float(cfg.get("delay_seconds", 0.0))
        self.rng = random.Random(cfg.get("seed"))

    def complete(self, req) -> LLMResult:
        if self.delay:
            time.sleep(self.delay)
        if req.extra.get("mock") is not None:
            # 모듈이 준비한 그럴듯한 mock 응답 (독백처럼 "mock" 한 단어로는 확인이 어려운 경우)
            data = req.extra["mock"]
            return LLMResult(text=json.dumps(data, ensure_ascii=False), model="mock", json=data)
        if req.json_schema:
            data = sample(req.json_schema, self.rng)
            return LLMResult(text=json.dumps(data, ensure_ascii=False), model="mock", json=data)
        last = req.messages[-1]["content"] if req.messages else ""
        return LLMResult(text=f"[mock] 수신 확인: {last}", model="mock")
