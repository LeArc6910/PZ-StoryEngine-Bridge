"""AI 곁가지 (episode 모듈, 모드 AiTales.lua)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request, item_words  # noqa: E402


class EpisodeTest(unittest.TestCase):
    def build(self, **extra):
        payload = {"faction": "ray", "lang": "KO", "kind": "items", "tier": 2,
                   "why": "the farmhouse well pump broke", "items": [{"item": "Base.WaterRationCan", "count": 4}],
                   "trust": 55, "season": "fall", "world": ["no power"], "players": ["Gerald Kar"],
                   "story": {"beat": "Annie and Lily live at the farm now."},
                   "recent": [{"title": "길 잃은 개", "beat": "A stray dog followed you home."}]}
        payload.update(extra)
        return build_request("episode", payload, {"model": "m"})

    def test_item_request(self):
        req = self.build()
        text = req.messages[0]["content"]
        self.assertIn("Language for say, tale and title: Korean", text)
        self.assertIn("You are Ray Mercer", text)
        self.assertIn("4 x Water Ration Can", text)
        self.assertIn("Size of the request: 2 of 5.", text)
        self.assertIn("Annie and Lily live at the farm now.", text)
        self.assertIn("County conditions now: no power.", text)
        self.assertIn("do not repeat them", text)
        self.assertIn("A stray dog followed you home.", text)
        self.assertEqual(req.json_schema["required"], ["title", "start", "why", "win", "lose"])
        self.assertEqual(req.module, "episode")
        self.assertIn("Do not invent big events", req.system)

    def test_quiet_and_horde(self):
        quiet = self.build(kind="quiet", items=[])
        self.assertEqual(quiet.json_schema["required"], ["title", "start", "end", "tone"])
        self.assertNotIn("The items you ask for", quiet.messages[0]["content"])
        horde = self.build(kind="horde")
        self.assertIn("clear a group of the dead", horde.messages[0]["content"])
        self.assertNotIn("The items you ask for", horde.messages[0]["content"])

    def test_successor_voice(self):
        text = self.build(voices={"ray": "martha"}).messages[0]["content"]
        self.assertIn("Martha", text)
        self.assertNotIn("You are Ray Mercer", text)

    def test_bad_payload(self):
        with self.assertRaises(ModuleError):
            self.build(kind="war")
        with self.assertRaises(ModuleError):
            self.build(items=[])
        with self.assertRaises(ModuleError):
            self.build(faction="nobody")

    def test_item_words(self):
        self.assertEqual(item_words("Base.TinnedBeans"), "Tinned Beans")
        self.assertEqual(item_words("Base.Bullets9mmBox"), "Bullets 9mm Box")
        self.assertEqual(item_words("Base.556Box"), "556 Box")


if __name__ == "__main__":
    unittest.main()
