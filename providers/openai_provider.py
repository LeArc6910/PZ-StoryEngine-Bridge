"""OpenAI 제공자 (공식 openai Python SDK, Responses API).

gpt-6-luna 등 추론 모델은 reasoning.effort 로 사고량을 조절한다 (none/low/medium/high/xhigh/max).
"""

from __future__ import annotations

import json

import openai

from . import LLMResult, ProviderError


class OpenAIProvider:
    def __init__(self, cfg: dict):
        # 키를 지정하지 않으면 SDK 가 OPENAI_API_KEY 환경 변수를 쓴다.
        kwargs = {
            "timeout": float(cfg.get("timeout_seconds", 40.0)),
            "max_retries": int(cfg.get("max_retries", 1)),
        }
        if cfg.get("api_key"):
            kwargs["api_key"] = cfg["api_key"]
        self.client = openai.OpenAI(**kwargs)

    def complete(self, req) -> LLMResult:
        # 대화 이력이 없는 단발 요청이므로 사용자 메시지만 input 으로 넘긴다.
        params: dict = {
            "model": req.model,
            "instructions": req.system,
            "input": [{"role": m["role"], "content": m["content"]} for m in req.messages],
            "max_output_tokens": req.max_tokens,
            "store": False,
        }
        if req.effort:
            params["reasoning"] = {"effort": req.effort}
        if req.json_schema:
            params["text"] = {"format": {
                "type": "json_schema", "name": f"{req.module}_output",
                "schema": req.json_schema, "strict": True,
            }}

        try:
            response = self.client.responses.create(**params)
        except openai.APITimeoutError as e:
            raise ProviderError("timeout", str(e)) from e
        except openai.APIConnectionError as e:
            raise ProviderError("network", str(e)) from e
        except openai.AuthenticationError as e:
            raise ProviderError("auth", "API 키를 확인하세요") from e
        except openai.PermissionDeniedError as e:
            raise ProviderError("permission", e.message) from e
        except openai.NotFoundError as e:
            raise ProviderError("bad_model", e.message) from e
        except openai.RateLimitError as e:
            raise ProviderError("rate_limited", e.message) from e
        except openai.BadRequestError as e:
            raise ProviderError("bad_request", e.message) from e
        except openai.APIStatusError as e:
            code = "server_error" if e.status_code >= 500 else f"api_{e.status_code}"
            raise ProviderError(code, e.message) from e

        for item in response.output or []:
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderError("refusal", part.refusal)

        text = (response.output_text or "").strip()
        if response.status == "incomplete":
            reason = response.incomplete_details.reason if response.incomplete_details else None
            if reason == "content_filter":
                raise ProviderError("refusal", "content_filter")
            if not text:
                raise ProviderError("incomplete", str(reason))

        data = None
        if req.json_schema:
            try:
                data = json.loads(text)
            except ValueError as e:
                raise ProviderError("bad_json", str(e)) from e
        return LLMResult(text=text, model=response.model, json=data)
