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
        self.assertIn("- Casey Liu: you worry about that kid; they trust the players a lot", req.system)
        self.assertIn('in their own words ("you" means them): Your father is sick.', req.system)
        self.assertIn("Things you have heard lately: A helicopter", req.system)
        self.assertNotIn("bogus", req.system)

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
        self.assertEqual(req.json_schema["properties"]["lines"]["items"]["properties"]["speaker"]["enum"], ["ray", "rats"])
        topic = build_request("radio_scene", dict(payload, said=None, topic="They catch up."), {"model": "m"})
        self.assertIn("What they talk about now: They catch up.", topic.messages[0]["content"])
        with self.assertRaises(ModuleError):
            build_request("radio_scene", dict(payload, participants=[{"id": "ray"}]), {"model": "m"})


if __name__ == "__main__":
    unittest.main()
