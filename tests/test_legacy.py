"""캐릭터가 죽은 뒤의 관계: 처음 듣는 목소리 맥락, 죽은 캐릭터 행적 표시."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import build_request  # noqa: E402


class LegacyTest(unittest.TestCase):
    def radio(self, **extra):
        payload = {"faction": "ray", "lang": "EN", "trust": 50, "history": []}
        payload.update(extra)
        return build_request("radio", payload, {"model": "m"})

    def test_newcomer(self):
        system = self.radio(newcomer={
            "name": "Mina Park", "companions": ["Minsu Kim"],
            "dead": [{"name": "Gerald Kar", "daysAgo": 2, "knew": True,
                      "what": "did jobs for you (3 times); talked with you on the radio 12 times"},
                     {"name": "Old Bob", "daysAgo": 0}]}).system
        self.assertIn("Mina Park is a voice you have never heard before", system)
        self.assertIn("Mina Park travels with the same group as Minsu Kim.", system)
        self.assertIn("Gerald Kar died 2 days ago (between Gerald Kar and you: did jobs for you (3 times)", system)
        self.assertIn("Old Bob died today (you never really dealt with them)", system)
        self.assertIn("Do not invent how they died.", system)
        self.assertNotIn("never heard before", self.radio().system)

    def test_dead_in_records(self):
        system = self.radio(life={"records": [
            {"day": 3, "kind": "quest_completed", "who": "Gerald Kar", "d": 2, "dead": True},
            {"day": 5, "kind": "player_died", "who": "Gerald Kar", "dead": True},
            {"day": 5, "kind": "quest_completed", "who": "Minsu Kim"}]}).system
        self.assertIn("Gerald Kar did what you asked (Gerald Kar is dead now)", system)
        self.assertIn("you heard that Gerald Kar died", system)
        self.assertNotIn("Minsu Kim is dead", system)


if __name__ == "__main__":
    unittest.main()
