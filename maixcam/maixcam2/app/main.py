#!/usr/bin/env python3
"""JLU LED Lab MaixCAM2 voice keyword + STM32 link application.

Responsibilities:
  - record microphone audio and segment an utterance with RMS VAD;
  - run the external SenseVoice model (model files stay in /root/models);
  - match the legacy MaixCAM-Pro keyword/character set;
  - publish high-level PERFORM events to the STM32 over SPI2/CS1.

The model is external.  Only recognition/business and SPI transport live in
/root/JLU_LEDLAB.
"""

from __future__ import annotations

import argparse
import array
import json
import logging
import math
import os
import select
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
sys.path.insert(0, str(APP_DIR))

from keyword_matcher import load_config, match_text  # noqa: E402
from maix import audio, app, sys as maix_sys  # noqa: E402
from local_pwm import LocalPerfPwm  # noqa: E402
from maix.sensevoice import Sensevoice  # noqa: E402

import stm32_protocol as proto  # noqa: E402
from maixcam_spi_link import Stm32SpiLink  # noqa: E402

log = logging.getLogger("JLU_LEDLAB")

DEFAULT_MODEL = "/root/JLU_LEDLAB/config/sensevoice.mud"
DEFAULT_KEYWORDS = "/root/JLU_LEDLAB/config/keywords.json"

SAMPLE_RATE = 16000
CHUNK_MS = 100
CHUNK_BYTES = SAMPLE_RATE * 2 * CHUNK_MS // 1000
VOICE_RMS = 0.012
START_CHUNKS = 2
END_SILENCE_MS = 600
MIN_UTTERANCE_MS = 350
MAX_UTTERANCE_MS = 6000
PRE_ROLL_MS = 200


