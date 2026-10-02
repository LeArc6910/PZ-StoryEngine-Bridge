"""처음 실행할 때 config.toml 을 만드는 설정 마법사 (배포판용).

API 키는 이 PC 의 config.toml 에만 저장되고 다른 곳으로 보내지 않는다. 비워 두면 환경 변수
(OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY)를 쓴다.
"""

from __future__ import annotations

import getpass
from pathlib import Path

PROVIDERS = {
    "1": ("openai", "OpenAI", "gpt-6-luna", "OPENAI_API_KEY"),
    "2": ("anthropic", "Anthropic (Claude)", "claude-haiku-4-5", "ANTHROPIC_API_KEY"),
    "3": ("gemini", "Google Gemini", "gemini-3.8-flash", "GEMINI_API_KEY"),
    "4": ("mock", "Test mode (no AI, no cost) / 테스트 모드 (AI 없음, 비용 없음)", "mock", ""),
}
MODULES = ("debug", "journal", "director", "radio", "monologue", "summary")


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_config(provider: str, model: str, api_key: str, data_dir: str) -> str:
    lines = [
        "# StoryEngine bridge settings. Created by the setup wizard; run StoryEngineBridge --setup to redo it.",
        "# StoryEngine 브릿지 설정. 설정 마법사가 만든 파일이며, StoryEngineBridge --setup 으로 다시 만들 수 있다.",
        "# Keep this file private: it contains your API key. / API 키가 들어 있으니 다른 사람과 공유하지 말 것.",
        "",
        "[bridge]",
        f"data_dir = {_toml_str(data_dir)}",
        "poll_interval = 0.25",
        "heartbeat_interval = 2.0",
        "max_workers = 2",
        "",
        "[limits]",
        "requests_per_hour = 120     # safety cap / 시간당 호출 상한 (비용 보호)",
        "",
    ]
    if provider != "mock":
        lines += [f"[providers.{provider}]", f"api_key = {_toml_str(api_key)}", "timeout_seconds = 60",
                  "max_retries = 1", ""]
    for module in MODULES:
        lines += [f"[modules.{module}]", f"provider = {_toml_str(provider)}", f"model = {_toml_str(model)}"]
        if module in ("debug", "monologue", "summary"):
            lines += ["max_tokens = 3000", 'effort = "low"']
        else:
            lines += ["max_tokens = 16000"]
        lines.append("")
    return "\n".join(lines)


def _ask(prompt: str, default: str = "") -> str:
    try:
        answer = input(prompt).strip()
    except EOFError:
        return default
    return answer or default


def run_setup(config_path: Path, default_data_dir: Path) -> bool:
    """대화형 설정. 저장했으면 True."""
    print()
    print("=" * 64)
    print(" StoryEngine bridge setup / 브릿지 설정")
    print("=" * 64)
    print("The bridge sends game events and radio messages to the AI service you choose,")
    print("using YOUR OWN API key. Usage is billed by that service to you.")
    print("브릿지는 게임 사건과 무전 대화를 선택한 AI 서비스로 보냅니다. 본인의 API 키를 쓰며,")
    print("사용 요금은 해당 서비스가 본인에게 청구합니다.")
    print()
    for key, (_, label, model, _) in PROVIDERS.items():
        print(f"  {key}) {label}" + (f"  [default model: {model}]" if model != "mock" else ""))
    choice = _ask(f"Choose 1-{len(PROVIDERS)} / 선택 (1-{len(PROVIDERS)}) [1]: ", "1")
    if choice not in PROVIDERS:
        print("Unknown choice. / 알 수 없는 선택입니다.")
        return False
    provider, label, model, env_name = PROVIDERS[choice]

    api_key = ""
    if provider != "mock":
        model = _ask(f"Model / 모델 [{model}]: ", model)
        print(f"Paste your {label} API key. It is not shown while typing and is saved only in {config_path.name}.")
        print(f"Leave it empty to use the {env_name} environment variable instead.")
        print(f"{label} API 키를 붙여 넣으세요. 입력 내용은 보이지 않고 {config_path.name} 에만 저장됩니다.")
        print(f"비워 두면 {env_name} 환경 변수를 씁니다.")
        try:
            api_key = getpass.getpass("API key: ").strip()
        except EOFError:
            api_key = ""

    print()
    print(f"Game data folder / 게임 데이터 폴더: {default_data_dir}")
    if not default_data_dir.parent.exists():
        print("  (Zomboid/Lua was not found. Run the game once, or type the folder of a dedicated server.)")
        print("  (Zomboid/Lua 폴더가 없습니다. 게임을 한 번 실행했는지 확인하거나 전용 서버의 폴더를 입력하세요.)")
    custom = _ask("Press Enter to keep it, or type another path / 그대로 쓰려면 Enter, 다른 경로는 입력: ", "")

    config_path.write_text(build_config(provider, model, api_key, custom), encoding="utf-8")
    print()
    print(f"Saved / 저장함: {config_path}")
    return True
