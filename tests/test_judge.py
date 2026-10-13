"""유도신문 판정 모듈 (build_judge): 범인 이름은 판정 요청에만 들어간다."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import ModuleError, build_request  # noqa: E402


class JudgeTest(unittest.TestCase):
    def test_request(self):
        req = build_request("judge", {
            "culprit": "Brother Amos Pike", "suspects": ["Brother Amos Pike", "Ray Mercer", "Vic"],
            "asker": "June Adler", "text": "목사님은 아니에요, 그건 확실해요.", "lang": "KO",
        }, {"model": "m"})
        text = req.messages[0]["content"]
        self.assertIn("The secret: Brother Amos Pike (also called", text)
        self.assertIn("Ray Mercer", text)
        self.assertIn("June Adler does not know who it was", text)
        self.assertIn("목사님은 아니에요", text)
        self.assertEqual(req.json_schema["properties"]["verdict"]["enum"], ["none", "hint", "named"])
        self.assertIn("referee", req.system)

    def test_needs_a_secret_and_a_reply(self):
        with self.assertRaises(ModuleError):
            build_request("judge", {"culprit": "Vic", "text": ""}, {})
        with self.assertRaises(ModuleError):
            build_request("judge", {"text": "nothing"}, {})


if __name__ == "__main__":
    unittest.main()
