"""DeepSeek 제공자 (OpenAI 호환 Chat Completions, 공식 문서가 권하는 openai SDK + base_url).

DeepSeek 는 전용 Python SDK 가 없고 OpenAI 형식(https://api.deepseek.com)을 쓴다.
JSON 출력은 response_format = json_object (스키마 강제 없음)만 지원하므로, 스키마를 시스템 프롬프트에 넣고
받은 JSON 을 여기서 스키마로 검사한다. 어긋나거나 빈 응답이면 한 번 다시 묻는다
(공식 문서: JSON 모드에서 가끔 빈 내용이 올 수 있음).
사고량: thinking {"type": enabled|disabled} + reasoning_effort (none/low/high/max).
"""

from __future__ import annotations

import json

import openai

from . import LLMResult, ProviderError

BASE_URL = "https://api.deepseek.com"
# 브릿지 effort -> DeepSeek reasoning_effort (none 은 사고를 끈다)
EFFORT_LEVELS = {"low": "low", "medium": "high", "high": "high", "xhigh": "max", "max": "max"}


def check_schema(schema: dict, value, path: str = "$") -> str | None:
    """JSON Schema 일부(type·properties·required·additionalProperties·items·enum·minItems·maxItems)로 검사.
    맞으면 None, 아니면 첫 오류 설명."""
    if not isinstance(schema, dict):
        return None
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return f"{path} must be one of {schema['enum']}"
    if kind == "object":
        if not isinstance(value, dict):
            return f"{path} must be an object"
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                return f"{path}.{key} is missing"
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    return f"{path}.{key} is not allowed"
        for key, sub in props.items():
            if key in value:
                err = check_schema(sub, value[key], f"{path}.{key}")
                if err:
                    return err
    elif kind == "array":
        if not isinstance(value, list):
            return f"{path} must be an array"
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path} needs at least {schema['minItems']} items"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path} allows at most {schema['maxItems']} items"
        for i, item in enumerate(value):
            err = check_schema(schema.get("items", {}), item, f"{path}[{i}]")
            if err:
                return err
    elif kind == "string" and not isinstance(value, str):
        return f"{path} must be a string"
    elif kind == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return f"{path} must be an integer"
    elif kind == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return f"{path} must be a number"
    elif kind == "boolean" and not isinstance(value, bool):
        return f"{path} must be true or false"
    return None


class DeepSeekProvider:
    def __init__(self, cfg: dict):
        # 키를 지정하지 않으면 DEEPSEEK_API_KEY 환경 변수를 쓴다 (openai SDK 의 OPENAI_API_KEY 가 아니라).
        import os
        key = cfg.get("api_key") or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise ProviderError("auth", "DEEPSEEK_API_KEY 환경 변수나 config.toml 의 api_key 를 확인하세요")
        self.client = openai.OpenAI(
            api_key=key,
            base_url=str(cfg.get("base_url") or BASE_URL),
            timeout=float(cfg.get("timeout_seconds", 60.0)),
            max_retries=int(cfg.get("max_retries", 1)),
        )
        # thinking = false 면 effort 와 상관없이 사고를 끈다 (빠르고 싸게)
        self.use_thinking = bool(cfg.get("thinking", True))

    def params_for(self, req, messages: list[dict]) -> dict:
        params: dict = {"model": req.model, "messages": messages, "max_tokens": req.max_tokens}
        extra: dict = {}
        effort = str(req.effort or "").lower()
        if not self.use_thinking or effort in ("none", "minimal"):
            extra["thinking"] = {"type": "disabled"}
        elif effort in EFFORT_LEVELS:
            extra["thinking"] = {"type": "enabled"}
            extra["reasoning_effort"] = EFFORT_LEVELS[effort]
        if req.json_schema:
            params["response_format"] = {"type": "json_object"}
        if extra:
            params["extra_body"] = extra
        return params

    @staticmethod
    def base_messages(req) -> list[dict]:
        system = req.system
        if req.json_schema:
            # JSON 모드는 프롬프트에 'json' 이라는 말과 형식이 있어야 한다 (공식 문서)
            system = (f"{system}\n\nReply with a single JSON object (json) that matches this JSON Schema exactly. "
                      f"No text outside the JSON.\n{json.dumps(req.json_schema, ensure_ascii=False)}")
        return [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in req.messages]

    def call(self, params: dict):
        try:
            return self.client.chat.completions.create(**params)
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
            # 402 = 잔액 부족 (DeepSeek)
            code = "server_error" if e.status_code >= 500 else ("no_balance" if e.status_code == 402 else f"api_{e.status_code}")
            raise ProviderError(code, e.message) from e

    def complete(self, req) -> LLMResult:
        messages = self.base_messages(req)
        last_error = None
        for attempt in range(2 if req.json_schema else 1):
            response = self.call(self.params_for(req, messages))
            choice = (response.choices or [None])[0]
            finish = getattr(choice, "finish_reason", None) if choice else None
            text = ((choice.message.content if choice and choice.message else None) or "").strip()
            if finish == "content_filter":
                raise ProviderError("refusal", "content_filter")
            if finish == "insufficient_system_resource":
                raise ProviderError("server_error", finish)
            model = getattr(response, "model", None) or req.model
            if not req.json_schema:
                if not text:
                    raise ProviderError("incomplete", str(finish or "empty"))
                return LLMResult(text=text, model=model, json=None)
            if not text:
                last_error = ProviderError("incomplete", str(finish or "empty"))
                if finish == "length":
                    raise last_error         # 토큰이 모자라면 다시 물어도 같다
                continue
            try:
                data = json.loads(text)
            except ValueError as e:
                last_error = ProviderError("incomplete" if finish == "length" else "bad_json", str(e))
                if finish == "length":
                    raise last_error from e
                messages = messages + [{"role": "assistant", "content": text},
                                       {"role": "user", "content": "That was not valid JSON. Reply again with only the "
                                                                   "corrected JSON object."}]
                continue
            err = check_schema(req.json_schema, data)
            if err is None:
                return LLMResult(text=text, model=model, json=data)
            last_error = ProviderError("bad_json", err)
            messages = messages + [{"role": "assistant", "content": text},
                                   {"role": "user", "content": f"That JSON does not match the schema ({err}). Reply "
                                                               "again with only the corrected JSON object."}]
        raise last_error or ProviderError("bad_json", "no valid JSON")
