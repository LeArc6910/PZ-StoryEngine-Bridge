"""Google Gemini 제공자 (공식 google-genai Python SDK, generateContent).

OpenAI 호환 주소가 아니라 Gemini API 를 직접 부른다. JSON 출력은 response_json_schema(표준 JSON Schema),
사고량은 thinking_config.thinking_level(MINIMAL/LOW/MEDIUM/HIGH)로 조절한다.
max_output_tokens 에는 생각하는 데 쓰는 토큰도 들어가므로 넉넉히 둔다.
"""

from __future__ import annotations

import json

from google import genai
from google.genai import errors, types

from . import LLMResult, ProviderError

# 브릿지 effort(anthropic/openai 와 같은 값) -> Gemini thinking_level
EFFORT_LEVELS = {
    "none": "MINIMAL", "minimal": "MINIMAL", "low": "LOW", "medium": "MEDIUM",
    "high": "HIGH", "xhigh": "HIGH", "max": "HIGH",
}
# 안전 정책으로 막힌 응답
BLOCKED = {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "RECITATION"}


class GeminiProvider:
    def __init__(self, cfg: dict):
        # 키를 지정하지 않으면 SDK 가 GEMINI_API_KEY (또는 GOOGLE_API_KEY) 환경 변수를 쓴다.
        http = types.HttpOptions(
            timeout=int(float(cfg.get("timeout_seconds", 40.0)) * 1000),   # 밀리초
            retry_options=types.HttpRetryOptions(attempts=max(1, int(cfg.get("max_retries", 1)) + 1)),
        )
        kwargs: dict = {"http_options": http}
        if cfg.get("api_key"):
            kwargs["api_key"] = cfg["api_key"]
        try:
            self.client = genai.Client(**kwargs)
        except ValueError as e:      # 키가 어디에도 없을 때
            raise ProviderError("auth", "GEMINI_API_KEY 환경 변수나 config.toml 의 api_key 를 확인하세요") from e
        # thinking = false 면 사고량 설정을 보내지 않는다 (thinking_level 을 받지 않는 모델용)
        self.use_thinking = bool(cfg.get("thinking", True))

    def config_for(self, req) -> types.GenerateContentConfig:
        # 도구를 쓰지 않으므로 자동 함수 호출(AFC)은 끈다 (켜 두면 매 요청 로그에 안내가 찍힌다)
        params: dict = {"system_instruction": req.system, "max_output_tokens": req.max_tokens,
                        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True)}
        level = EFFORT_LEVELS.get(str(req.effort or "").lower())
        if level and self.use_thinking:
            params["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        if req.json_schema:
            params["response_mime_type"] = "application/json"
            params["response_json_schema"] = req.json_schema
        return types.GenerateContentConfig(**params)

    @staticmethod
    def contents_for(req) -> list:
        out = []
        for m in req.messages:
            role = "model" if m["role"] == "assistant" else "user"
            out.append(types.Content(role=role, parts=[types.Part(text=str(m["content"]))]))
        return out

    def complete(self, req) -> LLMResult:
        try:
            response = self.client.models.generate_content(
                model=req.model, contents=self.contents_for(req), config=self.config_for(req))
        except errors.APIError as e:
            code = getattr(e, "code", 0) or 0
            message = getattr(e, "message", None) or str(e)
            # 틀린 키는 400 "API key not valid" 로 온다
            if code in (400, 401, 403) and "api key" in message.lower():
                raise ProviderError("auth", "API 키를 확인하세요") from e
            if code == 403:
                raise ProviderError("permission", message) from e
            if code == 404:
                raise ProviderError("bad_model", message) from e
            if code == 429:
                raise ProviderError("rate_limited", message) from e
            if code == 400:
                raise ProviderError("bad_request", message) from e
            if code in (408, 504):
                raise ProviderError("timeout", message) from e
            raise ProviderError("server_error" if code >= 500 else f"api_{code}", message) from e
        except Exception as e:  # httpx 시간 초과·연결 실패 등 SDK 밖의 오류
            name = type(e).__name__.lower()
            if "timeout" in name:
                raise ProviderError("timeout", str(e)) from e
            raise ProviderError("network", f"{type(e).__name__}: {e}") from e

        feedback = getattr(response, "prompt_feedback", None)
        if feedback is not None and getattr(feedback, "block_reason", None):
            raise ProviderError("refusal", str(feedback.block_reason))
        candidate = (response.candidates or [None])[0]
        finish = getattr(getattr(candidate, "finish_reason", None), "name", "") if candidate else ""

        try:
            text = (response.text or "").strip()
        except ValueError:
            text = ""
        if finish in BLOCKED and not text:
            raise ProviderError("refusal", finish)
        if not text:
            raise ProviderError("incomplete", finish or "empty")

        data = None
        if req.json_schema:
            try:
                data = json.loads(text)
            except ValueError as e:
                # 생각에 토큰을 다 써서 JSON 이 잘렸을 때
                raise ProviderError("incomplete" if finish == "MAX_TOKENS" else "bad_json", str(e)) from e
        return LLMResult(text=text, model=getattr(response, "model_version", None) or req.model, json=data)
