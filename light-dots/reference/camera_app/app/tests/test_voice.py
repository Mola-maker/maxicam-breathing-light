"""关键词门槛 + 音量打分逻辑"""

import array
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice_kws import (  # noqa: E402
    KeywordTrigger, ScoreState, VolumeMeter, score_color, volume_score,
)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def tone(amplitude: int, n: int = 1600) -> bytes:
    return array.array("h", [int(amplitude * math.sin(i / 5)) for i in range(n)]).tobytes()


class KeywordTriggerTest(unittest.TestCase):
    def test_one_utterance_triggers_once(self):
        clk = FakeClock()
        t = KeywordTrigger(0.5, 2.0, clk)
        hits = []
        for p in [0.0, 0.6, 0.9, 0.95, 0.7, 0.1]:
            clk.t += 0.1
            hits.append(t.feed(p))
        self.assertEqual(hits.count(True), 1)

    def test_rearm_needs_drop_and_cooldown(self):
        clk = FakeClock()
        t = KeywordTrigger(0.5, 2.0, clk)
        self.assertTrue(t.feed(0.9))
        clk.t = 1.0
        t.feed(0.0)
        self.assertFalse(t.feed(0.9))   # 冷却未到
        clk.t = 3.5
        t.feed(0.0)
        self.assertTrue(t.feed(0.9))

    def test_hit_cooldown(self):
        clk = FakeClock()
        t = KeywordTrigger(0.5, 2.0, clk)
        self.assertTrue(t.hit())
        clk.t = 1.0
        self.assertFalse(t.hit())
        clk.t = 2.5
        self.assertTrue(t.hit())


class VolumeTest(unittest.TestCase):
    def test_louder_is_higher(self):
        quiet, loud = VolumeMeter(), VolumeMeter()
        quiet.feed(tone(300))
        loud.feed(tone(10000))
        self.assertGreater(loud.db, quiet.db)
        self.assertGreater(volume_score(loud.db), volume_score(quiet.db))

    def test_full_scale_and_silence(self):
        m = VolumeMeter()
        m.feed(tone(32767))
        self.assertAlmostEqual(m.db, -3.0, delta=0.2)   # 正弦波 RMS = 峰值 / sqrt(2)
        m.feed(bytes(3200))
        self.assertEqual(m.db, VolumeMeter.SILENCE_DB)

    def test_peak_window(self):
        clk = FakeClock()
        m = VolumeMeter(window=1.0, clock=clk)
        m.feed(tone(10000))
        loud = m.db
        clk.t = 0.5
        m.feed(tone(100))
        self.assertEqual(m.peak_db, loud)              # 窗口内保持峰值
        clk.t = 2.0
        m.feed(tone(100))
        self.assertLess(m.peak_db, loud)               # 窗口过后回落

    def test_odd_length_chunks(self):
        m = VolumeMeter()
        data = tone(5000)
        m.feed(data[:101])
        m.feed(data[101:])
        whole = VolumeMeter()
        whole.feed(data)
        self.assertAlmostEqual(m.db, whole.db, delta=1.0)

    def test_volume_score_mapping(self):
        self.assertEqual(volume_score(-60), 0)
        self.assertEqual(volume_score(-50), 0)
        self.assertEqual(volume_score(-30), 50)
        self.assertEqual(volume_score(-10), 100)
        self.assertEqual(volume_score(0), 100)
        with self.assertRaises(ValueError):
            volume_score(-30, -10, -50)


class ScoreStateTest(unittest.TestCase):
    def test_update_and_hits(self):
        st = ScoreState(history=3)
        st.update(0.8, 42)
        self.assertAlmostEqual(st.keyword, 80)
        self.assertEqual(st.volume, 42)
        self.assertEqual(st.history, [0, 0, 42])
        self.assertIsNone(st.score)
        st.record_hit(70)
        st.record_hit(55)
        self.assertEqual((st.score, st.best, st.hits), (55, 70, 2))

    def test_clamp(self):
        st = ScoreState(history=2)
        st.update(1.7, 150)
        self.assertEqual((st.keyword, st.volume), (100, 100))

    def test_score_color(self):
        self.assertEqual(score_color(60, 50), (40, 220, 90))
        self.assertNotEqual(score_color(10, 50), score_color(60, 50))


if __name__ == "__main__":
    unittest.main()
