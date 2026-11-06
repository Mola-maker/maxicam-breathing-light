#!/usr/bin/env python3
"""SPI + English-keyword smoke test for MaixCAM Pro.

The installed Maix-Speech KWS model is a Mandarin pinyin model.  Direct English
keywords are rejected by its parser, so this test registers phonetic proxies:
    hello   -> ha1 lou2       (哈喽)
    welcome -> wei1 er2 kang1 (威尔康)

A detected proxy sends PERFORM to the STM32 with glyph_mask=0x4
(GLYPH_ALL_LAMPS), which drives PWM1..PWM13 and excludes HEAT1/HEAT2.
Temperature is read from SG2002 sysfs once per second and sent in TEMP TLVs.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time

TEST_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = "/root/surplife/app"
for path in (APP_DIR, TEST_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import stm32_protocol as proto
from spi_link import Stm32SpiLink
from sg2002_temp import sample as read_temperature

from maix import app, err, nn, pinmap

log = logging.getLogger("JLU_LEDLAB.test")


def load_config(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TempWorker(threading.Thread):
    def __init__(self, link, cfg, stop_event):
        super().__init__(name="temp", daemon=True)
        self.link = link
        self.cfg = cfg
        self.stop = stop_event
        self.seq = 0

    def run(self):
        tc = self.cfg.get("temperature", {})
        interval = float(tc.get("interval_seconds", 1.0))
        source = tc.get("source", "sysfs")
        while not self.stop.is_set():
            try:
                item = read_temperature(source)
                self.seq = (self.seq + 1) & 0xFFFF
                if self.link is not None:
                    self.link.set_temp(item["temp_mc"], self.seq, 0, True,
                                      0 if item.get("source") == "sysfs" else 1)
                log.info("TEMP %.3f C -> STM32 seq=%d", item["temp_c"], self.seq)
            except Exception as exc:  # noqa: BLE001
                log.warning("temperature failed: %s", exc)
            self.stop.wait(interval)


class SpiWorker(threading.Thread):
    def __init__(self, link, cfg, stop_event):
        super().__init__(name="spi", daemon=True)
        self.link = link
        self.cfg = cfg
        self.stop = stop_event
        self.was_active = False
        self.standby_sent = False
        self.fails = 0

    def run(self):
        while not self.stop.is_set():
            try:
                status = self.link.transaction()
                self.fails = 0
                active = status.link_state == proto.LINK_ACTIVE
                if active != self.was_active:
                    log.info("STM32 link %s state=%d faults=0x%04X",
                             "ACTIVE" if active else "not active",
                             status.link_state, status.fault_flags)
                    self.was_active = active
                if active and not self.standby_sent:
                    self.standby_sent = True
                    if self.cfg.get("standby_on_start", False):
                        seq = self.link.queue_perform(
                            int(self.cfg["all_lamps_mask"]), proto.ACTION_STANDBY)
                        log.info("PERFORM STANDBY all-lamps event=%d", seq)
            except Exception as exc:  # noqa: BLE001
                self.fails += 1
                if self.fails in (1, 10, 100):
                    log.warning("SPI failed (%d): %s", self.fails, exc)
            self.stop.wait(0.05)


class KeywordEngine:
    def __init__(self, cfg, link):
        self.cfg = cfg
        self.link = link
        self.stop = threading.Event()
        self.release_timer = None
        self.release_lock = threading.Lock()
        self.last_fire = {}
        self.keywords = [x["kws"] for x in cfg["keywords"]]
        self.labels = [x["label"] for x in cfg["keywords"]]
        self.display = [x.get("display", x["label"]) for x in cfg["keywords"]]
        self.thresholds = [float(x.get("threshold", 0.1)) for x in cfg["keywords"]]
        self.cooldowns = [float(x.get("cooldown", 2.0)) for x in cfg["keywords"]]
        self.speech = None

    def on_trigger(self, index, probability):
        now = time.monotonic()
        if now - self.last_fire.get(index, -1e9) < self.cooldowns[index]:
            return
        self.last_fire[index] = now
        mask = int(self.cfg.get("all_lamps_mask", 4))
        log.info("TRIGGER %s (%s) p=%.3f -> GATE mask=0x%X",
                 self.labels[index], self.display[index], probability, mask)
        if self.link is not None:
            seq = self.link.queue_perform(mask, proto.ACTION_GATE)
            log.info("PERFORM GATE all-lamps event=%d", seq)
        with self.release_lock:
            if self.release_timer is not None:
                self.release_timer.cancel()
            self.release_timer = threading.Timer(
                float(self.cfg.get("hold_seconds", 1.2)),
                self._release, args=(mask,))
            self.release_timer.daemon = True
            self.release_timer.start()

    def _release(self, mask):
        if self.stop.is_set():
            return
        if self.link is not None:
            seq = self.link.queue_perform(mask, proto.ACTION_RELEASE)
            log.info("PERFORM RELEASE all-lamps event=%d", seq)

    def _callback(self, data, length):
        for i in range(min(length, len(self.keywords))):
            try:
                prob = float(data[i])
            except (TypeError, ValueError):
                continue
            if prob >= self.thresholds[i]:
                self.on_trigger(i, prob)

    def start(self, wav):
        self.speech = nn.Speech(self.cfg["model"])
        if wav:
            ret = self.speech.init(nn.SpeechDevice.DEVICE_WAV, wav)
            log.info("KWS WAV input: %s", wav)
        else:
            ret = self.speech.init(nn.SpeechDevice.DEVICE_MIC,
                                   self.cfg.get("alsa_device", "surplife_mic"))
            log.info("KWS microphone: %s", self.cfg.get("alsa_device"))
        if ret != err.Err.ERR_NONE:
            raise RuntimeError(f"speech init failed: {ret}")
        ret = self.speech.kws(list(self.keywords), list(self.thresholds),
                              self._callback, True)
        if ret != err.Err.ERR_NONE:
            raise RuntimeError(f"kws init failed: {ret}")
        log.info("keywords: %s", ", ".join(
            f"{d} -> {k}" for d, k in zip(self.display, self.keywords)))
        log.info("all-lamp mask 0x%X = PWM1..PWM13, HEAT excluded",
                 int(self.cfg.get("all_lamps_mask", 4)))

    def stop_engine(self):
        self.stop.set()
        with self.release_lock:
            if self.release_timer is not None:
                self.release_timer.cancel()
                self.release_timer = None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=os.path.join(TEST_DIR, "config.json"))
    p.add_argument("--wav", default=None)
    p.add_argument("--no-spi", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    for pin, func in (("A22", "SPI4_SCK"), ("A23", "SPI4_MISO"),
                      ("A24", "SPI4_CS"), ("A25", "SPI4_MOSI")):
        try:
            r = pinmap.set_pin_function(pin, func)
            if r != err.Err.ERR_NONE:
                log.warning("pinmap %s -> %s: %s", pin, func, r)
        except Exception as exc:  # noqa: BLE001
            log.warning("pinmap %s -> %s failed: %s", pin, func, exc)

    link = None
    if not args.no_spi:
        try:
            link = Stm32SpiLink(
                bus=int(cfg.get("spi_bus", 3)),
                device=int(cfg.get("spi_device", 0)),
                frequency=int(cfg.get("spi_frequency", 1_000_000)))
            log.info("SPI /dev/spidev%d.%d @ %d Hz",
                     int(cfg.get("spi_bus", 3)),
                     int(cfg.get("spi_device", 0)),
                     int(cfg.get("spi_frequency", 1_000_000)))
        except Exception as exc:  # noqa: BLE001
            log.error("SPI open failed: %s", exc)

    spi_worker = temp_worker = None
    if link is not None:
        spi_worker = SpiWorker(link, cfg, stop)
        temp_worker = TempWorker(link, cfg, stop)
        spi_worker.start()
        temp_worker.start()
    else:
        log.warning("SPI disabled; keyword events are log-only")

    engine = KeywordEngine(cfg, link)
    try:
        engine.start(args.wav)
        while not stop.is_set() and not app.need_exit():
            n = engine.speech.run(1)
            if n < 1:
                log.info("audio input finished")
                break
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        log.exception("fatal: %s", exc)
        return 1
    finally:
        engine.stop_engine()
        # Let the SPI worker send ALL_OFF before stopping its loop.
        if link is not None:
            try:
                link.queue_all_off()
                time.sleep(0.2)
            except Exception:  # noqa: BLE001
                pass
        stop.set()
        if link is not None:
            link.close()
        if spi_worker is not None:
            spi_worker.join(1.0)
        if temp_worker is not None:
            temp_worker.join(1.0)
        log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
