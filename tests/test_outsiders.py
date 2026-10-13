"""밖에서 온 사람들 (format_outsiders, 페르소나 넷)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import FACTIONS, build_request, format_outsiders  # noqa: E402

HERE = [{"id": "okafor", "name": "Dr. Okafor", "who": "Dr. Okafor's research team", "trust": 45,
         "disliked": True, "rival": True, "sided": "out"}]


class OutsidersTest(unittest.TestCase):
    def test_four_personas_with_fixed_speech(self):
        for fid in ("hale", "odell", "okafor", "abigail"):
            self.assertIn(fid, FACTIONS)
            self.assertTrue(FACTIONS[fid]["speech"]["KO"])
            self.assertTrue(FACTIONS[fid]["local"]["KO"])

    def test_a_local_is_told_who_came_and_how_they_feel(self):
        text = " ".join(format_outsiders("doc", {"here": HERE}))
        self.assertIn("Dr. Okafor (Dr. Okafor's research team) were let in by a council vote", text)
        self.assertIn("you do not want them here", text)
        self.assertIn("took their side against you", text)
        wary = " ".join(format_outsiders("pike", {"here": [dict(HERE[0], rival=None, sided=None)]}))
        self.assertIn("You are wary of them", wary)
        calm = " ".join(format_outsiders("ray", {"here": [{"id": "okafor", "name": "Dr. Okafor", "who": "x"}],
                                                  "pending": "Captain Odell"}))
        self.assertIn("You have nothing against them.", calm)
        self.assertIn("Captain Odell and their people have asked to stay", calm)
        self.assertEqual(format_outsiders("ray", None), [])

    def test_an_outsider_knows_they_are_a_guest(self):
        info = {"here": HERE, "self": {"who": "research team", "rival": "Doc Adler", "hard": True,
                                       "dislike": ["Doc Adler", "Pastor Pike", "Hank Tolliver"]}}
        text = " ".join(format_outsiders("okafor", info))
        self.assertIn("You are an outsider here", text)
        self.assertIn("Doc Adler, Pastor Pike, Hank Tolliver are wary of you", text)
        self.assertIn("the players chose Doc Adler", text)
        self.assertNotIn("were let in by a council vote", text)     # 자기 자신은 목록에서 뺀다

    def test_radio_request_for_an_outsider(self):
        req = build_request("radio", {
            "faction": "abigail", "lang": "KO", "trust": 45, "day": 340, "date": "1994-06-10", "clock": "09:00",
            "players": [], "history": [{"from": "player", "name": "Gerald Kar", "text": "hello"}],
            "outsiders": {"here": [], "self": {"who": "pilgrims", "rival": "Pastor Pike", "dislike": ["Pastor Pike"]}},
        }, {"model": "m"})
        blob = req.system + " ".join(m["content"] for m in req.messages)
        self.assertIn("Mother Abigail", blob)
        self.assertIn("You are an outsider here", blob)


if __name__ == "__main__":
    unittest.main()
