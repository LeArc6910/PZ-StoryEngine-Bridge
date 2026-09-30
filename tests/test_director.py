"""디렉터 모듈: 프롬프트 조립, 동적 스키마, mock 응답."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request  # noqa: E402
from providers.mock import MockProvider  # noqa: E402

# Lua Director.lua 가 보내는 형태
PAYLOAD = {
    "day": 3, "date": "7/11", "clock": "08:00",
    "weather": {"raining": False, "snowing": False, "thunder": False, "temp": 24.6},
    "players": [
        {"name": "프랭키 콘웰", "hp": 92, "bitten": False, "wounds": 1, "inside": True, "town": "Rosewood",
         "zombiesNear": 4, "moodles": {"BORED": 2},
         "days": [{"day": 1, "class": "local_scavenge", "kills": 6, "harmed": False, "maxFromHome": 44},
                  {"day": 2, "class": "stayed_home", "kills": 0, "harmed": False, "maxFromHome": 3}]},
        {"name": "Minsu Kim", "hp": 40, "bitten": True, "inside": False, "days": {}},
    ],
    "recent": [{"day": 2, "clock": "20:00", "event": "quiet_day", "intensity": 1, "target": "프랭키 콘웰"}],
    "events": [{"id": "quiet_day"}, {"id": "storm"}, {"id": "supply_drop"}, {"id": "nuke"}],
}


class DirectorModuleTest(unittest.TestCase):
    def build(self, payload):
        return build_request("director", payload, {"model": "m", "max_tokens": 100})

    def test_world_conditions(self):
        text = self.build(dict(PAYLOAD, world=["no power", "winter"])).messages[0]["content"]
        self.assertIn("County conditions now: no power, winter.", text)
        self.assertNotIn("County conditions", self.build(PAYLOAD).messages[0]["content"])

    def test_prompt_facts(self):
        text = self.build(PAYLOAD).messages[0]["content"]
        self.assertIn("Day 3, 7/11 08:00. Weather: dry, 25C.", text)
        self.assertIn("- 프랭키 콘웰: health 92/100, 1 wounds, indoors, near Rosewood", text)
        self.assertIn("boredom 2/4", text)
        self.assertIn("day 2: stayed at home", text)
        self.assertIn("- Minsu Kim: health 40/100, BITTEN, outdoors", text)
        self.assertIn("day 2 20:00: quiet_day (intensity 1) for 프랭키 콘웰", text)

    def test_schema_whitelists_events_and_targets(self):
        req = self.build(PAYLOAD)
        props = req.json_schema["properties"]
        self.assertEqual(props["event"]["enum"], ["quiet_day", "storm", "supply_drop"])
        self.assertIn("fetch_item", __import__("modules").DIRECTOR_EVENTS)
        self.assertIn("npc_request", __import__("modules").DIRECTOR_EVENTS)
        self.assertEqual(props["target"]["enum"], ["프랭키 콘웰", "Minsu Kim"])
        self.assertEqual(props["intensity"]["enum"], [1, 2, 3, 4, 5])
        self.assertFalse(req.json_schema["additionalProperties"])
        self.assertNotIn("nuke", req.messages[0]["content"], "게임이 보내도 설명 없는 이벤트는 숨긴다")

    def test_only_allowed_events_offered(self):
        req = self.build({**PAYLOAD, "events": [{"id": "quiet_day"}]})
        self.assertEqual(req.json_schema["properties"]["event"]["enum"], ["quiet_day"])
        self.assertNotIn("storm:", req.messages[0]["content"])

    def test_requires_players_and_events(self):
        with self.assertRaises(ModuleError):
            self.build({**PAYLOAD, "players": {}})
        with self.assertRaises(ModuleError):
            self.build({**PAYLOAD, "events": [{"id": "nuke"}]})

    def test_mock_answers_within_schema(self):
        req = self.build(PAYLOAD)
        mock = MockProvider({"seed": 1})
        for _ in range(20):
            data = mock.complete(req).json
            self.assertIn(data["event"], ["quiet_day", "storm", "supply_drop"])
            self.assertIn(data["target"], ["프랭키 콘웰", "Minsu Kim"])
            self.assertIn(data["intensity"], [1, 2, 3, 4, 5])
            self.assertIsInstance(data["reason"], str)


class JournalNotesTest(unittest.TestCase):
    def test_director_notes_in_journal(self):
        payload = {
            "kind": "daily", "lang": "KO", "character": {"name": "A"}, "episodes": [],
            "notes": [
                {"kind": "storm", "clock": "20:00"},
                {"kind": "supply_drop_offered", "clock": "08:00", "faction": "ray",
                 "place": {"town": "Muldraugh", "townDist": 40, "inside": True, "rooms": ["firestorage"]}},
                {"kind": "supply_drop_completed", "clock": "13:10", "by": "Minsu Kim", "place": {"town": "Muldraugh"}},
                {"kind": "bogus"},
            ],
        }
        text = build_request("journal", payload, {}).messages[0]["content"]
        self.assertIn("- 20:00 a storm rolled in", text)
        self.assertIn("heard over the radio that Ray Mercer [레이 머서] left supplies at Muldraugh [멀드로]", text)
        self.assertIn("Minsu Kim found the supplies at Muldraugh [멀드로]", text)
        self.assertEqual(text.count("\n- "), 4, "알 수 없는 note 는 빠진다 (에피소드 없음 1줄 + note 3줄)")


class DeliverNotesTest(unittest.TestCase):
    def test_deliver_notes(self):
        notes = [
            {"kind": "deliver_proposed", "clock": "08:00", "faction": "ray", "item": "진통제 x2"},
            {"kind": "deliver_declined", "clock": "08:30", "faction": "guard", "item": "항생제"},
            {"kind": "deliver_completed", "clock": "12:00", "faction": "ray", "by": "A", "item": "진통제 x2"},
        ]
        text = build_request("journal", {"kind": "daily", "lang": "KO", "character": {"name": "A"},
                                         "episodes": [], "notes": notes}, {}).messages[0]["content"]
        self.assertIn("Ray Mercer [레이 머서] asked over the radio for 진통제 x2", text)
        self.assertIn("turned down Sergeant Dale Whitaker [데일 휘태커 병장]'s request for 항생제", text)
        self.assertIn("A handed 진통제 x2 over to Ray Mercer", text)


class HordeNotesTest(unittest.TestCase):
    def test_horde_notes(self):
        place = {"town": "Muldraugh", "townDist": 200, "inside": False, "landmark": "Muldraugh Trainyard"}
        notes = [
            {"kind": "horde_proposed", "clock": "08:00", "faction": "guard", "place": place},
            {"kind": "horde_completed", "clock": "15:00", "faction": "guard", "by": "A", "place": place},
        ]
        text = build_request("journal", {"kind": "daily", "lang": "KO", "character": {"name": "A"},
                                         "episodes": [], "notes": notes}, {}).messages[0]["content"]
        self.assertIn("asked over the radio for help clearing a horde near Muldraugh [멀드로]", text)
        self.assertIn("A cleared out the horde near Muldraugh [멀드로], near Muldraugh Trainyard, outdoors for Sergeant Dale Whitaker", text)


class FetchNotesTest(unittest.TestCase):
    def test_fetch_lifecycle_notes(self):
        place = {"town": "Rosewood", "townDist": 30, "inside": True}
        notes = [
            {"kind": "fetch_offered", "clock": "08:00", "faction": "guard", "item": "봉인된 서류", "place": place},
            {"kind": "fetch_retrieved", "clock": "11:00", "by": "A", "item": "봉인된 서류", "place": place},
            {"kind": "fetch_completed", "clock": "11:30", "by": "A", "item": "봉인된 서류", "faction": "guard",
             "place": place},
            {"kind": "supply_looted", "clock": "12:00", "by": "A", "place": place},
        ]
        text = build_request("journal", {"kind": "daily", "lang": "KO", "character": {"name": "A"},
                                         "episodes": [], "notes": notes}, {}).messages[0]["content"]
        self.assertIn("Sergeant Dale Whitaker [데일 휘태커 병장] asked over the radio for someone to bring back a 봉인된 서류", text)
        self.assertIn("A found the 봉인된 서류 at Rosewood [로즈우드]", text)
        self.assertIn("A handed the 봉인된 서류 over to Sergeant Dale Whitaker", text)
        self.assertIn("A found the supplies at Rosewood", text, "이전 버전 note 도 읽는다")


if __name__ == "__main__":
    unittest.main()


class NewEventsNotesTest(unittest.TestCase):
    def test_new_notes_and_fight(self):
        place = {"town": "Muldraugh", "townDist": 100, "inside": True}
        notes = [
            {"kind": "horde_nearby", "clock": "10:00", "count": 15},
            {"kind": "helicopter", "clock": "11:00"},
            {"kind": "rescue_offered", "clock": "12:00", "faction": "casey", "place": place},
            {"kind": "rescue_completed", "clock": "15:00", "faction": "casey", "by": "A", "place": place,
             "fight": {"kills": 4, "hurt": 1, "bitten": False}},
        ]
        text = build_request("journal", {"kind": "daily", "lang": "KO", "character": {"name": "A"},
                                         "episodes": [], "notes": notes}, {}).messages[0]["content"]
        self.assertIn("a pack of about 15 of the dead came after them and would not stop following", text)
        self.assertIn("a helicopter flew low over the area", text)
        self.assertIn("relayed a distress call", text)
        self.assertIn("(a fight: killed 4 zombies there, someone got hurt)", text)

    def test_director_offers_new_events(self):
        payload = dict(PAYLOAD, events=[{"id": "horde_nearby"}, {"id": "helicopter"}, {"id": "rescue_signal"}])
        req = build_request("director", payload, {})
        self.assertEqual(sorted(req.json_schema["properties"]["event"]["enum"]),
                         ["helicopter", "horde_nearby", "rescue_signal"])


class RelationEventsTest(unittest.TestCase):
    def test_extort_notes(self):
        notes = [{"kind": "extort_demanded", "clock": "08:00", "faction": "rats", "item": "Painkillers x2"},
                 {"kind": "extort_punished", "clock": "20:00", "faction": "rats"}]
        text = build_request("journal", {"kind": "daily", "lang": "EN", "character": {"name": "A"},
                                         "episodes": [], "notes": notes}, {}).messages[0]["content"]
        self.assertIn("threatened them over the radio, demanding Painkillers x2", text)
        self.assertIn("made good on their threat", text)

    def test_director_new_events(self):
        payload = dict(PAYLOAD, events=[{"id": "friend_gift"}, {"id": "extortion"}])
        req = build_request("director", payload, {})
        self.assertEqual(sorted(req.json_schema["properties"]["event"]["enum"]), ["extortion", "friend_gift"])
