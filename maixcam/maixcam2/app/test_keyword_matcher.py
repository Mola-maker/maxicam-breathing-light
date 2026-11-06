import unittest
from pathlib import Path

import keyword_matcher as km


class MatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = Path(__file__).resolve().parent.parent / "config" / "keywords.json"
        cls.cfg = km.load_config(cfg)

    def test_phrase(self):
        r = km.match_text("长春。", self.cfg)
        self.assertTrue(r["gate"])
        self.assertEqual(r["glyph_mask"], 3)
        self.assertEqual(r["reason"], "phrase")

    def test_chang_chun_sequence(self):
        r = km.match_text("长 春", self.cfg)
        self.assertTrue(r["gate"])
        self.assertEqual(r["reason"], "phrase")

    def test_single_chang_is_not_gate(self):
        r = km.match_text("长", self.cfg)
        self.assertFalse(r["gate"])
        self.assertEqual(r["matches"][0]["family"], "chang")
        self.assertIn("chang2", r["matches"][0]["registered_keywords"])

    def test_single_chun_is_not_gate(self):
        r = km.match_text("春", self.cfg)
        self.assertFalse(r["gate"])
        self.assertEqual(r["reason"], "chun")

    def test_ang_is_debug_only(self):
        r = km.match_text("昂", self.cfg)
        self.assertFalse(r["gate"])
        self.assertEqual(r["matches"][0]["family"], "ang")

    def test_empty(self):
        r = km.match_text("。！？", self.cfg)
        self.assertFalse(r["gate"])
        self.assertEqual(r["normalized"], "")


if __name__ == "__main__":
    unittest.main()