class AlsaRecorder:
    """Small arecord adapter usable with a selected ALSA card."""

    def __init__(self, device: str, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        self.bytes_per_ms = sample_rate * 2 // 1000
        self.proc = subprocess.Popen(
            ["arecord", "-q", "-D", device,
             "-f", "S16_LE", "-r", str(sample_rate),
             "-c", "1", "-t", "raw"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )

    def record(self, record_ms: int) -> bytes:
        remaining = max(1, record_ms) * self.bytes_per_ms
        chunks: list[bytes] = []
        # Use a bounded select loop so a signal/stop_event can break the
        # recording loop even when ALSA has no data ready.
        deadline = time.monotonic() + max(0.2, record_ms / 1000.0 * 2.5)
        fd = self.proc.stdout.fileno()
        while remaining > 0 and time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                continue
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def finish(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=1.0)


def pcm_rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    samples = array.array("h", pcm[:len(pcm) // 2 * 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


def capture_utterance(rec, stop_event: threading.Event,
                     voice_rms: float = VOICE_RMS) -> bytes:
    """Return one utterance, or b'' when stopping."""
    pre_roll: deque[bytes] = deque(maxlen=max(1, PRE_ROLL_MS // CHUNK_MS))
    speech = bytearray()
    in_speech = False
    silence_ms = 0
    max_bytes = SAMPLE_RATE * 2 * MAX_UTTERANCE_MS // 1000
    min_bytes = SAMPLE_RATE * 2 * MIN_UTTERANCE_MS // 1000

    while not stop_event.is_set() and not app.need_exit():
        pcm = rec.record(CHUNK_MS)
        if not pcm:
            continue

        rms = pcm_rms(pcm)

        if not in_speech:
            pre_roll.append(pcm)
            if rms >= voice_rms:
                in_speech = True
                speech.clear()
                for chunk in pre_roll:
                    speech.extend(chunk)
                pre_roll.clear()
                silence_ms = 0
        else:
            speech.extend(pcm)
            if rms < voice_rms:
                silence_ms += CHUNK_MS
            else:
                silence_ms = 0

            if silence_ms >= END_SILENCE_MS or len(speech) >= max_bytes:
                return bytes(speech) if len(speech) >= min_bytes else b""

    return b""


class SpiWorker(threading.Thread):
    """Own the SPI bus and send heartbeat/temperature at 20 Hz."""

    def __init__(self, link: Stm32SpiLink, stop_event: threading.Event):
        super().__init__(name="stm32-spi", daemon=True)
        self.link = link
        self.stop_event = stop_event
        self.temp_seq = 0
        self.last_temp_at = 0.0
        self.last_error_at = 0.0
        self.was_active = False

    def _send_temperature(self) -> None:
        try:
            info = maix_sys.cpu_temp()
            temp_c = info.get("cpu") if isinstance(info, dict) else None
            if temp_c is None:
                return
            self.temp_seq = (self.temp_seq + 1) & 0xFFFF
            self.link.set_temp(int(round(float(temp_c) * 1000)),
                               self.temp_seq, 0, True, source=2)
        except Exception as exc:  # noqa: BLE001
            log.debug("temperature read failed: %s", exc)

    def run(self) -> None:
        while not self.stop_event.is_set():
            started = time.monotonic()
            now = started
            if now - self.last_temp_at >= 1.0:
                self.last_temp_at = now
                self._send_temperature()

            try:
                status = self.link.transaction()
                active = status.link_state == proto.LINK_ACTIVE
                if active != self.was_active:
                    log.info("STM32 link %s (link_state=%d)",
                             "ACTIVE" if active else "not active",
                             status.link_state)
                    self.was_active = active
            except Exception as exc:  # noqa: BLE001
                if now - self.last_error_at >= 10.0:
                    self.last_error_at = now
                    log.warning("STM32 SPI transaction failed: %s", exc)

            elapsed = time.monotonic() - started
            self.stop_event.wait(max(0.0, 0.05 - elapsed))


class KeywordApp:
    def __init__(self, cfg: dict, link, wav: str | None,
                 local_pwm: bool = False, audio_device: str | None = None,
                 voice_rms: float = VOICE_RMS):
        self.cfg = cfg
        self.link = link
        self.wav = wav
        self.local_pwm = local_pwm
        self.audio_device = audio_device
        self.voice_rms = voice_rms
        self.model_mud = cfg.get("model_mud", "config/sensevoice.mud")
        if not os.path.isabs(self.model_mud):
            self.model_mud = str(ROOT_DIR / self.model_mud)

        self.sv = Sensevoice(model=self.model_mud,
                             lauguage=cfg.get("language", "zh"),
                             stream=False)
        self.stop_event = threading.Event()
        self.release_timer: threading.Timer | None = None
        self.release_lock = threading.Lock()
        self.spi_worker: SpiWorker | None = None

    def start(self) -> None:
        if self.local_pwm and self.link is not None:
            self.link.start()
        elif self.link is not None:
            self.spi_worker = SpiWorker(self.link, self.stop_event)
            self.spi_worker.start()

        log.info("loading SenseVoice model: %s", self.model_mud)
        self.sv.start()
        if not self.sv.is_ready(block=True):
            raise RuntimeError("SenseVoice service/model failed to load")
        log.info("SenseVoice ready")

    def stop(self) -> None:
        self.stop_event.set()
        with self.release_lock:
            if self.release_timer is not None:
                self.release_timer.cancel()
                self.release_timer = None
        if self.link is not None:
            try:
                self.link.queue_all_off()
                # Give the SPI worker one or two transactions to send it.
                time.sleep(0.2)
            except Exception:  # noqa: BLE001
                pass
            if self.spi_worker is not None:
                self.spi_worker.join(timeout=1.0)
            if self.local_pwm:
                self.link.shutdown()
        self.sv.stop()

    def _schedule_release(self, glyph_mask: int) -> None:
        if self.link is None:
            return

        hold_s = float(self.cfg.get("gate", {}).get("hold_seconds", 1.2))

        def release() -> None:
            if self.stop_event.is_set():
                return
            seq = self.link.queue_perform(glyph_mask, proto.ACTION_RELEASE)
            log.info("PERFORM RELEASE mask=0x%X event=%d", glyph_mask, seq)

        with self.release_lock:
            if self.release_timer is not None:
                self.release_timer.cancel()
            self.release_timer = threading.Timer(hold_s, release)
            self.release_timer.daemon = True
            self.release_timer.start()

    def handle_text(self, text: str) -> dict:
        result = match_text(text, self.cfg)
        log.info("ASR: %r normalized=%r gate=%s reason=%s",
                 text, result["normalized"], result["gate"],
                 result["reason"])
        for match in result["matches"]:
            if match["type"] == "char":
                log.info("  char=%s matched=%s registered=%s",
                         match["family"], match["matched"],
                         ",".join(match.get("registered_keywords", [])))
            else:
                log.info("  phrase=%s matched=%s",
                         match.get("id"), match.get("matched"))

        if result["gate"] and self.link is not None:
            mask = result["glyph_mask"]
            seq = self.link.queue_perform(mask, proto.ACTION_GATE)
            log.info("PERFORM GATE mask=0x%X event=%d", mask, seq)
            self._schedule_release(mask)
        return result

    def _run_wav(self) -> None:
        text = self.sv.refer(path=self.wav)
        self.handle_text(text)
        hold_s = float(self.cfg.get("gate", {}).get("hold_seconds", 1.2))
        # Let a watched RELEASE timer fire before shutdown when SPI is enabled.
        time.sleep((hold_s + 0.5) if self.link is not None else 0.5)

    def _run_mic(self) -> None:
        threshold = self.voice_rms
        if self.audio_device:
            rec = AlsaRecorder(self.audio_device, SAMPLE_RATE)
            log.info("ALSA microphone %s ready; speak the registered keywords",
                     self.audio_device)

            # PCM2902-class USB microphones have a higher noise floor than
            # the on-board codec.  Measure it briefly so the VAD does not
            # split an utterance every 100 ms in a quiet room.
            cal = []
            for _ in range(8):
                pcm = rec.record(CHUNK_MS)
                if pcm:
                    cal.append(pcm_rms(pcm))
            if cal:
                cal.sort()
                noise_floor = cal[len(cal) // 2]
                threshold = max(self.voice_rms, noise_floor * 3.0)
                log.info("USB mic noise floor=%.4f RMS, VAD threshold=%.4f",
                         noise_floor, threshold)
            else:
                log.warning("USB mic calibration got no PCM; using threshold=%.4f",
                            threshold)
        else:
            rec = audio.Recorder(sample_rate=SAMPLE_RATE,
                                 format=audio.Format.FMT_S16_LE,
                                 channel=1,
                                 block=True)
            log.info("built-in microphone ready; speak the registered keywords")
        try:
            while not self.stop_event.is_set() and not app.need_exit():
                pcm = capture_utterance(rec, self.stop_event, threshold)
                if not pcm:
                    continue
                log.info("utterance: %.2f s", len(pcm) / 2.0 / SAMPLE_RATE)
                try:
                    text = self.sv.refer(audio_data=pcm)
                except Exception as exc:  # noqa: BLE001
                    log.warning("ASR failed: %s", exc)
                    continue
                if text:
                    self.handle_text(text)
                else:
                    log.info("ASR: <empty>")
        finally:
            try:
                rec.finish()
            except Exception:  # noqa: BLE001
                pass

    def run(self) -> None:
        if self.wav:
            self._run_wav()
        else:
            self._run_mic()


def list_keywords(cfg: dict) -> None:
    print("registered phrase:")
    phrase = cfg.get("phrase", {})
    print(" ", phrase.get("id"), "->", phrase.get("display"),
          "glyph_mask=", phrase.get("glyph_mask"))
    print("registered character families:")
    for family, spec in cfg.get("char_families", {}).items():
        print(" ", family, spec.get("display"),
              "keywords=", ",".join(spec.get("registered_keywords", [])),
              "aliases=", ",".join(spec.get("aliases", [])))


def main() -> int:
    parser = argparse.ArgumentParser(description="JLU_LEDLAB MaixCAM2 voice + STM32")
    parser.add_argument("--config", default=DEFAULT_KEYWORDS)
    parser.add_argument("--model", default=None,
                        help="optional override for the SenseVoice .mud path")
    parser.add_argument("--wav", default=None,
                        help="recognize one WAV file instead of microphone")
    parser.add_argument("--no-spi", action="store_true",
                        help="do not open the STM32 SPI link")
    parser.add_argument("--local-pwm", action="store_true",
                        help="temporary local A30/PWM6 performance output")
    parser.add_argument("--pwm-pin", default="A30")
    parser.add_argument("--pwm-id", type=int, default=6)
    parser.add_argument("--pwm-freq", type=int, default=2000)
    parser.add_argument("--audio-device", default=None,
                        help="ALSA device, e.g. plughw:1,0 for USB mic")
    parser.add_argument("--usb-mic", action="store_true",
                        help="shortcut for --audio-device plughw:1,0")
    parser.add_argument("--voice-rms", type=float, default=VOICE_RMS,
                        help="VAD RMS threshold (default 0.012)")
    parser.add_argument("--list-keywords", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    if args.model:
        cfg["model_mud"] = args.model
    if args.list_keywords:
        list_keywords(cfg)
        return 0

    if args.local_pwm:
        link = LocalPerfPwm(pin=args.pwm_pin, pwm_id=args.pwm_id,
                            frequency=args.pwm_freq)
    elif args.no_spi:
        link = None
    else:
        link = Stm32SpiLink()
    audio_device = args.audio_device
    if args.usb_mic and not audio_device:
        audio_device = "plughw:1,0"
    application = KeywordApp(cfg, link, args.wav,
                             local_pwm=args.local_pwm,
                             audio_device=audio_device,
                             voice_rms=args.voice_rms)

    def on_signal(signum, frame):  # noqa: ARG001
        application.stop_event.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    try:
        application.start()
        application.run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        log.exception("fatal: %s", exc)
        return 1
    finally:
        application.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
