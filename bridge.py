"""StoryEngine 브릿지.

게임(서버 측 Lua)이 Zomboid/Lua/StoryEngine/requests/ 에 쓴 요청 파일을 읽어
LLM을 호출하고, responses/ 에 응답 파일을 쓴다. heartbeat.json 을 주기적으로 갱신해
게임이 연결 상태를 알 수 있게 한다.

프로토콜 제약 (B42 getFileWriter 기준):
- 게임은 .ini/.cfg/.txt/.log/.json 확장자만 쓸 수 있고, 파일 삭제는 못 한다.
- 그래서 요청 파일 삭제와 응답 파일 정리는 전부 브릿지가 맡는다.
- 게임은 응답을 읽은 뒤 그 파일을 빈 파일로 덮어써서 "읽음"을 표시한다.

사용법:
    python bridge.py                     # config.toml 사용
    python bridge.py --mock              # 모든 모듈을 mock 제공자로 (API 호출 없음)
    python bridge.py --data-dir <경로>   # Zomboid/Lua/StoryEngine 경로 직접 지정
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
import tomllib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

# 배포판(PyInstaller exe)에서는 설정 파일을 exe 옆에 둔다. 소스로 실행하면 이 파일 옆.
FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from modules import ModuleError, build_request  # noqa: E402
from providers import ProviderError, create_provider  # noqa: E402

PROTOCOL_VERSION = 1
BRIDGE_VERSION = "0.3.8"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")

log = logging.getLogger("bridge")

DEFAULT_CONFIG: dict[str, Any] = {
    "bridge": {
        "data_dir": "",
        "poll_interval": 0.25,
        "heartbeat_interval": 2.0,
        "max_workers": 2,
        "partial_grace_seconds": 5.0,
        "request_max_age_seconds": 120.0,
        "response_stale_seconds": 600.0,
    },
    "limits": {"requests_per_hour": 120},
    "providers": {},
    "modules": {"debug": {"provider": "mock"}, "journal": {"provider": "mock"}, "director": {"provider": "mock"},
                "radio": {"provider": "mock"}, "monologue": {"provider": "mock"}},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: Path | None) -> dict:
    cfg = DEFAULT_CONFIG
    if path and path.exists():
        with path.open("rb") as f:
            cfg = deep_merge(cfg, tomllib.load(f))
    elif path:
        log.warning("설정 파일 없음: %s (기본값 사용, 모든 모듈 mock)", path)
    return cfg


def default_data_dir() -> Path:
    return Path.home() / "Zomboid" / "Lua" / "StoryEngine"


def write_json_atomic(path: Path, obj: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


class RateLimiter:
    """시간당 호출 수 제한 (슬라이딩 윈도우)."""

    def __init__(self, per_hour: int, clock: Callable[[], float] = time.monotonic):
        self.per_hour = per_hour
        self.clock = clock
        self.calls: deque[float] = deque()

    def allow(self) -> bool:
        if self.per_hour <= 0:
            return True
        now = self.clock()
        while self.calls and now - self.calls[0] > 3600:
            self.calls.popleft()
        if len(self.calls) >= self.per_hour:
            return False
        self.calls.append(now)
        return True


class Bridge:
    def __init__(self, cfg: dict, data_dir: Path, force_mock: bool = False, inline: bool = False):
        self.cfg = cfg
        self.bcfg = cfg["bridge"]
        self.data_dir = data_dir
        self.requests_dir = data_dir / "requests"
        self.responses_dir = data_dir / "responses"
        self.heartbeat_path = data_dir / "heartbeat.json"
        self.force_mock = force_mock
        self.limiter = RateLimiter(int(cfg["limits"].get("requests_per_hour", 0)))
        self.providers: dict[str, Any] = {}
        self.in_flight: set[str] = set()
        self.seen: deque[str] = deque(maxlen=2000)
        self.heartbeat_seq = 0
        self.last_heartbeat = 0.0
        self.executor = None if inline else ThreadPoolExecutor(max_workers=int(self.bcfg["max_workers"]))

    # ---------- setup ----------

    def prepare(self) -> None:
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.responses_dir.mkdir(parents=True, exist_ok=True)
        # 이전 세션에서 남은 응답은 게임이 더 이상 기다리지 않으므로 지운다.
        for p in self.responses_dir.iterdir():
            self._unlink(p)

    def provider_for(self, name: str):
        if self.force_mock:
            name = "mock"
        if name not in self.providers:
            pcfg = self.cfg["providers"].get(name, {})
            self.providers[name] = create_provider(name, pcfg)
        return self.providers[name]

    # ---------- main loop ----------

    def run_forever(self) -> None:
        self.prepare()
        log.info("브릿지 시작: %s", self.data_dir)
        try:
            while True:
                self.tick()
                time.sleep(float(self.bcfg["poll_interval"]))
        except KeyboardInterrupt:
            log.info("종료")
        finally:
            if self.executor:
                self.executor.shutdown(wait=False, cancel_futures=True)

    def tick(self) -> None:
        now = time.time()
        if now - self.last_heartbeat >= float(self.bcfg["heartbeat_interval"]):
            self.write_heartbeat()
        self.scan_requests()
        self.clean_responses()

    def write_heartbeat(self) -> None:
        # os.replace 로 교체하면 그 순간 게임(Java)이 파일을 열다가 공유 위반이 나고, 게임이 콘솔에
        # SEVERE 스택 트레이스를 남긴다 (42.20.4 확인). 그래서 heartbeat 만은 제자리에 덮어쓴다.
        # 게임이 쓰다 만 내용을 읽으면 JSON 해석에 실패해 "정보 없음"으로 넘어가므로 안전하다.
        self.heartbeat_seq += 1
        body = json.dumps({"v": PROTOCOL_VERSION, "seq": self.heartbeat_seq, "busy": len(self.in_flight)},
                          separators=(",", ":"))
        try:
            with self.heartbeat_path.open("w", encoding="utf-8") as f:
                f.write(body)
            self.last_heartbeat = time.time()
        except OSError as e:
            log.debug("heartbeat 쓰기 실패: %s", e)

    def scan_requests(self) -> None:
        ready: list[tuple[int, float, str, dict]] = []
        now = time.time()
        for path in self.requests_dir.glob("*.json"):
            rid = path.stem
            if rid in self.in_flight or rid in self.seen:
                self._unlink(path)
                continue
            try:
                stat = path.stat()
                raw = path.read_text(encoding="utf-8-sig")
                req = json.loads(raw)
                if not isinstance(req, dict):
                    raise ValueError("request is not an object")
            except (OSError, ValueError) as e:
                age = now - path.stat().st_mtime if path.exists() else 0
                if age < float(self.bcfg["partial_grace_seconds"]):
                    continue  # 게임이 아직 쓰는 중일 수 있다
                log.warning("잘못된 요청 파일 %s: %s", path.name, e)
                self._unlink(path)
                self.respond_error(rid, "bad_request")
                continue

            self._unlink(path)
            self.seen.append(rid)
            if now - stat.st_mtime > float(self.bcfg["request_max_age_seconds"]):
                log.info("오래된 요청 무시: %s", rid)
                continue
            ready.append((int(req.get("priority", 9)), stat.st_mtime, rid, req))

        ready.sort(key=lambda r: (r[0], r[1]))
        for _, _, rid, req in ready:
            self.dispatch(rid, req)

    def dispatch(self, rid: str, req: dict) -> None:
        if not ID_PATTERN.match(rid) or req.get("id") != rid:
            log.warning("요청 id 불일치: file=%s body=%s", rid, req.get("id"))
            self.respond_error(rid, "bad_request")
            return
        if not self.limiter.allow():
            log.warning("시간당 호출 한도 초과, 거절: %s", rid)
            self.respond_error(rid, "rate_limited")
            return
        self.in_flight.add(rid)
        if self.executor:
            self.executor.submit(self.handle, rid, req)
        else:
            self.handle(rid, req)

    def handle(self, rid: str, req: dict) -> None:
        started = time.monotonic()
        module = str(req.get("module", ""))
        try:
            mcfg = self.cfg["modules"].get(module)
            if mcfg is None and module == "summary":
                mcfg = self.cfg["modules"].get("journal")
            if mcfg is None and module == "banter":
                mcfg = self.cfg["modules"].get("monologue")
            if mcfg is None and module == "episode":
                mcfg = self.cfg["modules"].get("radio")
            if mcfg is None and module == "letter":
                mcfg = self.cfg["modules"].get("radio")
            if mcfg is None and module == "broadcast":
                mcfg = self.cfg["modules"].get("radio")
            if mcfg is None and module == "radio_scene":
                mcfg = self.cfg["modules"].get("radio")
            if mcfg is None:
                raise ModuleError("unknown_module")
            llm_req = build_request(module, req.get("payload") or {}, mcfg)
            provider = self.provider_for(str(mcfg.get("provider", "mock")))
            result = provider.complete(llm_req)
            body = {
                "v": PROTOCOL_VERSION,
                "id": rid,
                "ok": True,
                "text": result.text,
                "model": result.model,
                "ms": int((time.monotonic() - started) * 1000),
            }
            if result.json is not None:
                body["json"] = result.json
            self.write_response(rid, body)
            lang = (req.get("payload") or {}).get("lang") if isinstance(req.get("payload"), dict) else None
            log.info("응답 %s (%s, %dms%s)", rid, result.model, body["ms"], f", lang={lang}" if lang else "")
        except (ModuleError, ProviderError) as e:
            log.warning("요청 실패 %s: %s", rid, e)
            self.respond_error(rid, e.code)
        except Exception:  # 워커 스레드에서 예외가 사라지지 않도록
            log.exception("요청 처리 중 예외 %s", rid)
            self.respond_error(rid, "internal")
        finally:
            self.in_flight.discard(rid)

    def respond_error(self, rid: str, code: str) -> None:
        if not ID_PATTERN.match(rid):
            return
        self.write_response(rid, {"v": PROTOCOL_VERSION, "id": rid, "ok": False, "error": code})

    def write_response(self, rid: str, body: dict) -> None:
        write_json_atomic(self.responses_dir / f"{rid}.json", body)

    def clean_responses(self) -> None:
        now = time.time()
        stale = float(self.bcfg["response_stale_seconds"])
        for path in self.responses_dir.glob("*.json"):
            try:
                st = path.stat()
            except OSError:
                continue
            # 게임이 읽고 비운 파일, 또는 게임이 가져가지 않은 채 오래된 파일
            if st.st_size == 0 or now - st.st_mtime > stale:
                self._unlink(path)

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            log.debug("삭제 실패 %s: %s", path.name, e)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="StoryEngine LLM bridge")
    ap.add_argument("--config", type=Path, default=HERE / "config.toml")
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--mock", action="store_true", help="모든 모듈을 mock 제공자로 처리")
    ap.add_argument("--setup", action="store_true", help="설정 마법사를 다시 실행 (config.toml 새로 만들기)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if os.name == "nt":
        os.system("title StoryEngine Bridge")
    # 설정 파일이 없으면(배포판 첫 실행) 마법사로 만든다
    if args.setup or (not args.config.exists() and not args.mock and sys.stdin and sys.stdin.isatty()):
        from setup_wizard import run_setup
        if not run_setup(args.config, default_data_dir()):
            return 1

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    data_dir = args.data_dir or Path(cfg["bridge"]["data_dir"] or default_data_dir())
    Bridge(cfg, data_dir, force_mock=args.mock).run_forever()
    return 0


def _run_frozen() -> int:
    """배포판: 오류가 나도 창이 바로 닫히지 않게 한다 (더블클릭으로 실행하므로)."""
    try:
        code = main()
    except KeyboardInterrupt:
        code = 0
    except Exception:
        logging.getLogger("bridge").exception("fatal error")
        code = 1
    try:
        print()
        input("Press Enter to close / Enter 를 누르면 닫힙니다...")
    except EOFError:
        pass
    return code


if __name__ == "__main__":
    raise SystemExit(_run_frozen() if FROZEN else main())
