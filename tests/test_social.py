"""NPC 사회생활: 이야기 맥락, 먼저 거는 연락·위기 모드, 공용 주파수 장면."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request  # noqa: E402

STORY = {
    "beat": "You heard a faint voice that might be your daughter.",
    "past": ["You planted beans."],
    "others": [{"id": "casey", "note": "you worry about that kid", "trust": 70, "beat": "Your father is sick."},
               {"id": "bogus", "note": "x"}],
    "news": ["A helicopter flew low over the county today."],
}


class SocialTest(unittest.TestCase):
    def radio(self, **extra):
        payload = {"faction": "ray", "lang": "EN", "trust": 40, "history": [], "story": STORY}
        payload.update(extra)
        return build_request("radio", payload, {"model": "m"})

    def test_story_context_in_persona(self):
        req = self.radio()
        self.assertIn("What is going on in your own life right now: You heard a faint voice", req.system)
        self.assertIn("Earlier in your life since the outbreak: You planted beans.", req.system)
        self.assertIn("- Casey Liu: you worry about that kid; how much they (not you) trust the players: a lot", req.system)
        # 태도는 현재 신뢰도로만 (시작 성향·기록에 끌려가지 않게)
        self.assertIn("Current trust in these players: 40/100.", req.system)
        self.assertIn("How you treat strangers at first (only matters before trust is built)", req.system)
        self.assertIn("This follows the trust number only", req.system)
        self.assertIn('in their own words ("you" means them): Your father is sick.', req.system)
        self.assertIn("Things you have heard lately: A helicopter", req.system)
        self.assertNotIn("bogus", req.system)

    def test_bonds(self):
        story = {"others": [{"id": "casey", "note": "you worry about that kid", "trust": 70, "bond": 3,
                             "shift": "Ray drove a load of supplies over to them"},
                            {"id": "dewey", "bond": -2, "shift": "the players chose to help Casey over Dewey in a crisis"},
                            {"id": "pike", "bond": 0}]}
        sys_text = self.radio(story=story).system
        self.assertIn("feeling now: they are a close friend; what changed it lately: Ray drove", sys_text)
        # 관계표에 없던 사람도 마음이 생기면 들어간다
        self.assertIn("- Dewey Hollis: you did not know them well at first; feeling now: you dislike them", sys_text)
        self.assertNotIn("Pike", sys_text)
        self.assertIn("the feeling now is what counts", sys_text)
        payload = {"lang": "EN", "participants": [
            {"id": "ray", "trust": 70, "relations": [{"id": "rats", "note": "vultures", "bond": -1,
                                                      "shift": "Vic's crew robbed the church"}]},
            {"id": "rats", "trust": 5, "relations": [{"id": "ray", "bond": 1}]}], "log": []}
        text = build_request("radio_scene", payload, {"model": "m"}).messages[0]["content"]
        self.assertIn("about Vic: vultures, feeling now: they are wary of them; what changed it lately: Vic's crew", text)
        self.assertIn("about Ray Mercer: feeling now: they get along", text)

    def test_chat_and_crisis_modes(self):
        chat = self.radio(mode="chat", topic="Tell them about the beans.").messages[0]["content"]
        self.assertIn("You are calling them yourself, just to talk: Tell them about the beans.", chat)
        self.assertNotIn("Trading rules", chat)
        crisis = self.radio(mode="crisis", topic="A truck overturned.").messages[0]["content"]
        self.assertIn("you need their help, but others need it too: A truck overturned.", crisis)
        self.assertIn("ask them to choose to help you", crisis)

    def test_scene(self):
        payload = {"lang": "KO", "day": 4, "clock": "19:00", "players": ["Minsu"],
                   "participants": [{"id": "ray", "trust": 70, "beat": "You planted beans.",
                                     "relations": [{"id": "rats", "note": "vultures"}]},
                                    {"id": "rats", "trust": 5}, {"id": "nobody"}],
                   "log": [{"from": "player", "name": "Minsu", "clock": "18:50", "text": "hello all"},
                           {"from": "npc", "npc": "rats", "clock": "18:51", "text": "who's this"}],
                   "said": {"name": "Minsu", "text": "anyone need help?"}}
        req = build_request("radio_scene", payload, {"model": "m"})
        text = req.messages[0]["content"]
        self.assertIn("- ray = Ray Mercer", text)
        self.assertIn("about Vic: vultures", text)
        self.assertIn('Minsu (a player): "hello all"', text)
        self.assertIn('Vic: "who\'s this"', text)
        self.assertIn('Minsu (one of the players) just said on the open channel: "anyone need help?"', text)
        self.assertIn("Speak only Korean", text)
        self.assertIn("Toward the players this person likes the players", text)
        self.assertIn("Speech level, always the same: warm, easygoing", text)
        # 1:1 무전: 한국어일 때만 말투 수준 고정
        ko = build_request("radio", {"faction": "doc", "lang": "KO", "trust": 30, "history": []}, {"model": "m"})
        self.assertIn("Your speech level in Korean: calm, polite", ko.system)
        en = build_request("radio", {"faction": "doc", "lang": "EN", "trust": 30, "history": []}, {"model": "m"})
        self.assertNotIn("speech level", en.system)
        self.assertIn("Toward the players this person distrusts the players deeply", text)
        self.assertNotIn("cut into a conversation", text)
        cut = build_request("radio_scene", dict(payload, interrupted="They catch up."), {"model": "m"})
        self.assertIn("The player cut into a conversation that was still going on. It was about: They catch up.",
                      cut.messages[0]["content"])
        self.assertEqual(req.json_schema["properties"]["lines"]["items"]["properties"]["speaker"]["enum"], ["ray", "rats"])
        topic = build_request("radio_scene", dict(payload, said=None, topic="They catch up."), {"model": "m"})
        self.assertIn("What they talk about now: They catch up.", topic.messages[0]["content"])
        with self.assertRaises(ModuleError):
            build_request("radio_scene", dict(payload, participants=[{"id": "ray"}]), {"model": "m"})
        self.assertNotIn("offers", req.json_schema["properties"])

    def test_scene_market(self):
        payload = {"lang": "EN", "day": 4, "clock": "19:00", "players": ["Minsu"],
                   "participants": [{"id": "ray", "trust": 70}, {"id": "casey", "trust": 40}],
                   "log": [], "said": {"name": "Minsu", "text": "anyone got food?"},
                   "market": {"max": 3, "sellers": [
                       {"id": "ray", "trust": 70, "goods": [{"category": "food", "maxTier": 4}],
                        "wants": ["medical", "tools"]},
                       {"id": "doc", "trust": 50, "goods": [{"category": "medical", "maxTier": 3}],
                        "wants": ["food", "bogus"]},
                       {"id": "nobody", "goods": [{"category": "food", "maxTier": 1}], "wants": ["food"]}]}}
        req = build_request("radio_scene", payload, {"model": "m"})
        text = req.messages[0]["content"]
        self.assertIn("Trading on this channel (rules from the game)", text)
        self.assertIn("- ray = Ray Mercer: can offer food up to 4", text)
        self.assertIn("accepts payment in medical, tools.", text)
        self.assertIn("- doc = ", text)
        self.assertIn("Not in the conversation so far: speaks only if they make an offer.", text)
        props = req.json_schema["properties"]
        self.assertEqual(props["offers"]["items"]["properties"]["faction"]["enum"], ["ray", "doc"])
        self.assertEqual(props["lines"]["items"]["properties"]["speaker"]["enum"], ["ray", "casey", "doc"])
        self.assertEqual(req.json_schema["required"], ["lines", "offers", "selling"])
        self.assertNotIn("What the player has to trade away", text)
        # 판매 시장: 가진 물건과 모자란 품목을 알려 준다
        sell = dict(payload, market=dict(payload["market"], stock={"food": 24, "ammo": 0, "bogus": 9}))
        sell["market"]["sellers"] = [dict(payload["market"]["sellers"][0], short=["medical", "food"])] + payload["market"]["sellers"][1:]
        stext = build_request("radio_scene", sell, {"model": "m"}).messages[0]["content"]
        self.assertIn("What the player has to trade away (category: total value): food: 24.", stext)
        self.assertIn('set "selling" to that category', stext)
        self.assertIn("Short of medical themselves.", stext)
        # 진행 중인 거래가 있으면 제안 없이 그렇다고 말한다
        closed = build_request("radio_scene", dict(payload, market={"closed": "open_deal"}), {"model": "m"})
        self.assertIn("nobody makes an offer now (they already have a trade going", closed.messages[0]["content"])
        self.assertNotIn("offers", closed.json_schema["properties"])
        # 예약 장면(플레이어가 말하지 않음)에는 시장이 없다
        quiet = build_request("radio_scene", dict(payload, said=None, topic="weather"), {"model": "m"})
        self.assertNotIn("Trading on this channel", quiet.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
