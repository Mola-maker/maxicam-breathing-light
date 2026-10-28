"""SG2002 温度读取工具的纯逻辑测试。"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sg2002_temp import raw_to_mc, sample  # noqa: E402


class ConversionTest(unittest.TestCase):
    def test_known_room_temperature(self):
        # 实测 ch0 raw=904 时 sysfs=43046 m°C。
        self.assertEqual(raw_to_mc(904), 43046)

    def test_negative_temperature_range(self):
        # raw=666 -> -40.161 °C，覆盖 -40 °C 低温场景。
        self.assertEqual(raw_to_mc(666), -40161)
        self.assertLess(raw_to_mc(666), 0)

    def test_extremes(self):
        self.assertEqual(raw_to_mc(0), -273000)
        self.assertEqual(raw_to_mc(8191), 2590650)

    def test_masks_to_13_bits(self):
        self.assertEqual(raw_to_mc(0xF388), raw_to_mc(0x1388))


class SampleTest(unittest.TestCase):
    def test_sysfs_source(self):
        with mock.patch("sg2002_temp.read_sysfs_mc", return_value=43046):
            item = sample("sysfs")
        self.assertEqual(item["source"], "sysfs")
        self.assertEqual(item["temp_mc"], 43046)
        self.assertEqual(item["temp_c"], 43.046)

    def test_reg_source(self):
        with mock.patch("sg2002_temp.read_reg_raw", return_value=904):
            item = sample("reg")
        self.assertEqual(item["source"], "reg")
        self.assertEqual(item["raw"], 904)
        self.assertEqual(item["temp_mc"], 43046)

    def test_auto_falls_back_to_reg(self):
        with mock.patch("sg2002_temp.read_sysfs_mc", side_effect=OSError("x")):
            with mock.patch("sg2002_temp.read_reg_raw", return_value=666):
                item = sample("auto")
        self.assertEqual(item["source"], "reg")
        self.assertEqual(item["temp_mc"], -40161)


if __name__ == "__main__":
    unittest.main()
