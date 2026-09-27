"""Anthropic Claude 제공자 (공식 anthropic Python SDK)."""

from __future__ import annotations

import json

import anthropic

from . import LLMResult, ProviderError

# 거절(refusal) 시 서버 측에서 다른 모델로 다시 실행해 주는 fallbacks 를 켤 모델.
# "default" 모드는 거절 사유별로 Anthropic 권장 모델을 고른다.
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    def __init__(self, cfg: dict):
        # 키를 지정하지 않으면 SDK 가 ANTHROPIC_API_KEY 환경 변수 등에서 찾는다.
        kwargs = {
            "timeout": float(cfg.get("timeout_seconds", 40.0)),
            "max_retries": int(cfg.get("max_retries", 1)),
        }
        if cfg.get("api_key"):
            kwargs["api_key"] = cfg["api_key"]
        self.client = anthropic.Anthropic(**kwargs)
        self.use_fallbacks = bool(cfg.get("refusal_fallback", True))

    def complete(self, req) -> LLMResult:
        params: dict = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": req.messages,
        }
        output_config: dict = {}
        if req.effort:
            output_config["effort"] = req.effort
        if req.json_schema:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        if output_config:
            params["output_config"] = output_config

        try:
            if self.use_fallbacks and req.model in FALLBACK_MODELS:
                response = self.client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **params
                )
            else:
                response = self.client.messages.create(**params)
        except anthropic.APITimeoutError as e:
            raise ProviderError("timeout", str(e)) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("network", str(e)) from e
        except anthropic.AuthenticationError as e:
            raise ProviderError("auth", "API 키를 확인하세요") from e
        except anthropic.PermissionDeniedError as e:
            raise ProviderError("permission", e.message) from e
        except anthropic.NotFoundError as e:
            raise ProviderError("bad_model", e.message) from e
        except anthropic.RateLimitError as e:
            raise ProviderError("rate_limited", e.message) from e
        except anthropic.BadRequestError as e:
            raise ProviderError("bad_request", e.message) from e
        except anthropic.APIStatusError as e:
            code = "server_error" if e.status_code >= 500 else f"api_{e.status_code}"
            raise ProviderError(code, e.message) from e

        if response.stop_reason == "refusal":
            raise ProviderError("refusal")

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        data = None
        if req.json_schema:
            try:
                data = json.loads(text)
            except ValueError as e:
                raise ProviderError("bad_json", str(e)) from e
        return LLMResult(text=text, model=response.model, json=data)
