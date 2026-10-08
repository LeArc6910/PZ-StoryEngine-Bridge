"""개인 신뢰 (2026-10-09): 멀티 개인 모드에서 무리에 대한 태도와 이 사람에 대한 태도를 따로 넘긴다."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import modules  # noqa: E402

MCFG = {"provider": "mock", "model": "mock"}


def radio(**extra):
    payload = {
        "faction": "doc", "lang": "KO", "trust": 70,
        "history": [{"from": "player", "name": "Gerald Kar", "clock": "21:00", "text": "약 좀 구할 수 있을까요?"}],
    }
    payload.update(extra)
    return modules.build_radio(payload, MCFG)


def persona_of(req):
    """시스템 프롬프트에서 radio.md 를 뺀 페르소나 부분."""
    return req.system[len(modules.load_prompt("radio")):]


class PersonalTrustTest(unittest.TestCase):
    def test_without_personal_is_unchanged(self):
        req = radio()
        self.assertIn("Current trust in these players: 70/100.", req.system)
        self.assertIn("Your attitude toward them right now: " + modules.trust_tone(70), req.system)
        self.assertNotIn("as a group", persona_of(req))
        self.assertNotIn("personally", persona_of(req))

    def test_group_and_person_are_separate(self):
        req = radio(personal={"name": "Gerald Kar", "trust": 35, "known": "new"})
        persona = persona_of(req)
        self.assertIn("Current trust in the players as a group: 70/100.", persona)
        self.assertIn("toward the players as a group right now: " + modules.trust_tone(70), persona)
        self.assertIn("Your own trust in Gerald Kar personally: 35/100.", persona)
        self.assertIn("How well you know Gerald Kar: you barely know them yet.", persona)
        self.assertIn("Your attitude toward Gerald Kar personally: " + modules.trust_tone(35), persona)
        self.assertIn("be polite but careful", persona)
        self.assertIn("not knowing Gerald Kar well enough yet", persona)
        self.assertNotIn("Current trust in these players", persona)

    def test_known_levels_and_warm_person(self):
        well = radio(trust=15, personal={"name": "Gerald Kar", "trust": 85, "known": "well"}).system
        self.assertIn("you know them well", well)
        self.assertIn(modules.trust_tone(85), well)
        self.assertIn("warmer with them than with the group", well)
        little = radio(personal={"name": "Gerald Kar", "trust": 45, "known": "little"}).system
        self.assertIn("you have dealt with them a little", little)
        odd = radio(personal={"name": "Gerald Kar", "trust": 45, "known": "???"}).system
        self.assertNotIn("How well you know", odd)

    def test_speech_level_stays_fixed(self):
        req = radio(personal={"name": "Gerald Kar", "trust": 90, "known": "well"})
        self.assertIn("Use this same speech level in every message", req.system)

    def test_personal_trust_is_clamped_and_defaults(self):
        high = radio(personal={"name": "Gerald Kar", "trust": 400}).system
        self.assertIn("personally: 100/100.", high)
        missing = radio(personal={"name": "", "known": "new"}).system
        self.assertIn("Your own trust in this person personally: 70/100.", missing)

    def test_prompt_explains_two_attitudes(self):
        self.assertIn("two trust numbers", modules.load_prompt("radio"))


if __name__ == "__main__":
    unittest.main()
