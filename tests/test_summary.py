"""스토리 로그 압축: 주간 요약, 무전 기억, 일지·회고록·디렉터 연결."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request  # noqa: E402


def content(req):
    return req.messages[0]["content"]


class SummaryTest(unittest.TestCase):
    def test_week(self):
        days = [{"day": i, "date": f"7/{8 + i}", "class": "stayed_home", "kills": i, "harmed": i == 3,
                 "diary": f"diary {i}"} for i in range(1, 8)]
        req = build_request("summary", {"kind": "week", "lang": "KO", "character": {"name": "A"}, "days": days}, {})
        text = content(req)
        self.assertEqual(req.module, "summary")
        self.assertIn("Day 3 (7/11): stayed at home, nothing much happened, killed 3, injured. Diary: diary 3", text)
        self.assertIn("long-term record", req.system)

    def test_radio_memory(self):
        req = build_request("summary", {"kind": "radio_memory", "faction": "doc", "previous": "They helped once.",
                                        "lines": ["[09:00] A: hi", "[09:01] You: hello"]}, {})
        text = content(req)
        self.assertIn("June Adler", text)
        self.assertIn("Your notes so far: They helped once.", text)
        self.assertIn("[09:01] You: hello", text)

    def test_bad(self):
        with self.assertRaises(ModuleError):
            build_request("summary", {"kind": "nope"}, {})
        with self.assertRaises(ModuleError):
            build_request("summary", {"kind": "radio_memory", "faction": "nobody"}, {})

    def test_journal_and_memoir_use_weeks(self):
        weeks = [{"from": 1, "to": 7, "text": "They stayed near Rosewood."}]
        daily = content(build_request("journal", {"kind": "daily", "lang": "EN", "character": {"name": "A"},
                                                  "episodes": [], "weeks": weeks}, {}))
        self.assertIn("The week before, in brief (days 1-7): They stayed near Rosewood.", daily)
        memoir = content(build_request("journal", {"kind": "memoir", "lang": "EN", "character": {"name": "A"},
                                                   "daysSurvived": 9, "weeks": weeks,
                                                   "days": [{"day": 8, "class": "expedition"}]}, {}))
        self.assertIn("Earlier weeks, summarised:", memoir)
        self.assertIn("- Days 1-7: They stayed near Rosewood.", memoir)
        self.assertIn("The last days, one by one:", memoir)

    def test_director_stage(self):
        payload = {"players": [{"name": "A", "stage": 1, "maxIntensity": 2}], "events": [{"id": "quiet_day"}]}
        text = content(build_request("director", payload, {}))
        self.assertIn("early days, has little, intensity at most 2", text)

    def test_director_last_week(self):
        payload = {"players": [{"name": "A", "lastWeek": "Quiet week at home."}], "events": [{"id": "quiet_day"}]}
        text = content(build_request("director", payload, {}))
        self.assertIn("last full week: Quiet week at home.", text)


if __name__ == "__main__":
    unittest.main()
