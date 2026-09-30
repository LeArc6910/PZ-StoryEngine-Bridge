"""NPC 생활 상태: 형편·행적·평판 맥락, 공용 주파수 형편, 거래 품절·부족, 물자 지원 일지 메모."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import build_request, format_life_context, format_note, format_trade_rules  # noqa: E402

LIFE = {
    "state": {"food": 8, "medical": 30, "safety": 60, "morale": 85},
    "records": [
        {"day": 3, "kind": "quest_completed", "who": "Gerald", "d": 3},
        {"day": 4, "kind": "spill_down", "who": "Gerald", "d": -1, "src": "rats"},
        {"day": 5, "kind": "unknown_kind", "who": "x"},
        {"day": 6, "kind": "donation", "who": "Minsu", "d": 2},
    ],
    "tags": ["healer", "bogus"],
}


class LifeTest(unittest.TestCase):
    def test_context_lines(self):
        text = "\n".join(format_life_context(LIFE))
        self.assertIn("food and water none left (8/100)", text)
        self.assertIn("medicine running low (30/100)", text)
        self.assertIn("ammunition and defenses enough for now (60/100)", text)
        self.assertIn("morale plenty (85/100)", text)
        self.assertIn("- day 3: Gerald did what you asked (trust +3)", text)
        self.assertIn("- day 4: Gerald helped Vic, whom you do not like (trust -1)", text)
        self.assertIn("- day 6: Minsu sent your people supplies without being asked (trust +2)", text)
        self.assertNotIn("unknown_kind", text)
        self.assertIn("How you think of them by now: the one who brings medicine.", text)
        self.assertEqual(format_life_context(None), [])

    def test_project_line(self):
        text = " ".join(format_life_context({"project": {"name": "a greenhouse farm", "points": 45}}))
        self.assertIn("Your big project: a greenhouse farm, about 45% done (the players have been helping).", text)
        done = " ".join(format_life_context({"project": {"name": "a greenhouse farm", "points": 100, "done": True}}))
        self.assertIn("is finished thanks to the players", done)
        self.assertEqual(format_note({"kind": "project_done", "faction": "ray", "item": "a greenhouse farm", "clock": "09:00"}),
                         "09:00 heard that Ray Mercer finished their big project (a greenhouse farm) with the players' help")

    def test_in_radio_persona(self):
        req = build_request("radio", {"faction": "doc", "lang": "EN", "trust": 50, "history": [], "life": LIFE},
                            {"model": "m"})
        self.assertIn("How your people are doing right now: food and water none left", req.system)

    def test_scene_state(self):
        payload = {"lang": "EN", "participants": [{"id": "ray", "trust": 50, "state": {"food": 30}},
                                                  {"id": "doc", "trust": 50}],
                   "log": [], "topic": "chat"}
        text = build_request("radio_scene", payload, {"model": "m"}).messages[0]["content"]
        self.assertIn("Their people right now: food and water running low (30/100).", text)

    def test_trade_empty_and_short(self):
        trade = {"allowed": True, "maxTier": 3, "mult": 1.5, "wants": ["food"],
                 "goods": [{"category": "food", "maxTier": 3}],
                 "catalog": [{"category": "medical", "maxTier": 0, "needs": [20, 20, 40], "empty": True},
                             {"category": "food", "maxTier": 3, "needs": [20, 20, 40], "short": True}]}
        text = "\n".join(format_trade_rules(trade, "doc"))
        self.assertIn("medical: none to spare right now", text)
        self.assertIn("If they ask for medical, refuse", text)
        self.assertIn("You are short on food yourself", text)
        self.assertNotIn("locked: needs trust 20", text.split("medical:")[1].split("\n")[0])

    def test_fate_notes_and_story_context(self):
        self.assertEqual(format_note({"kind": "npc_dead", "faction": "doc", "clock": "08:00"}),
                         "08:00 heard over the radio that June Adler had died")
        self.assertEqual(format_note({"kind": "npc_gone", "faction": "ray", "clock": "08:00"}),
                         "08:00 Ray Mercer left for good and went off the air")
        story = {"others": [{"id": "doc", "note": "you respect her", "trust": 50, "gone": "dead", "beat": "x"},
                            {"id": "casey", "note": "the kid", "trust": 70}]}
        req = build_request("radio", {"faction": "pike", "lang": "EN", "trust": 50, "history": [], "story": story},
                            {"model": "m"})
        self.assertIn("- June Adler: you respect her; June Adler died recently.", req.system)
        self.assertIn("- Casey Liu: the kid; how much they (not you) trust the players", req.system)

    def test_director_npc_situation_and_emergency(self):
        payload = {"day": 5, "players": [{"name": "Gerald"}], "events": [{"id": "npc_emergency"}, {"id": "quiet_day"}],
                   "npcs": [{"id": "doc", "trust": 40, "state": {"food": 50, "medical": 8, "safety": 30, "morale": 45}}]}
        req = build_request("director", payload, {"model": "m"})
        text = req.messages[0]["content"]
        self.assertIn("Radio contacts' situation", text)
        self.assertIn("- June Adler (trust 40): food and water enough for now (50/100), medicine none left (8/100)", text)
        self.assertIn("- npc_emergency:", text)

    def test_donation_note(self):
        note = format_note({"kind": "donation", "faction": "ray", "item": "3 x Beans", "clock": "10:00"})
        self.assertEqual(note, "10:00 sent supplies over to Ray Mercer to help their people (3 x Beans)")


if __name__ == "__main__":
    unittest.main()
