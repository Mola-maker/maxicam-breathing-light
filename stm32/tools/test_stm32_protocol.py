"""Host-side tests for the SPI v1 frame/TLV reference."""

from __future__ import annotations

import struct
import unittest

import stm32_protocol as p


class CrcTest(unittest.TestCase):
    def test_ccitt_reference_vector(self):
        self.assertEqual(p.crc16_ccitt(b"123456789"), 0x29B1)


class FrameTest(unittest.TestCase):
    def test_frame_round_trip(self):
        payload = p.temp(-40161, 9, 120, True, 0)
        frame = p.build_frame(p.TYPE_CONTROL, 7, 0x12345678, payload)
        self.assertEqual(len(frame), p.FRAME_SIZE)
        parsed = p.parse_frame(frame)
        self.assertEqual(parsed["type"], p.TYPE_CONTROL)
        self.assertEqual(parsed["seq"], 7)
        self.assertEqual(parsed["session_id"], 0x12345678)
        self.assertEqual(parsed["payload"], payload)
        self.assertEqual(p.parse_tlvs(parsed["payload"]),
                         [(p.TLV_TEMP, payload[2:])])

    def test_crc_corruption_rejected(self):
        frame = bytearray(p.build_frame(p.TYPE_CONTROL, 1, 1,
                                        p.hello()))
        frame[20] ^= 0x01
        with self.assertRaises(ValueError):
            p.parse_frame(bytes(frame))


class CommandTest(unittest.TestCase):
    def test_temp_layout(self):
        raw = p.temp(-40161, 0x1234, 500, True, 1)
        self.assertEqual(raw[0], p.TLV_TEMP)
        self.assertEqual(raw[1], 10)
        temp_mc, seq, age, valid, source = struct.unpack("<iHHBB", raw[2:])
        self.assertEqual(temp_mc, -40161)
        self.assertEqual(seq, 0x1234)
        self.assertEqual(age, 500)
        self.assertEqual(valid, 1)
        self.assertEqual(source, 1)

    def test_perform_layout(self):
        raw = p.perform(0x3, p.ACTION_GATE, 11, 0, 0)
        self.assertEqual(raw[0], p.TLV_PERFORM)
        self.assertEqual(raw[1], 12)
        mask, action, profile, event, value = struct.unpack("<IBBIH", raw[2:])
        self.assertEqual((mask, action, profile, event, value),
                         (3, p.ACTION_GATE, 0, 11, 0))


class StatusTest(unittest.TestCase):
    def test_status_and_caps(self):
        status_value = struct.pack(
            "<IIIIHiHBBHB",
            7, 3, 0x3, 1234, p.FAULT_LINK_LOST,
            43046, 100, 1, p.LINK_ACTIVE, 42, 0,
        ) + bytes((2, 3))
        caps_value = struct.pack("<BBBBI", 1, 2, 15, 0,
                                 p.FEATURE_PERFORM | p.FEATURE_TEMP)
        payload = p.tlv(p.TLV_STATUS, status_value) + p.tlv(p.TLV_CAPS, caps_value)
        frame = p.build_frame(p.TYPE_STATUS, 9, 0xABCD, payload)
        status, caps = p.parse_status(frame)
        self.assertEqual(status.last_control_seq, 7)
        self.assertEqual(status.last_event_seq, 3)
        self.assertEqual(status.active_mask, 0x3)
        self.assertEqual(status.temp_mc, 43046)
        self.assertTrue(status.temp_valid)
        self.assertEqual(status.link_state, p.LINK_ACTIVE)
        self.assertEqual(status.glyph_state, (2, 3))
        self.assertEqual(caps["glyph_count"], 2)
        self.assertEqual(caps["pwm_channel_count"], 15)


if __name__ == "__main__":
    unittest.main()
