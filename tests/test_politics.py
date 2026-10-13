"""의회의 정치 (format_politics): 파벌, 기울기, 걸린 법안과 표, 시행 중인 법안."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import build_request, format_politics  # noqa: E402


class PoliticsTest(unittest.TestCase):
    def test_camp_and_bill(self):
        text = " ".join(format_politics({
            "bloc": "gun", "lean": {"field": 40, "gun": 0, "market": 5}, "against": True,
            "bill": {"text": "opening the Guard's armory.", "vote": "against", "days": 2},
            "laws": ["a common kitchen that feeds every survivor", "a truce between the Guard and Vic's crew"],
        }))
        self.assertIn("You stand with the Guns", text)
        self.assertIn("doing a lot for the Fields lately", text)
        self.assertIn("You hold it against them a little.", text)
        self.assertIn("to be voted on in 2 days: opening the Guard's armory.", text)
        self.assertIn("you will vote AGAINST it", text)
        self.assertIn("In force by council vote right now: a common kitchen", text)

    def test_own_side_and_own_bill(self):
        text = " ".join(format_politics({
            "bloc": "market", "lean": {"market": 30},
            "bill": {"text": "a county post.", "vote": "for", "days": 0, "mine": True},
        }))
        self.assertIn("friends of your side", text)
        self.assertIn("voted on today", text)
        self.assertIn("It is your own proposal.", text)
        self.assertIn("vote FOR it", text)

    def test_nothing_before_politics(self):
        self.assertEqual(format_politics(None), [])
        self.assertEqual(format_politics({"bloc": "nobody"}), [])
        quiet = " ".join(format_politics({"bloc": "field", "lean": {"field": 5}}))
        self.assertNotIn("lately", quiet)
        self.assertNotIn("Before the council", quiet)

    def test_radio_request_carries_it(self):
        req = build_request("radio", {
            "faction": "ray", "lang": "EN", "trust": 60, "day": 330, "date": "1994-06-01", "clock": "09:00",
            "players": [], "history": [{"from": "player", "name": "Gerald Kar", "text": "Morning, Ray."}],
            "politics": {"bloc": "field", "lean": {}, "bill": {"text": "a common kitchen.", "vote": "for", "days": 1}},
        }, {"model": "m"})
        text = req.system + " ".join(m["content"] for m in req.messages)
        self.assertIn("You stand with the Fields", text)
        self.assertIn("voted on tomorrow: a common kitchen.", text)


if __name__ == "__main__":
    unittest.main()
