"""NPC 손편지 (letter 모듈)와 일지의 "편지를 읽었다" 메모."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request, format_note  # noqa: E402


class LetterTest(unittest.TestCase):
    def build(self, **extra):
        payload = {"faction": "doc", "lang": "KO", "reason": "gift", "to": "Gerald Kar", "trust": 75,
                   "memory": "Gerald brought antibiotics once.",
                   "story": {"beat": "The clinic's roof is leaking."},
                   "life": {"state": {"food": 60, "medical": 15, "safety": 50, "morale": 40}}}
        payload.update(extra)
        return build_request("letter", payload, {"model": "m"})

    def test_prompt(self):
        req = self.build()
        text = req.messages[0]["content"]
        self.assertIn("Language: Korean", text)
        self.assertIn("Writer: June Adler (", text)
        self.assertIn("Writer's speech level, always the same, also in writing:", text)
        self.assertIn("What the writer remembers from radio talks with the players: Gerald brought", text)
        self.assertIn("The clinic's roof is leaking.", text)
        self.assertIn("Reader: Gerald Kar, one of the players.", text)
        self.assertIn("leaving a small package of supplies", text)
        self.assertEqual(req.json_schema["required"], ["title", "text"])
        self.assertIn("80 to 150 words", req.system)

    def test_reasons(self):
        farewell = self.build(reason="farewell", extra="Ray set out for Louisville to find his daughter.",
                              faction="ray", lang="EN").messages[0]["content"]
        self.assertIn("You are leaving for good", farewell)
        self.assertIn("Louisville to find his daughter", farewell)
        self.assertNotIn("speech level", farewell)
        project = self.build(reason="project", extra="the greenhouse").messages[0]["content"]
        self.assertIn("big project (the greenhouse) is finally finished", project)
        with self.assertRaises(ModuleError):
            self.build(reason="ransom")
        with self.assertRaises(ModuleError):
            self.build(faction="nobody")

    def test_journal_note(self):
        line = format_note({"kind": "letter_read", "faction": "doc", "clock": "14:20", "text": "Take care of that cough."},
                           "EN")
        self.assertIn("14:20 read a handwritten letter from June Adler", line)
        self.assertIn('"Take care of that cough."', line)


if __name__ == "__main__":
    unittest.main()
