"""대화 맥락 (2026-10-04): 플레이어 몸 상태, NPC 특기 안내, 답하는 장면 줄 수, 되묻기 금지 규칙."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modules  # noqa: E402

MCFG = {"provider": "mock", "model": "mock"}
STATE = {"hp": 60, "wounds": [{"part": "Neck", "kind": "cut", "bandaged": True},
                              {"part": "Torso_Lower", "kind": "deep", "bleeding": True}]}


class DialogContextTest(unittest.TestCase):
    def test_player_state_line(self):
        line = modules.format_player_state("Jerry", STATE)
        self.assertIn("hurt", line)
        self.assertIn("cut (laceration) on the neck (bandaged)", line)
        self.assertIn("deep wound on the stomach (bleeding)", line)
        self.assertIn("do not ask about them again", line)
        self.assertIsNone(modules.format_player_state("Jerry", None))

    def test_specialty_line_uses_ui_names(self):
        ko = modules.format_specialty("doc", {"tier": 1, "wait": 0}, "KO")
        self.assertIn('"특기" button', ko)
        self.assertIn('"거점" tab', ko)
        self.assertIn("yes, you can do it now", ko)
        wait = modules.format_specialty("doc", {"tier": 1, "wait": 30, "reason": "cooldown"}, "EN")
        self.assertIn("about 30 more hours", wait)
        self.assertIsNone(modules.format_specialty("doc", {"reason": "gone"}, "EN"))

    def test_radio_reply_gets_state_and_rules(self):
        req = modules.build_radio({
            "faction": "doc", "lang": "KO", "trust": 45,
            "history": [{"from": "player", "name": "Jerry", "clock": "21:00", "text": "괜찮아요"}],
            "speakerState": STATE, "specialty": {"tier": 1, "wait": 0}, "trade": {"allowed": False},
        }, MCFG)
        user = req.messages[0]["content"]
        self.assertIn("How Jerry is right now", user)
        self.assertIn("Never ask again something they already answered", req.system)
        self.assertIn("What you can do for them", req.system)

    def test_reply_scene_is_shorter(self):
        req = modules.build_radio_scene({
            "lang": "KO", "participants": [{"id": "doc", "trust": 45, "specialty": {"tier": 1, "wait": 0}},
                                           {"id": "ray", "trust": 55}],
            "log": [], "said": {"name": "Jerry", "text": "괜찮아요", "state": STATE},
        }, MCFG)
        user = req.messages[0]["content"]
        self.assertIn("Write 2 to 4 lines", user)
        self.assertIn("How Jerry is right now", user)
        self.assertIn("Their special skill", user)
        self.assertNotIn("What you can do for them", user)


if __name__ == "__main__":
    unittest.main()
