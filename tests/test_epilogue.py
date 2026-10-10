"""카운티 회의의 에필로그와 헌장 서명 (epilogue 모듈), 무전의 호칭 문구."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request, format_council, format_note  # noqa: E402


def payload(**extra):
    p = {
        "lang": "KO", "day": 300, "result": "formed", "held": True, "prep": 1, "era": True,
        "siege": {"total": 1000, "sent": 600, "held": 400},
        "npcs": [
            {"fid": "ray", "name": "Ray Mercer", "trust": 85,
             "lines": ["(good) Annie came home.", "(now) The county farm feeds everyone."]},
            {"fid": "guard", "voice": "kowalski", "name": "Corporal Kowalski", "trust": 40,
             "prev": [{"voice": False, "fate": "gone"}], "lines": ["(now) Kowalski holds the camp alone."]},
            {"fid": "doc", "name": "June Adler", "trust": 70, "gone": "dead", "lines": ["(bad) The fever took her."]},
        ],
        "players": [
            {"name": "Gerald Kar", "defender": True,
             "close": [{"faction": "ray", "name": "Ray Mercer", "did": "did what you asked (5 times)"}]},
            {"name": "Ann Lee"},
        ],
        "signers": ["ray", "guard"],
    }
    p.update(extra)
    return p


class EpilogueTest(unittest.TestCase):
    def test_prompt(self):
        req = build_request("epilogue", payload(), {"model": "m"})
        text = req.messages[0]["content"]
        self.assertIn("Language: Korean", text)
        self.assertIn("it worked, and they agreed to meet every month", text)
        self.assertIn("The church: it held (about 1000 of the dead came at it; friends on the radio stopped some", text)
        self.assertIn("the county has power and running water again, for good", text)
        self.assertIn("- Ray Mercer (", text)
        self.assertIn("(good) Annie came home.", text)
        # 후임은 자기 이름과 말투로, 앞 사람은 따로
        self.assertIn("- Corporal Kowalski (", text)
        self.assertIn("Before them on this frequency: Sergeant Dale Whitaker, who left the county.", text)
        self.assertIn("stiff military", text)
        # 죽은 사람은 말투 줄 없이
        self.assertIn("This person is dead; nobody has taken over the frequency.", text)
        self.assertIn("- Gerald Kar, who stood at the church that day. Closest on the radio to: Ray Mercer (", text)
        self.assertIn("- Ann Lee.", text)
        self.assertIn("Signing the charter: ray = Ray Mercer (", text)
        self.assertIn("guard = Corporal Kowalski (", text)
        self.assertIn("Speak only Korean", text)
        sig = req.json_schema["properties"]["signatures"]["items"]
        self.assertEqual(sig["properties"]["faction"]["enum"], ["ray", "guard"])
        self.assertEqual(req.json_schema["required"], ["title", "text", "signatures"])
        self.assertIn("350 to 550 words", req.system)

    def test_failed_council(self):
        req = build_request("epilogue", payload(result="failed", held=False, era=None, prep=0.2, signers=[]),
                            {"model": "m"})
        text = req.messages[0]["content"]
        self.assertIn("it broke up in arguments; there is no county council", text)
        self.assertIn("The church: it was overrun, or nobody stayed to hold it", text)
        self.assertIn("the council met half provisioned", text)
        self.assertNotIn("for good", text)
        self.assertIn("Signing the charter: nobody.", text)

    def test_bad_payload(self):
        with self.assertRaises(ModuleError):
            build_request("epilogue", payload(result="maybe"), {"model": "m"})

    def test_title_in_radio(self):
        lines = format_council({"result": "formed", "held": True, "era": True, "days": 12, "defender": True,
                                "name": "Gerald Kar"})
        text = " ".join(lines)
        self.assertIn("met at the March Ridge church 12 days ago and it worked", text)
        self.assertIn("the church held against the dead that day", text)
        self.assertIn("keeps the power and the water running", text)
        self.assertIn("Gerald Kar was one of those who stood at the church that day", text)
        self.assertIn("Do not bring it up in every message", text)
        self.assertEqual(format_council(None), [])
        self.assertEqual(format_council({"result": "none"}), [])
        other = " ".join(format_council({"result": "failed", "held": False, "days": 0}))
        self.assertIn("today and broke up in arguments; the church was overrun", other)
        self.assertNotIn("stood at the church", other)

    def test_radio_request_carries_it(self):
        req = build_request("radio", {
            "faction": "ray", "lang": "EN", "trust": 80, "day": 312, "date": "1994-05-13", "clock": "09:00",
            "players": [], "history": [{"from": "player", "name": "Gerald Kar", "text": "Morning, Ray."}],
            "council": {"result": "formed", "held": True, "days": 12, "defender": True, "name": "Gerald Kar"},
        }, {"model": "m"})
        text = req.system + " ".join(m["content"] for m in req.messages)
        self.assertIn("Gerald Kar was one of those who stood at the church that day", text)

    def test_council_day_note(self):
        text = format_note({"kind": "holiday", "holiday": "councilday", "faction": "pike", "clock": "09:00"}, "EN")
        self.assertIn("Council Day (the anniversary of the first county council)", text)


if __name__ == "__main__":
    unittest.main()
