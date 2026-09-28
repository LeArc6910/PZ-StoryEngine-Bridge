"""일지 모듈 프롬프트 조립 테스트."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request  # noqa: E402

# Lua 쪽 Journal.lua 가 보내는 형태 (Json.encode 결과를 파이썬 dict 로 옮긴 것)
DAILY = {
    "kind": "daily",
    "lang": "KO",
    "character": {"name": "Eddie Gagnon", "profession": "Fire Officer"},
    "date": "7/12",
    "day": 4,
    "home": {"town": "Muldraugh", "townDist": 100, "inside": True, "residential": True},
    "summary": {"class": "combat_day", "travel": 412, "maxFromHome": 160, "outsideMin": 90,
                "kills": 17, "harmed": True, "moodlePeaks": {"PANIC": 3, "BORED": 0}},
    "episodes": [
        {"from": "09:10", "to": "11:40",
         "place": {"town": "Muldraugh", "townDist": 120, "inside": True,
                   "residential": False, "rooms": ["firestorage", "office"]},
         "with": ["Minsu Kim"], "kills": 11, "zombiesNear": 14,
         "harm": [{"who": "Minsu Kim", "part": "Hand_L", "kind": "scratched"}]},
        {"from": "11:40", "to": "13:00",
         "place": {"town": "Muldraugh", "townDist": 90, "inside": False, "rooms": {}, "via": ["West Point"]},
         "with": {}, "kills": 6, "harm": {}, "_via": 1},
    ],
    "previous": "어제는 비가 왔다.",
}


class JournalModuleTest(unittest.TestCase):
    def build(self, payload):
        return build_request("journal", payload, {"model": "m", "max_tokens": 100})

    def test_daily_contains_facts(self):
        req = self.build(DAILY)
        text = req.messages[0]["content"]
        self.assertIn("Language: Korean", text)
        self.assertIn("Eddie Gagnon, formerly a Fire Officer", text)
        self.assertIn("Muldraugh [멀드로]", text)
        self.assertIn("inside a building (rooms: firestorage, office)", text)
        self.assertIn("with Minsu Kim", text)
        self.assertIn("Minsu Kim: scratched on left hand", text)
        self.assertIn("killed 11 zombies", text)
        self.assertIn("panic 3/4", text)
        self.assertNotIn("boredom", text, "레벨 0 무들은 빼야 한다")
        self.assertIn("a day of heavy fighting", text)
        self.assertIn("어제는 비가 왔다.", text)
        self.assertIn("Home: Muldraugh [멀드로], inside a house", text)
        self.assertIn("traveling through West Point [웨스트 포인트]", text)
        self.assertIn("Four to eight sentences", req.system)

    def test_english_has_no_local_names(self):
        req = self.build({**DAILY, "lang": "EN"})
        text = req.messages[0]["content"]
        self.assertIn("Muldraugh, inside", text)
        self.assertNotIn("멀드로", text)

    def test_empty_lua_tables_are_lists(self):
        req = self.build({**DAILY, "episodes": {}})
        self.assertIn("Nothing was recorded", req.messages[0]["content"])

    def test_far_from_town_is_countryside(self):
        ep = {"from": "1", "to": "2", "place": {"town": "Rosewood", "townDist": 900, "inside": False}}
        req = self.build({**DAILY, "episodes": [ep]})
        self.assertIn("countryside 900 tiles from Rosewood", req.messages[0]["content"])

    def test_episode_list_is_capped(self):
        eps = [{"from": f"{i}", "to": f"{i}", "place": {}} for i in range(100)]
        req = self.build({**DAILY, "episodes": eps})
        self.assertEqual(req.messages[0]["content"].count("Knox County countryside"), 30)

    def test_bad_types_do_not_crash(self):
        req = self.build({"kind": "daily", "summary": "x", "episodes": "y", "character": 5, "day": "abc"})
        self.assertIn("Language: English", req.messages[0]["content"])

    def test_memoir(self):
        payload = {
            "kind": "memoir", "lang": "EN", "character": {"name": "Eddie Gagnon"}, "daysSurvived": 9,
            "death": {"date": "7/17", "place": {"town": "Rosewood", "townDist": 50, "inside": True},
                      "harm": [{"part": "Neck", "kind": "bitten"}]},
            "days": [{"day": 1, "date": "7/9", "class": "stayed_home", "diary": "Quiet."}],
            "episodes": [],
        }
        req = self.build(payload)
        text = req.messages[0]["content"]
        self.assertIn("Survived 9 days", text)
        self.assertIn("BITTEN on neck", text)
        self.assertIn("Their diary said: Quiet.", text)
        self.assertIn("third person", req.system)

    def test_activities(self):
        acts = {"craft": {"n": 3, "w": {"Craft Rope": 2, "Make Spear": 1}},
                "dismantle": {"n": 4, "w": {"Dismantle Radio": 4}},
                "fish": {"n": 2, "w": {"Bass": 2}},
                "treat_other": {"n": 1, "w": {}},
                "chop": {"n": 5, "w": []},
                "bogus": {"n": 9, "w": {"x": 9}}}
        ep = dict(DAILY["episodes"][0], acts=acts)
        payload = dict(DAILY, episodes=[ep], summary=dict(DAILY["summary"], acts=acts))
        text = self.build(payload).messages[0]["content"]
        self.assertIn("did: crafted: Craft Rope x2, Make Spear; took apart for parts: Dismantle Radio x4; "
                      "caught fish: Bass x2; treated another survivor's wounds; chopped at trees (5 times)", text)
        self.assertIn("Work and chores today: crafted: Craft Rope x2", text)
        self.assertNotIn("bogus", text)
        # 빈 Lua 테이블은 [] 로 온다
        empty = self.build(dict(DAILY, episodes=[dict(ep, acts=[])])).messages[0]["content"]
        self.assertNotIn("did:", empty)

    def test_death_note_and_comment(self):
        notes = [{"kind": "death_of", "by": "Minsu Kim", "place": {"town": "Riverside", "townDist": 90}, "together": 185,
                  "clock": "21:10"},
                 {"kind": "death_of", "by": "Tia Gordon", "together": 0}]
        text = self.build(dict(DAILY, notes=notes)).messages[0]["content"]
        self.assertIn("heard that Minsu Kim, another survivor, had died near", text)
        self.assertIn("(they had spent about 3 hours in each other's company)", text)
        self.assertIn("(they had never met in person)", text)

        payload = {"kind": "comment", "lang": "EN", "character": {"name": "Eddie Gagnon", "profession": "Carpenter"},
                   "dead": {"name": "Minsu Kim", "profession": "Nurse", "daysSurvived": 12, "date": "7/20",
                            "place": {"town": "Riverside", "townDist": 90, "inside": True},
                            "harm": [{"part": "Neck", "kind": "bitten"}]},
                   "together": 185, "mentions": [{"date": "7/15", "text": "Minsu patched my arm today."}]}
        req = self.build(payload)
        body = req.messages[0]["content"]
        self.assertIn("The survivor who died: Minsu Kim", body)
        self.assertIn("after 12 days", body)
        self.assertIn("The writer spent about 3 hours in their company.", body)
        self.assertIn("- 7/15: Minsu patched my arm today.", body)
        self.assertIn("Their last injuries:", body)
        self.assertIn("remembrance", req.system)
        stranger = self.build(dict(payload, together=0, mentions=[])).messages[0]["content"]
        self.assertIn("never spent time with them in person", stranger)

    def test_radio_lines(self):
        radio = [{"clock": "10:02", "day": 8, "faction": "ray", "from": "player", "text": "Need canned food, can trade bandages"},
                 {"clock": "10:03", "day": 8, "faction": "ray", "from": "npc", "text": "Bring me two boxes of bandages."},
                 {"clock": "10:04", "faction": "bogus", "from": "npc", "text": "static"},
                 {"clock": "10:05", "faction": "ray", "from": "npc", "text": ""}]
        text = self.build(dict(DAILY, lang="EN", radio=radio)).messages[0]["content"]
        self.assertIn("What was actually said on the radio", text)
        self.assertIn('- [10:02] Eddie Gagnon to Ray Mercer: "Need canned food, can trade bandages"', text)
        self.assertIn('- [10:03] Ray Mercer: "Bring me two boxes of bandages."', text)
        self.assertIn('- [10:04] a radio contact: "static"', text)
        self.assertEqual(text.count("[10:05]"), 0)
        memoir = self.build({"kind": "memoir", "lang": "EN", "character": {"name": "Eddie Gagnon"}, "daysSurvived": 9,
                             "days": [], "radio": radio}).messages[0]["content"]
        self.assertIn('- [day 8 10:02] Eddie Gagnon to Ray Mercer:', memoir)
        self.assertIn("Their last radio conversations", memoir)

    def test_unknown_kind(self):
        with self.assertRaises(ModuleError):
            self.build({"kind": "poem"})


if __name__ == "__main__":
    unittest.main()
