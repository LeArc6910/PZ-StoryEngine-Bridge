"""복구 작전 일지 메모 (게임 Ops.lua 가 영어 문장을 만들어 보낸다)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules import RECORD_TEXT, format_note  # noqa: E402


class OpsNoteTest(unittest.TestCase):
    def test_op_note_uses_given_text(self):
        note = {"kind": "op", "clock": "09:10", "text": "the survivors got the county's power working again"}
        self.assertEqual(format_note(note, "EN"), "09:10 the survivors got the county's power working again")

    def test_empty_op_note_is_dropped(self):
        self.assertIsNone(format_note({"kind": "op", "text": ""}, "EN"))

    def test_life_record_text(self):
        self.assertIn("operation_done", RECORD_TEXT)


if __name__ == "__main__":
    unittest.main()
