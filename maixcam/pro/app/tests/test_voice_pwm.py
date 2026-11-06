"""voice_pwm 纯逻辑测试 (不需要 MaixCAM 硬件)"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice_pwm import (  # noqa: E402
    blink_hz,
    breathing_duty,
    build_config,
    business_brightness,
    decay_step,
)


class ConfigTest(unittest.TestCase):
    def test_default_keyword_is_full_changchun(self):
        # 不增加 chun1/chun~ 之类的二级触发; 只保留完整“长春”门。
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = build_config()
        self.assertEqual(cfg["phrase_keywords"], ("chang2 chun1",))

    def test_decay_defaults(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = build_config()
        self.assertAlmostEqual(cfg["light_threshold"], 35.0)
        self.assertAlmostEqual(cfg["decay_tick_ms"], 20.0)
        self.assertAlmostEqual(cfg["work_decay"], 1.0)
        self.assertAlmostEqual(cfg["release_decay"], 3.0)

    def test_default_pwm_frequency_is_1khz(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            cfg = build_config()
        self.assertEqual(cfg["period_ns"], 1_000_000)

    def test_pwm_frequency_env_override(self):
        with mock.patch.dict(os.environ, {"PWM_FREQ": "2000"}, clear=True):
            cfg = build_config()
        self.assertEqual(cfg["period_ns"], 500_000)


class LampMathTest(unittest.TestCase):
    def test_breathing_bounds(self):
        values = [breathing_duty(t, 4.0, 1.0, 8.0) for t in range(0, 80)]
        self.assertAlmostEqual(min(values), 1.0, delta=0.2)
        self.assertAlmostEqual(max(values), 8.0, delta=0.2)
        self.assertAlmostEqual(breathing_duty(0.0), 1.0, delta=0.01)

    def test_business_above_standby_ceiling(self):
        self.assertAlmostEqual(business_brightness(0.0), 40.0)
        self.assertAlmostEqual(business_brightness(1.0), 100.0)
        self.assertGreater(business_brightness(0.0), 35.0)
        self.assertAlmostEqual(business_brightness(-1.0), 40.0)
        self.assertAlmostEqual(business_brightness(2.0), 100.0)

    def test_blink_increases_with_level(self):
        self.assertAlmostEqual(blink_hz(0.0), 1.0)
        self.assertAlmostEqual(blink_hz(1.0), 8.0)
        self.assertLess(blink_hz(0.25), blink_hz(0.75))

    def test_fast_attack(self):
        # 声音变大: 立即跳到目标, 不经过慢衰减
        self.assertAlmostEqual(decay_step(40.0, 90.0, 1.0, 0.02, 0.02), 90.0)
        self.assertAlmostEqual(decay_step(0.0, 100.0, 1.0, 0.02, 0.02), 100.0)

    def test_slow_work_decay(self):
        light = 100.0
        for _ in range(60):
            light = decay_step(light, 40.0, 1.0, 0.02, 0.02)
        self.assertAlmostEqual(light, 40.0, delta=0.01)
        self.assertAlmostEqual(decay_step(100.0, 40.0, 1.0, 0.02, 0.02), 99.0)

    def test_release_decay_three_per_tick(self):
        light = 40.0
        light = decay_step(light, 0.0, 3.0, 0.02, 0.02)
        self.assertAlmostEqual(light, 37.0)
        light = decay_step(light, 0.0, 3.0, 0.02, 0.02)
        self.assertAlmostEqual(light, 34.0)

    def test_decay_scales_with_dt(self):
        # 半个 tick 只衰减半个单位
        self.assertAlmostEqual(
            decay_step(100.0, 0.0, 1.0, 0.01, 0.02), 99.5)

    def test_decay_clamped(self):
        self.assertAlmostEqual(decay_step(1.0, 0.0, 3.0, 0.02, 0.02), 0.0)
        self.assertAlmostEqual(decay_step(0.0, -10.0, 1.0, 0.02, 0.02), 0.0)


if __name__ == "__main__":
    unittest.main()
