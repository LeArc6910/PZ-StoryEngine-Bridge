"""후임 목소리 (2026-10-07): payload.voices 가 있으면 그 채널의 이름·성격·말투를 후임으로 바꾼다."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modules  # noqa: E402

MCFG = {"provider": "mock", "model": "mock"}
PAYLOAD = {
    "faction": "ray", "lang": "KO", "trust": 30,
    "history": [{"from": "player", "name": "Jerry", "clock": "21:00", "text": "누구세요?"}],
    "trade": {"allowed": False},
}


def prompt_of(req):
    return req.system + "\n" + "\n".join(m["content"] for m in req.messages)


class VoicesTest(unittest.TestCase):
    def test_successor_persona_replaces_the_original(self):
        payload = dict(PAYLOAD, voices={"ray": "martha"})
        text = prompt_of(modules.build_request("radio", payload, MCFG))
        self.assertIn("Martha Cole", text)
        self.assertIn("마사 콜", text)
        self.assertNotIn("former long-haul trucker", text)
        self.assertIn("Never 존댓말", text)

    def test_without_voices_nothing_changes(self):
        text = prompt_of(modules.build_request("radio", dict(PAYLOAD), MCFG))
        self.assertIn("Ray Mercer", text)
        self.assertNotIn("Martha Cole", text)

    def test_voices_do_not_leak_between_requests(self):
        modules.build_request("radio", dict(PAYLOAD, voices={"ray": "martha"}), MCFG)
        self.assertEqual(modules.PERSONAS.get("ray")["name"], "Ray Mercer")

    def test_every_voice_is_complete(self):
        for vid, v in modules.VOICES.items():
            for key in ("name", "local", "who", "trust", "speech"):
                self.assertIn(key, v, vid)
            self.assertIn("KO", v["speech"], vid)


if __name__ == "__main__":
    unittest.main()
