"""게임 속 라디오 저녁 방송 (broadcast 모듈)과 일지의 "방송을 들었다" 메모."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request, format_note  # noqa: E402


class BroadcastTest(unittest.TestCase):
    def build(self, **extra):
        payload = {"host": "casey", "lang": "KO", "day": 6, "clock": "19:00", "freq": "105.4",
                   "facts": ["Minsu cleared out a pack of the dead for Ray Mercer near Riverside.",
                             "A helicopter flew low over the county today."],
                   "weather": "Tomorrow: 17 to 26 C, heavy rain", "beat": "Your father's fever broke."}
        payload.update(extra)
        return build_request("broadcast", payload, {"model": "m"})

    def test_payload_to_prompt(self):
        req = self.build()
        text = req.messages[0]["content"]
        self.assertIn("Language: Korean", text)
        self.assertIn('Station: "Valley Station Evening News", 105.4 MHz. Day 6', text)
        self.assertIn("Host: Casey Liu (케이시 리우).", text)
        self.assertIn("Host's speech level, always the same: polite 해요체", text)
        self.assertIn('("you" means the host): Your father\'s fever broke.', text)
        self.assertIn("- Minsu cleared out a pack", text)
        self.assertIn("Weather forecast: Tomorrow: 17 to 26 C, heavy rain", text)
        self.assertNotIn("no longer on the air", text)
        self.assertEqual(req.json_schema["required"], ["lines", "rerun"])
        self.assertIn("Do not invent deaths", req.system)

    def test_quiet_day_and_ray_takes_over(self):
        text = self.build(host="ray", lang="EN", facts=[], weather=None, beat=None).messages[0]["content"]
        self.assertIn("Host: Ray Mercer.", text)
        self.assertIn("Casey, is no longer on the air", text)
        self.assertIn("nothing new reached the host today", text)
        self.assertIn("barometer is acting up", text)
        with self.assertRaises(ModuleError):
            self.build(host="nobody")

    def test_world_conditions(self):
        text = self.build(conditions=["no power", "winter"]).messages[0]["content"]
        self.assertIn("Life in the county now: no power, winter.", text)
        for kind, words in (("world_power", "power grid went down"), ("world_winter", "winter set in"),
                            ("world_day30", "a month since the outbreak")):
            self.assertIn(words, format_note({"kind": kind, "clock": "10:00"}, "EN"))

    def test_journal_note(self):
        line = format_note({"kind": "broadcast_heard", "faction": "casey", "clock": "19:05",
                            "lines": ["Valley Station, 105.4.", "Ray's people are short of food."]}, "EN")
        self.assertIn("19:05 listened to", line)
        self.assertIn("evening news on the radio", line)
        self.assertIn('"Ray\'s people are short of food."', line)


if __name__ == "__main__":
    unittest.main()
