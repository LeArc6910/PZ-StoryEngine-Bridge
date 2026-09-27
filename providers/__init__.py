"""LLM 제공자. 모든 제공자는 complete(LLMRequest) -> LLMResult 를 구현한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ProviderError(Exception):
    """게임에 그대로 전달되는 오류. code 는 짧은 영문 식별자."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass
class LLMResult:
    text: str
    model: str
    json: Any = None


def create_provider(name: str, cfg: dict):
    if name == "mock":
        from .mock import MockProvider
        return MockProvider(cfg)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(cfg)
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(cfg)
    raise ProviderError("unknown_provider", name)
