"""캐릭터끼리 대화 모듈."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request, format_note  # noqa: E402

PAYLOAD = {
    "speakers": [
        {"name": "Eddie Gagnon", "profession": "Carpenter", "lang": "KO", "hp": 60, "wounds": 1,
         "moodles": {"PANIC": 2}, "met": [{"name": "Minsu Kim", "minutes": 190}]},
        {"name": "Minsu Kim", "profession": "Nurse", "lang": "KO", "hp": 100, "wounds": 0, "moodles": {},
         "met": [{"name": "Eddie Gagnon", "minutes": 190}]},
    ],
    "event": {"kind": "bitten", "info": {"part": "ForeArm_L"}, "who": "Eddie Gagnon"},
    "day": 5, "clock": "14:20", "place": {"town": "Riverside", "townDist": 80, "inside": False},
    "weather": {"raining": True},
    "radio": [{"clock": "13:00", "faction": "ray", "from": "npc", "text": "Stay off the main road."}],
    "said": ["Keep moving."],
}


class BanterTest(unittest.TestCase):
    def build(self, payload):
        return build_request("banter", payload, {"model": "m"})

    def test_prompt_and_schema(self):
        req = self.build(PAYLOAD)
        text = req.messages[0]["content"]
        self.assertIn("Language: everyone speaks Korean", text)
        self.assertIn("Eddie Gagnon", text)
        self.assertIn("about 3 hours in total with Minsu Kim since they met", text)
        self.assertIn("This just happened to Eddie Gagnon: They were just bitten on the", text)
        self.assertIn('Ray Mercer [레이 머서]: "Stay off the main road."', text)
        self.assertIn("do not repeat): Keep moving.", text)
        self.assertIn("Weather: rain", text)
        item = req.json_schema["properties"]["lines"]["items"]
        self.assertEqual(item["properties"]["speaker"]["enum"], ["Eddie Gagnon", "Minsu Kim"])
        self.assertEqual(req.module, "banter")

    def test_group_events_and_languages(self):
        mixed = dict(PAYLOAD, speakers=[dict(PAYLOAD["speakers"][0]), dict(PAYLOAD["speakers"][1], lang="EN")],
                     event={"kind": "support_arrived", "info": {"faction": "guard", "count": 6}})
        text = self.build(mixed).messages[0]["content"]
        self.assertIn("each person speaks their own language", text)
        self.assertIn("Minsu Kim speaks English", text)
        self.assertIn("6 armed people sent by Sergeant Dale Whitaker", text)
        chat = self.build(dict(PAYLOAD, event={"kind": "chat"})).messages[0]["content"]
        self.assertIn("just spending time together", chat)
        with self.assertRaises(ModuleError):
            self.build(dict(PAYLOAD, event={"kind": "bogus"}))
        with self.assertRaises(ModuleError):
            self.build(dict(PAYLOAD, speakers=PAYLOAD["speakers"][:1]))

    def test_journal_note(self):
        note = {"kind": "banter", "with": ["Minsu Kim"], "event": "bitten", "clock": "14:21",
                "lines": ["Eddie Gagnon: It got me.", "Minsu Kim: Let me see it."]}
        self.assertEqual(format_note(note, "EN"),
                         '14:21 talked with Minsu Kim: "Eddie Gagnon: It got me." / "Minsu Kim: Let me see it."')
        self.assertIsNone(format_note({"kind": "banter", "lines": []}, "EN"))


if __name__ == "__main__":
    unittest.main()
