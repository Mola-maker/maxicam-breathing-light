"""用两份逆向文档中的抓包报文校验协议编码"""

import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P  # noqa: E402


def wire(seq, payload):
    proto = P.SurplifeProtocol()
    proto._seq = seq - 1
    chunks = proto.encode(P.CMD_CONTROL, payload)
    assert len(chunks) == 1
    return chunks[0].hex()


class TransportTest(unittest.TestCase):
    def test_single_packets_match_capture(self):
        self.assertEqual(wire(3, P.cmd_power(False)), "0003800000020" "30a7124")
        self.assertEqual(wire(2, P.cmd_query_status()), "00028000000506" "0aea818a8b59")
        self.assertEqual(wire(4, bytes.fromhex("e20b57ff")), "0004800000040" "50ae20b57ff")

    def test_segmentation(self):
        proto = P.SurplifeProtocol(mtu=23)
        payload = bytes(range(50))
        chunks = proto.encode(P.CMD_CONTROL, payload)
        self.assertTrue(all(len(c) <= 20 for c in chunks))
        self.assertEqual(chunks[0][0], 0x40)
        self.assertEqual(chunks[-1][2] & 0x80, 0x80)
        body = chunks[0][7:] + b"".join(c[5:] for c in chunks[1:])
        self.assertEqual(body, bytes([0x0A]) + payload)

    def test_decode_status(self):
        raw = bytes.fromhex("0401800000191a15ea810100c20623670b64f00000000000010190000001020300")
        msg = P.SurplifeProtocol.decode(raw)
        self.assertEqual(msg["cmd_id"], 0x15)
        st = P.parse_status(msg["payload"])
        self.assertTrue(st["power"])
        self.assertEqual(st["model"], "00C2")
        self.assertEqual(st["mode"], "effect")
        off = P.parse_status(bytes.fromhex("ea810100c20324720550f00000000000010190000401020100"))
        self.assertFalse(off["power"])


class CommandTest(unittest.TestCase):
    def test_time_sync_checksum(self):
        # ge0rg: 1014190b040d1e1702000f9f ; marcelrv: 1014190b1c1320260500 0fd1
        self.assertEqual(P.cmd_time_sync(datetime(2025, 11, 4, 13, 30, 23)).hex(),
                         "1014190b040d1e1702000f9f")
        self.assertEqual(P.cmd_time_sync(datetime(2025, 11, 28, 19, 32, 38)).hex(),
                         "1014190b1c1320260500" "0fd1")

    def test_hsv16_reference_colors(self):
        self.assertEqual(P.hsv16(0, 100, 100), 0x01FF)       # red
        self.assertEqual(P.hsv16(0, 0, 100), 0x001F)         # white
        self.assertEqual(P.hsv16(120, 100, 100), 0x51FF)     # green
        self.assertEqual(P.hsv16(240, 100, 100), 0xA1FF)     # blue
        self.assertEqual(P.rgb_to_hsv16(255, 0, 0), 0x01FF)
        self.assertEqual(P.rgb_to_hsv16(0, 0, 0), 0x0000)

    def test_effect(self):
        self.assertEqual(P.cmd_effect(5, 0x50, 0x50).hex(), "e00200055050")

    def test_text_config_capture(self):
        self.assertEqual(P.cmd_text_config(0, 0x01, "left").hex(),
                         "e2050201000064640000000000000102")
        self.assertEqual(P.cmd_text_config(0, 0x01, "down").hex(),
                         "e2050201000064640000000000000105")

    def test_text_bitmap_layout(self):
        glyphs = [[0x7FC0, 0x4400, 0x4400, 0x4400, 0x4000, 0, 0]]
        self.assertEqual(P.cmd_text_bitmap(glyphs).hex(),
                         "e20400000c7fc0440044004400400000000000")

    def test_music_capture(self):
        expected = ("e10500640300006400000000000000000000000000000000"
                    "00a100000006a1006464a1966464a1786464a15a6464a13c6464a11e6464")
        self.assertEqual(P.cmd_music_device(3, 100, 100).hex(), expected)

    def test_pixel_mask(self):
        m = P.pixel_mask([(0, 0), (19, 19)])
        self.assertEqual(m[0], 0x80)
        self.assertEqual(m[-1], 0x01)
        self.assertEqual(len(P.cmd_paint(0x01FF, m)), 55)

    def test_render_text(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest("Pillow 未安装")
        glyphs = P.render_text_glyphs("Hi")
        self.assertEqual(len(glyphs), 2)
        self.assertTrue(any(glyphs[0]))


if __name__ == "__main__":
    unittest.main()
