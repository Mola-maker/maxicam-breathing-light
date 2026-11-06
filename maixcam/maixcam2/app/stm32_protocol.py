"""MaixCAM <-> STM32 SPI v1 frame/TLV reference implementation.

This module is intentionally host-testable.  It can be copied to the MaixCAM
application or used on a PC with a fake SPI transport.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

FRAME_SIZE = 64
MAX_PAYLOAD = 44
PROTOCOL_VERSION = 1

MAGIC = 0xA55A
TYPE_CONTROL = 0x01
TYPE_STATUS = 0x81

TLV_HELLO = 0x01
TLV_TEMP = 0x02
TLV_PERFORM = 0x10
TLV_HEARTBEAT = 0x20
TLV_THERMAL_CONFIG = 0x30
TLV_ALL_OFF = 0x7F

TLV_STATUS = 0x81
TLV_CAPS = 0x82

ACTION_STANDBY = 0
ACTION_GATE = 1
ACTION_RELEASE = 2
ACTION_EGG = 3
ACTION_OFF = 4

LINK_BOOT = 0
LINK_WAIT_HELLO = 1
LINK_ACTIVE = 2
LINK_LOST = 3
LINK_FAULT = 4

FAULT_CRC = 1 << 0
FAULT_FORMAT = 1 << 1
FAULT_SPI = 1 << 2
FAULT_UNKNOWN_TLV = 1 << 3
FAULT_NEED_HELLO = 1 << 4
FAULT_TEMP_STALE = 1 << 5
FAULT_TEMP_INVALID = 1 << 6
FAULT_HEATER_UNSUPPORTED = 1 << 7
FAULT_BAD_MASK = 1 << 8
FAULT_PROTOCOL = 1 << 9
FAULT_LINK_LOST = 1 << 10

FEATURE_PERFORM = 1 << 0
FEATURE_TEMP = 1 << 1
FEATURE_HEARTBEAT = 1 << 2
FEATURE_EGG = 1 << 3
FEATURE_THERMAL_PID = 1 << 4
FEATURE_DIRECT = 1 << 5


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def tlv(type_: int, value: bytes) -> bytes:
    if len(value) > 255:
        raise ValueError("TLV value too large")
    return bytes((type_, len(value))) + value


def build_frame(type_: int, seq: int, session_id: int, payload: bytes,
                flags: int = 0) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload must be <= {MAX_PAYLOAD} bytes")
    header = struct.pack(
        "<HBBIIHH",
        MAGIC,
        PROTOCOL_VERSION,
        type_,
        seq & 0xFFFFFFFF,
        session_id & 0xFFFFFFFF,
        len(payload),
        flags & 0xFFFF,
    )
    body = header + payload + bytes(MAX_PAYLOAD - len(payload))
    crc = crc16_ccitt(body[:60])
    return body + struct.pack("<HH", crc, 0)


def parse_frame(frame: bytes) -> dict:
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"frame must be {FRAME_SIZE} bytes")
    magic, version, type_, seq, session_id, payload_len, flags = struct.unpack(
        "<HBBIIHH", frame[:16]
    )
    if magic != MAGIC:
        raise ValueError("bad magic")
    if version != PROTOCOL_VERSION:
        raise ValueError("bad version")
    if payload_len > MAX_PAYLOAD:
        raise ValueError("bad payload length")
    crc_expected, reserved = struct.unpack("<HH", frame[60:64])
    if crc_expected != crc16_ccitt(frame[:60]):
        raise ValueError("bad crc")
    if reserved != 0:
        raise ValueError("bad reserved field")
    return {
        "version": version,
        "type": type_,
        "seq": seq,
        "session_id": session_id,
        "payload_len": payload_len,
        "flags": flags,
        "payload": frame[16:16 + payload_len],
    }


def parse_tlvs(payload: bytes) -> list[tuple[int, bytes]]:
    result = []
    offset = 0
    while offset + 2 <= len(payload):
        type_, length = payload[offset], payload[offset + 1]
        offset += 2
        if offset + length > len(payload):
            raise ValueError("truncated TLV")
        result.append((type_, payload[offset:offset + length]))
        offset += length
    if offset != len(payload):
        raise ValueError("trailing TLV bytes")
    return result


def hello(heartbeat_ms: int = 1000, features: int = 0) -> bytes:
    return tlv(TLV_HELLO, struct.pack("<BBHI", 1, 1,
                                     heartbeat_ms & 0xFFFF,
                                     features & 0xFFFFFFFF))


def temp(temp_mc: int, sample_seq: int, age_ms: int,
         valid: bool = True, source: int = 0xFF) -> bytes:
    return tlv(TLV_TEMP, struct.pack("<iHHBB", int(temp_mc),
                                     sample_seq & 0xFFFF,
                                     age_ms & 0xFFFF,
                                     1 if valid else 0,
                                     source & 0xFF))


def perform(glyph_mask: int, action: int, event_seq: int,
            profile_id: int = 0, value: int = 0) -> bytes:
    return tlv(TLV_PERFORM, struct.pack("<IBBIH",
                                        glyph_mask & 0xFFFFFFFF,
                                        action & 0xFF,
                                        profile_id & 0xFF,
                                        event_seq & 0xFFFFFFFF,
                                        value & 0xFFFF))


def heartbeat(maix_uptime_ms: int, state_flags: int = 0) -> bytes:
    return tlv(TLV_HEARTBEAT, struct.pack("<IHH",
                                          maix_uptime_ms & 0xFFFFFFFF,
                                          state_flags & 0xFFFF,
                                          0))


def all_off() -> bytes:
    return tlv(TLV_ALL_OFF, b"")


@dataclass
class Status:
    last_control_seq: int
    last_event_seq: int
    active_mask: int
    stm32_uptime_ms: int
    fault_flags: int
    temp_mc: int
    temp_age_ms: int
    temp_valid: bool
    link_state: int
    temp_sample_seq: int
    temp_source: int
    glyph_state: tuple[int, ...]


def parse_status(frame: bytes) -> tuple[Status, dict]:
    parsed = parse_frame(frame)
    if parsed["type"] != TYPE_STATUS:
        raise ValueError("not a status frame")
    status = None
    caps: dict = {}
    for type_, value in parse_tlvs(parsed["payload"]):
        if type_ == TLV_STATUS:
            if len(value) < 29:
                raise ValueError("status too short")
            fixed = struct.unpack("<IIIIHiHBBHB", value[:29])
            status = Status(
                last_control_seq=fixed[0],
                last_event_seq=fixed[1],
                active_mask=fixed[2],
                stm32_uptime_ms=fixed[3],
                fault_flags=fixed[4],
                temp_mc=fixed[5],
                temp_age_ms=fixed[6],
                temp_valid=bool(fixed[7]),
                link_state=fixed[8],
                temp_sample_seq=fixed[9],
                temp_source=fixed[10],
                glyph_state=tuple(value[29:]),
            )
        elif type_ == TLV_CAPS and len(value) == 8:
            version, glyph_count, pwm_count, reserved, features = struct.unpack(
                "<BBBBI", value
            )
            caps = {
                "protocol_version": version,
                "glyph_count": glyph_count,
                "pwm_channel_count": pwm_count,
                "reserved": reserved,
                "features": features,
            }
    if status is None:
        raise ValueError("missing STATUS TLV")
    return status, caps
