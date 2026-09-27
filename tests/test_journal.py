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

    def test_unknown_kind(self):
        with self.assertRaises(ModuleError):
            self.build({"kind": "poem"})


if __name__ == "__main__":
    unittest.main()
