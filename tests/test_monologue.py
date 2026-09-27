"""독백 모듈: 프롬프트 조립, 계기 화이트리스트, mock 응답."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request  # noqa: E402
from providers.mock import MockProvider  # noqa: E402

# Lua Monologue.payload 가 보내는 형태
PAYLOAD = {
    "lang": "KO", "trigger": "panic", "count": 3, "info": {"level": 3},
    "character": {"name": "프랭키 콘웰", "profession": "Fire Officer"},
    "day": 4, "clock": "21:40",
    "place": {"town": "Rosewood", "townDist": 120, "inside": False},
    "health": 60, "moodles": {"PANIC": 3, "TIRED": 1},
    "weather": {"raining": True, "snowing": False, "thunder": False},
    "notes": [{"kind": "radio_contact", "clock": "20:00", "faction": "ray"}],
    "said": ["숨 쉬어.", "너무 많아."],
}


def content(req):
    return req.messages[0]["content"]


class MonologueModuleTest(unittest.TestCase):
    def test_prompt(self):
        req = build_request("monologue", PAYLOAD, {"model": "m", "max_tokens": 500, "effort": "low"})
        text = content(req)
        self.assertIn("Language: Korean", text)
        self.assertIn("formerly a Fire Officer", text)
        self.assertIn("Feeling: panic, tiredness", text)
        self.assertNotIn("3/4", text)
        # 풀용 여러 줄: 시각·장소·날씨·최근 사건 없음
        self.assertNotIn("Rosewood", text)
        self.assertNotIn("Weather", text)
        self.assertNotIn("Ray Mercer", text)
        self.assertNotIn("21:40", text)
        self.assertIn("do not repeat", text)
        self.assertIn("Panic is rising (badly).", text)
        self.assertIn("Write 3 lines. They will be used one at a time", text)
        self.assertEqual(req.effort, "low")
        self.assertEqual(req.json_schema["required"], ["lines"])

    def test_single_line_has_situation(self):
        text = content(build_request("monologue", dict(PAYLOAD, trigger="first_kill", info={}, count=1), {}))
        self.assertIn("Rosewood [로즈우드]", text)
        self.assertIn("Weather: rain", text)
        self.assertIn("Ray Mercer", text)
        self.assertIn("21:40", text)
        self.assertIn("Write 1 line.", text)

    def test_unknown_trigger(self):
        with self.assertRaises(ModuleError) as cm:
            build_request("monologue", dict(PAYLOAD, trigger="nuke"), {})
        self.assertEqual(cm.exception.code, "unknown_trigger")

    def test_count_clamped(self):
        self.assertIn("Write 5 lines.", content(build_request("monologue", dict(PAYLOAD, count=99), {})))
        self.assertIn("Write 1 line.", content(build_request("monologue", dict(PAYLOAD, count=0), {})))

    def test_event_details(self):
        cases = {
            "bitten": ({"part": "ForeArm_L"}, "bitten on the left forearm"),
            "kills": ({"kills": 50}, "reached 50 zombie kills"),
            "new_town": ({"town": "Muldraugh"}, "Muldraugh [멀드로] for the first time"),
            "supply_found": ({"town": "Rosewood", "faction": "guard", "reward": True},
                             "left by Sergeant Dale Whitaker"),
            "horde_cleared": ({"town": "Rosewood", "faction": "ray"}, "as Ray Mercer"),
        }
        for trigger, (info, expected) in cases.items():
            text = content(build_request("monologue", dict(PAYLOAD, trigger=trigger, info=info, count=1), {}))
            self.assertIn(expected, text, trigger)

    def test_wake_diary(self):
        text = content(build_request("monologue", dict(PAYLOAD, trigger="wake", info={}, diary="오늘은 조용했다."), {}))
        self.assertIn("diary last night: 오늘은 조용했다.", text)

    def test_lua_empty_tables(self):
        payload = dict(PAYLOAD, info={}, notes={}, said={}, moodles={}, place={}, count=1)
        text = content(build_request("monologue", payload, {}))
        self.assertIn("Knox County countryside", text)
        self.assertNotIn("Feeling:", text)

    def test_mock_lines(self):
        req = build_request("monologue", PAYLOAD, {})
        out = MockProvider({}).complete(req)
        self.assertEqual(out.json["lines"], ["[mock] panic 1", "[mock] panic 2", "[mock] panic 3"])


if __name__ == "__main__":
    unittest.main()
