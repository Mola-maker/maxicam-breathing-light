"""Temporary local A30/PWM6 performance output.

This mirrors the STM32 performance engine so the same GATE/RELEASE/EGG
semantics can be observed without the STM32 board connected.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time

from maix import err, pinmap, pwm

import stm32_protocol as proto

log = logging.getLogger("JLU_LEDLAB.local_pwm")

STANDBY_MIN = 1.0
STANDBY_MAX = 8.0
STANDBY_PERIOD_S = 4.0
INTRO_S = 0.03
RELEASE_TOTAL_S = 2.5
EGG_FLASH_S = 1.6
EGG_CYCLE_S = 0.2
EGG_OFF_S = 2.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def _smoothstep(x: float) -> float:
    x = _clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _ease_out(x: float) -> float:
    x = _clamp(x, 0.0, 1.0)
    return 1.0 - (1.0 - x) ** 3


class LocalPerfPwm:
    """One physical PWM channel, same high-level state machine as STM32."""

    def __init__(self, pin: str = "A30", pwm_id: int = 6,
                 frequency: int = 2000, update_hz: int = 100):
        self.pin = pin
        self.pwm_id = pwm_id
        self.frequency = frequency
        self.update_hz = max(20, min(200, int(update_hz)))
        self._dev = None
        self._thread = None
        self._stop = threading.Event()
        self._commands: queue.Queue[tuple[int, int]] = queue.Queue(maxsize=16)
        self._lock = threading.Lock()
        self._state = "STANDBY"
        self._state_start = time.monotonic()
        self._duty = 0.0
        self._intro_from = 0.0
        self._release_from = 0.0
        self._event_seq = 0

    def start(self) -> None:
        err.check_raise(pinmap.set_pin_function(self.pin, f"PWM{self.pwm_id}"),
                        f"pinmap {self.pin} -> PWM{self.pwm_id} failed")
        self._dev = pwm.PWM(self.pwm_id, freq=self.frequency,
                            duty=0.0, enable=True)
        self._state = "STANDBY"
        self._state_start = time.monotonic()
        self._duty = 0.0
        self._thread = threading.Thread(target=self._run, name="local-pwm",
                                        daemon=True)
        self._thread.start()
        log.info("local PWM started pin=%s pwm=%d freq=%dHz",
                 self.pin, self.pwm_id, self.frequency)

    def queue_perform(self, glyph_mask: int, action: int,
                      profile_id: int = 0, value: int = 0) -> int:
        del profile_id, value
        with self._lock:
            self._event_seq = (self._event_seq + 1) & 0xFFFFFFFF
            seq = self._event_seq
        try:
            self._commands.put_nowait((action, glyph_mask))
        except queue.Full:
            log.warning("local PWM command queue full, drop action=%d", action)
        return seq

    def queue_all_off(self) -> None:
        try:
            self._commands.put_nowait((proto.ACTION_OFF, 0))
        except queue.Full:
            pass

    def shutdown(self) -> None:
        self.queue_all_off()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._dev is not None:
            try:
                self._dev.duty(0.0)
                self._dev.disable()
            except Exception:  # noqa: BLE001
                pass
        # A30 is a shared UART1_TX pin; restore it after the temporary test.
        if self.pin == "A30":
            try:
                pinmap.set_pin_function("A30", "UART1_TX")
            except Exception:  # noqa: BLE001
                pass
        log.info("local PWM stopped")

    def _process_commands(self, now: float) -> None:
        while True:
            try:
                action, glyph_mask = self._commands.get_nowait()
            except queue.Empty:
                return

            if action == proto.ACTION_STANDBY:
                self._state = "STANDBY"
                self._state_start = now
            elif action == proto.ACTION_GATE:
                self._intro_from = self._duty
                self._state = "INTRO"
                self._state_start = now
                log.info("local GATE mask=0x%X", glyph_mask)
            elif action == proto.ACTION_RELEASE:
                self._release_from = self._duty
                self._state = "RELEASE"
                self._state_start = now
                log.info("local RELEASE mask=0x%X", glyph_mask)
            elif action == proto.ACTION_EGG:
                self._state = "EGG"
                self._state_start = now
                log.info("local EGG mask=0x%X", glyph_mask)
            elif action == proto.ACTION_OFF:
                self._state = "OFF"
                self._state_start = now
                log.info("local OFF")
            else:
                log.warning("local PWM unknown action=%d", action)

    def _tick_duty(self, now: float) -> float:
        elapsed = now - self._state_start

        if self._state == "OFF":
            return 0.0

        if self._state == "STANDBY":
            t = elapsed % STANDBY_PERIOD_S
            wave = 0.5 + 0.5 * math.sin(2.0 * math.pi * t / STANDBY_PERIOD_S
                                        - math.pi / 2.0)
            return STANDBY_MIN + (STANDBY_MAX - STANDBY_MIN) * wave

        if self._state == "INTRO":
            if elapsed >= INTRO_S:
                self._state = "HOLD"
                self._state_start = now
                return 100.0
            p = _smoothstep(elapsed / INTRO_S)
            return self._intro_from + (100.0 - self._intro_from) * p

        if self._state == "HOLD":
            return 100.0

        if self._state == "RELEASE":
            if elapsed >= RELEASE_TOTAL_S:
                self._state = "STANDBY"
                # Release ends at the 8% breathing high point.
                self._state_start = now - STANDBY_PERIOD_S / 2.0
                return STANDBY_MAX
            start = self._release_from
            stage1_end = min(50.0, start)
            stage2_end = min(35.0, stage1_end)
            stage3_end = min(8.0, stage2_end)
            if elapsed < 0.5:
                return start - (start - stage1_end) * _ease_out(elapsed / 0.5)
            if elapsed < 1.3:
                p = _ease_out((elapsed - 0.5) / 0.8)
                return stage1_end - (stage1_end - stage2_end) * p
            p = (elapsed - 1.3) / 1.2
            return stage2_end - (stage2_end - stage3_end) * _clamp(p, 0.0, 1.0)

        if self._state == "EGG":
            if elapsed < EGG_FLASH_S:
                phase = elapsed % EGG_CYCLE_S
                return 100.0 if phase < EGG_CYCLE_S * 0.5 else 0.0
            if elapsed < EGG_FLASH_S + EGG_OFF_S:
                return 0.0
            self._state = "STANDBY"
            self._state_start = now
            return STANDBY_MIN

        return 0.0

    def _run(self) -> None:
        period = 1.0 / self.update_hz
        next_tick = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            self._process_commands(now)
            duty = _clamp(self._tick_duty(now), 0.0, 100.0)
            self._duty = duty
            if self._dev is not None:
                try:
                    self._dev.duty(duty)
                except Exception as exc:  # noqa: BLE001
                    log.warning("local PWM write failed: %s", exc)
                    time.sleep(0.1)
                    continue
            next_tick += period
            sleep_s = next_tick - time.monotonic()
            if sleep_s > 0:
                self._stop.wait(sleep_s)
            elif sleep_s < -0.1:
                next_tick = time.monotonic()

    def get_state(self) -> str:
        return self._state

    def get_duty(self) -> float:
        return self._duty
