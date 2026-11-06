"""SPI master transport for the STM32 PWM-Heater test firmware.

MaixCAM Pro SPI4: A22 SCK, A23 MISO, A24 CS, A25 MOSI.
Linux device: /dev/spidev3.0 (override with --spi-bus/--spi-device).
"""
from __future__ import annotations

import os
import threading
import time

import spidev
import stm32_protocol as p


class Stm32SpiLink:
    def __init__(self, bus=3, device=0, frequency=1_000_000,
                 session_id=None):
        self._spi = spidev.SpiDev()
        self._spi.open(int(bus), int(device))
        self._spi.mode = 0
        self._spi.bits_per_word = 8
        self._spi.max_speed_hz = int(frequency)
        self._spi.cshigh = False
        self.session_id = session_id or (
            int.from_bytes(os.urandom(4), "little") or 1
        )
        self.seq = 1
        self._event_seq = 1
        self._hello_pending = True
        self._pending_event = None
        self._temp = None
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

    def set_temp(self, temp_mc, sample_seq, age_ms=0, valid=True, source=0):
        with self._lock:
            self._temp = p.temp(temp_mc, sample_seq, age_ms, valid, source)

    def queue_perform(self, glyph_mask, action, profile_id=0, value=0):
        with self._lock:
            event_seq = self._event_seq
            self._event_seq = (self._event_seq + 1) & 0xFFFFFFFF
            self._pending_event = (
                p.perform(glyph_mask, action, event_seq, profile_id, value),
                event_seq,
            )
            return event_seq

    def queue_all_off(self):
        with self._lock:
            self._pending_event = (p.all_off(), -1)

    def _payload(self, now):
        chunks = []
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
                state_flags=0))

        payload = b"".join(chunks)
        if len(payload) > p.MAX_PAYLOAD:
            raise RuntimeError("SPI payload exceeds 44 bytes")
        return payload

    def transaction(self):
        with self._lock:
            now = time.monotonic()
            tx = p.build_frame(p.TYPE_CONTROL, self.seq, self.session_id,
                               self._payload(now))
            self.seq = (self.seq + 1) & 0xFFFFFFFF
            rx = self._spi.xfer2(list(tx))
            if len(rx) != p.FRAME_SIZE:
                raise RuntimeError(f"short SPI response: {len(rx)}")
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

    def close(self):
        try:
            self._spi.close()
        except Exception:
            pass
