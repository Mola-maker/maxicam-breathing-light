"""Minimal MaixCAM SPI master link for the STM32 PWM-Heater board.

This is a transport/reference module, not yet wired into voice_pwm.py.

Typical use from a lightweight link process:

    link = Stm32SpiLink()
    link.set_temp(temp_mc, sample_seq, age_ms, valid=True)
    link.queue_perform(glyph_mask=0x3, action=ACTION_GATE)
    while running:
        status = link.transaction()
        ...
        time.sleep(0.05)

The STM32 parses a request after the SPI transaction, so its STATUS response
is observed on the next transaction.  Pending PERFORM events are resent until
STATUS.last_event_seq acknowledges them.
"""

from __future__ import annotations

import os
import threading
import time

import stm32_protocol as p


class Stm32SpiLink:
    def __init__(self, spi_id: int | None = None,
                 frequency: int = 1_000_000,
                 session_id: int | None = None):
        from maix import err, pinmap, spi, sys

        if sys.device_id() == "maixcam2":
            # MaixCAM2 external SPI2, hardware CS1 -> /dev/spidev2.1
            pins = {
                "B20": "SPI2_SCK",
                "B19": "SPI2_MISO",
                "B21": "SPI2_CS1",
                "B18": "SPI2_MOSI",
            }
            default_spi_id = 2
        else:
            # MaixCAM / MaixCAM-Pro SPI4
            pins = {
                "A22": "SPI4_SCK",
                "A23": "SPI4_MISO",
                "A24": "SPI4_CS",
                "A25": "SPI4_MOSI",
            }
            default_spi_id = 4

        for pin, function in pins.items():
            err.check_raise(pinmap.set_pin_function(pin, function),
                            f"pinmap {pin} -> {function} failed")

        self._spi = spi.SPI(default_spi_id if spi_id is None else spi_id,
                            spi.Mode.MASTER, frequency,
                            polarity=0, phase=0, bits=8)
        self.session_id = session_id or (
            int.from_bytes(os.urandom(4), "little") or 1
        )
        self.seq = 1
        self._event_seq = 1
        self._hello_pending = True
        self._pending_event: tuple[bytes, int] | None = None
        self._temp: bytes | None = None
        self._temp_sent_at = 0.0
        self._last_status = None
        self._last_caps = None
        self._started = time.monotonic()
        self._lock = threading.Lock()

    @property
    def status(self):
        return self._last_status

    @property
    def caps(self):
        return self._last_caps

    def set_temp(self, temp_mc: int, sample_seq: int, age_ms: int,
                 valid: bool = True, source: int = 0):
        with self._lock:
            self._temp = p.temp(temp_mc, sample_seq, age_ms, valid, source)

    def queue_perform(self, glyph_mask: int, action: int,
                      profile_id: int = 0, value: int = 0) -> int:
        event_seq = self._event_seq
        self._event_seq += 1
        event = p.perform(glyph_mask, action, event_seq, profile_id, value)
        with self._lock:
            self._pending_event = (event, event_seq)
        return event_seq

    def queue_all_off(self) -> None:
        with self._lock:
            self._pending_event = (p.all_off(), -1)

    def _payload(self, now: float) -> bytes:
        # Caller holds self._lock.
        chunks: list[bytes] = []

        if self._hello_pending:
            chunks.append(p.hello(heartbeat_ms=50,
                                  features=p.FEATURE_PERFORM | p.FEATURE_TEMP))
        elif self._temp is not None and (now - self._temp_sent_at) >= 1.0:
            chunks.append(self._temp)
            self._temp_sent_at = now

        if self._pending_event is not None:
            chunks.append(self._pending_event[0])
        else:
            chunks.append(p.heartbeat(
                maix_uptime_ms=int((now - self._started) * 1000),
                state_flags=0,
            ))

        payload = b"".join(chunks)
        if len(payload) > p.MAX_PAYLOAD:
            # In practice HELLO/TEMP/PERFORM/HB are small enough.  Drop the
            # optional temperature chunk before giving up.
            payload = b"".join(chunk for chunk in chunks
                               if chunk is not self._temp)
        if len(payload) > p.MAX_PAYLOAD:
            raise RuntimeError("SPI v1 payload exceeds 44 bytes")
        return payload

    def transaction(self):
        with self._lock:
            now = time.monotonic()
            payload = self._payload(now)
            tx = p.build_frame(p.TYPE_CONTROL, self.seq,
                               self.session_id, payload)
            self.seq = (self.seq + 1) & 0xFFFFFFFF

            rx = self._spi.write_read(tx, len(tx))
            if (not isinstance(rx, (bytes, bytearray)) or
                    len(rx) != p.FRAME_SIZE):
                raise RuntimeError(
                    f"short SPI response: {len(rx) if rx else 0}")

            status, caps = p.parse_status(bytes(rx))
            self._last_status = status
            self._last_caps = caps

            if self._hello_pending and status.link_state == p.LINK_ACTIVE:
                self._hello_pending = False

            if self._pending_event is not None:
                _, event_seq = self._pending_event
                if event_seq < 0:
                    self._pending_event = None
                elif (status.last_event_seq == event_seq or
                      ((status.last_event_seq - event_seq) & 0xFFFFFFFF)
                      < 0x80000000):
                    self._pending_event = None

            return status
