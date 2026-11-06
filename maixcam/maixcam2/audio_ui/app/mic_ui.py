#!/usr/bin/env python3
"""MaixCAM2 USB microphone real-time visualizer.

The MaixCAM2 kernel shipped by Sipeed does not select CONFIG_SND_USB_AUDIO,
so the USB microphone is exposed as an ALSA card by the out-of-tree
snd-usb-audio module installed under /lib/modules/4.19.125.  MaixPy's
Recorder uses the default (on-board) card, therefore this app captures raw
PCM from the USB card through arecord and draws the result with MaixPy's
display API.

Run through run_mic_ui.sh so the launcher is stopped while the UI owns the
display.  The app itself is intentionally self-contained and can also be
used headlessly for screenshots:

    python3 app/mic_ui.py --duration 5 --headless --screenshot /tmp/mic.png
"""

from __future__ import annotations

import argparse
import collections
import math
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time as pytime

import numpy as np
from maix import app, display, image, touchscreen


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WIDTH = 640
HEIGHT = 480
DEFAULT_RATE = 16000
DEFAULT_CHUNK_MS = 20
DEFAULT_FPS = 30

AUDIO_WINDOW_SEC = 0.24
WAVE_WINDOW_SEC = 0.14
FFT_SIZE = 2048
BAND_COUNT = 24
BAND_LOW_HZ = 60.0
BAND_HIGH_HZ = 7800.0

DB_FLOOR = -60.0
DB_TOP = 0.0

EXIT_RECT = (520, 414, 96, 36)

FONT_PATH = "/maixapp/share/font/SourceHanSansCN-Regular.otf"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def rgb(r: int, g: int, b: int):
    return image.Color.from_rgb(r, g, b)


def load_ui_fonts() -> None:
    """Load the CJK font at the sizes used by the UI."""
    fonts = {
        "ui12": 12,
        "ui14": 14,
        "ui16": 16,
        "ui18": 18,
        "ui24": 24,
        "ui40": 40,
    }
    if not os.path.exists(FONT_PATH):
        return
    for name, size in fonts.items():
        try:
            image.load_font(name, FONT_PATH, size)
        except Exception:
            # The default font is still usable for ASCII; Chinese labels would
            # be missing, but this must not prevent audio acquisition.
            pass


def draw_text(img, x, y, text, color, font="ui16", scale=1.0, thickness=1):
    """draw_string wrapper with the awkward positional wrap_space argument."""
    img.draw_string(
        int(x), int(y), str(text), color, float(scale), int(thickness),
        False, 4, font,
    )


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def db_from_amplitude(amplitude: float) -> float:
    return 20.0 * math.log10(max(float(amplitude), 1.0e-7))


def fmt_db(db: float) -> str:
    if not math.isfinite(db) or db <= DB_FLOOR:
        return "--"
    return f"{db:5.1f}"


# ---------------------------------------------------------------------------
# ALSA capture
# ---------------------------------------------------------------------------

_CARD_RE = re.compile(
    r"^card\s+(?P<card>\d+):\s+(?P<card_name>.+?),\s+"
    r"device\s+(?P<device>\d+):\s+(?P<device_name>.+)$"
)


def list_capture_devices():
    """Return a list of ALSA capture devices parsed from arecord -l."""
    try:
        out = subprocess.check_output(
            ["arecord", "-l"], stderr=subprocess.STDOUT,
            text=True, timeout=4,
        )
    except Exception:
        return []

    devices = []
    for line in out.splitlines():
        m = _CARD_RE.match(line.strip())
        if not m:
            continue
        card = int(m.group("card"))
        dev = int(m.group("device"))
        devices.append({
            "card": card,
            "device": dev,
            "card_name": m.group("card_name").strip(),
            "device_name": m.group("device_name").strip(),
            "line": line.strip(),
            "alsa": f"plughw:{card},{dev}",
        })
    return devices


def find_usb_capture_device():
    """Pick the first USB Audio capture device, regardless of card number."""
    for d in list_capture_devices():
        text = d["line"].lower()
        if "usb" in text and ("audio" in text or "pnp" in text):
            return d
    return None


class AlsaCapture:
    """Read fixed-size mono S16_LE chunks from an arecord subprocess."""

    def __init__(self, device: str, sample_rate: int, chunk_samples: int):
        self.device = device
        self.sample_rate = int(sample_rate)
        self.chunk_samples = int(chunk_samples)
        self.bytes_per_chunk = self.chunk_samples * 2
        self.proc = None
        self.thread = None
        self.queue = queue.Queue(maxsize=8)
        self.running = threading.Event()
        self.error = ""
        self._lock = threading.Lock()

    def start(self) -> bool:
        self.stop()
        self.error = ""
        cmd = [
            "arecord",
            "-D", self.device,
            "-f", "S16_LE",
            "-r", str(self.sample_rate),
            "-c", "1",
            "-t", "raw",
            "-q",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            self.error = f"arecord 启动失败: {exc}"
            self.proc = None
            return False

        self.running.set()
        self.thread = threading.Thread(
            target=self._reader, name="alsa-capture", daemon=True,
        )
        self.thread.start()
        return True

    def _read_exact(self, stream, n: int):
        buf = bytearray()
        while len(buf) < n and self.running.is_set():
            try:
                chunk = stream.read(n - len(buf))
            except Exception as exc:
                self.error = f"读取失败: {exc}"
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf) if len(buf) == n else None

    def _reader(self):
        try:
            while self.running.is_set():
                data = self._read_exact(self.proc.stdout, self.bytes_per_chunk)
                if data is None:
                    break
                samples = (
                    np.frombuffer(data, dtype="<i2").astype(np.float32)
                    / 32768.0
                )
                try:
                    self.queue.put_nowait(samples)
                except queue.Full:
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self.queue.put_nowait(samples)
                    except queue.Full:
                        pass
        finally:
            proc = self.proc
            if proc is not None:
                try:
                    if proc.poll() is None:
                        proc.terminate()
                    proc.wait(timeout=0.8)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=0.5)
                    except Exception:
                        pass
                try:
                    err = proc.stderr.read().decode("utf-8", "replace").strip()
                except Exception:
                    err = ""
                if err and not self.error:
                    self.error = err.splitlines()[-1][:180]

    def get_chunks(self):
        chunks = []
        while True:
            try:
                chunks.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return chunks

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        self.running.clear()
        proc = self.proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=0.8)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self.proc = None
        self.thread = None


# ---------------------------------------------------------------------------
# Audio / visual state
# ---------------------------------------------------------------------------

class VisualState:
    def __init__(self, sample_rate: int):
        self.sample_rate = int(sample_rate)
        self.audio_n = max(int(self.sample_rate * AUDIO_WINDOW_SEC), 512)
        self.wave_n = max(int(self.sample_rate * WAVE_WINDOW_SEC), 512)

        self.audio = np.zeros(self.audio_n, dtype=np.float32)
        self.wave = np.zeros(self.wave_n, dtype=np.float32)
        self.fft = np.zeros(FFT_SIZE, dtype=np.float32)
        self.hann = np.hanning(FFT_SIZE).astype(np.float32)

        self.rms = 0.0
        self.peak = 0.0
        self.db = -120.0
        self.peak_db_hold = -120.0
        self.bars = np.zeros(BAND_COUNT, dtype=np.float32)
        self.dom_freq = 0.0
        self.total_samples = 0
        self.last_audio_at = 0.0

        nyq = self.sample_rate / 2.0
        high = min(BAND_HIGH_HZ, nyq * 0.98)
        edges = np.geomspace(BAND_LOW_HZ, high, BAND_COUNT + 1)
        freqs = np.fft.rfftfreq(FFT_SIZE, 1.0 / self.sample_rate)
        self.freqs = freqs
        self.dom_start = max(1, int(np.searchsorted(freqs, BAND_LOW_HZ)))
        self.band_bins = []
        for i in range(BAND_COUNT):
            lo = np.searchsorted(freqs, edges[i], side="left")
            hi = np.searchsorted(freqs, edges[i + 1], side="right")
            if hi <= lo:
                hi = min(lo + 1, len(freqs))
            self.band_bins.append((int(lo), int(hi)))
        self.band_edges = edges

    def feed(self, chunks, now: float) -> None:
        if not chunks:
            return
        new = np.concatenate(chunks).astype(np.float32, copy=False)
        if new.size == 0:
            return

        self.total_samples += int(new.size)
        self.last_audio_at = now

        self.audio = np.concatenate((self.audio, new))[-self.audio_n:]
        self.wave = np.concatenate((self.wave, new))[-self.wave_n:]
        self.fft = np.concatenate((self.fft, new))[-FFT_SIZE:]

        # Level uses about the last 100 ms for a stable but responsive meter.
        level_n = min(max(int(self.sample_rate * 0.10), 320), self.audio.size)
        seg = self.audio[-level_n:]
        if seg.size:
            rms = float(np.sqrt(np.mean(seg * seg)))
            peak = float(np.max(np.abs(seg)))
        else:
            rms = 0.0
            peak = 0.0

        self.rms = 0.68 * self.rms + 0.32 * rms
        self.peak = 0.55 * self.peak + 0.45 * peak
        db = db_from_amplitude(self.rms)
        if db > self.db:
            self.db = 0.45 * self.db + 0.55 * db
        else:
            self.db = 0.86 * self.db + 0.14 * db

        peak_db = db_from_amplitude(self.peak)
        if peak_db > self.peak_db_hold:
            self.peak_db_hold = peak_db
        else:
            self.peak_db_hold -= 10.0 / DEFAULT_FPS

        # Spectrum: rfft magnitude normalized so a full-scale sine is 1.0.
        spec = np.abs(np.fft.rfft(self.fft * self.hann))
        mag = spec / (FFT_SIZE / 2.0)
        band_levels = np.zeros(BAND_COUNT, dtype=np.float32)
        for i, (lo, hi) in enumerate(self.band_bins):
            if hi <= lo:
                continue
            m = float(np.max(mag[lo:hi]))
            band_db = db_from_amplitude(m)
            band_levels[i] = clamp((band_db + 72.0) / 60.0, 0.0, 1.0)

        # Instant attack, smooth release.
        self.bars = np.maximum(band_levels, self.bars * 0.78)

        if self.db > -55.0 and self.dom_start < mag.size:
            # Ignore DC and low-frequency rumble below the displayed 60 Hz.
            idx = self.dom_start + int(np.argmax(mag[self.dom_start:]))
            self.dom_freq = float(self.freqs[idx])
        else:
            self.dom_freq = 0.0


# ---------------------------------------------------------------------------
# UI drawing
# ---------------------------------------------------------------------------

class MicUI:
    """Incremental renderer.

    Drawing text and hundreds of line segments is relatively expensive on the
    MaixCAM2, especially at 30 FPS.  The static cards and labels are rendered
    once; each frame only clears/repaints the small dynamic regions.  Text is
    cached by value so it is not redrawn when nothing changed.
    """

    def __init__(self):
        self.bg = rgb(5, 10, 18)
        self.card = rgb(9, 19, 30)
        self.card_edge = rgb(27, 49, 67)
        self.grid = rgb(20, 37, 52)
        self.text = rgb(226, 240, 250)
        self.muted = rgb(118, 144, 164)
        self.dim = rgb(57, 78, 96)
        self.cyan = rgb(0, 224, 190)
        self.green = rgb(55, 220, 132)
        self.yellow = rgb(250, 204, 68)
        self.red = rgb(255, 94, 94)
        self.blue = rgb(82, 160, 255)
        self.bar_bg = rgb(17, 31, 44)
        self.white = rgb(246, 250, 255)
        self.exit_bg = rgb(33, 48, 62)
        self.exit_edge = rgb(255, 172, 70)

        self._last_status = None
        self._last_level_text = None
        self._last_level_line = None
        self._last_freq_text = None
        self._last_footer_primary = None
        self._last_footer_detail = None
        self._last_fps_text = None
        self._last_fps_at = 0.0

        self.base = self._build_base()
        self.img = self.base.copy()

    def _card_box(self, img, x, y, w, h):
        img.draw_rect(x, y, w, h, self.card, -1)
        img.draw_rect(x, y, w, h, self.card_edge, 1)

    def _build_base(self):
        img = image.Image(WIDTH, HEIGHT, image.Format.FMT_RGB888, bg=self.bg)

        # Header: title/subtitle and USB badge.  The LIVE/WAIT indicator is
        # painted as a small dynamic region.
        draw_text(img, 92, 12, "外接麦克风", self.text, "ui24")
        draw_text(img, 94, 44, "USB Audio 实时声学监测", self.muted, "ui14")
        img.draw_rect(526, 16, 96, 28, self.card, -1)
        img.draw_rect(526, 16, 96, 28, self.card_edge, 1)
        draw_text(img, 536, 22, "USB HUB", self.cyan, "ui12")

        # Level card.
        lx, ly, lw, lh = 16, 80, 304, 158
        self._card_box(img, lx, ly, lw, lh)
        img.draw_rect(lx, ly, 3, lh, self.cyan, -1)
        draw_text(img, lx + 14, ly + 10, "输入电平", self.muted, "ui16")
        draw_text(img, lx + lw - 58, ly + 12, "dBFS", self.muted, "ui12")

        # Spectrum card.
        sx, sy, sw, sh = 328, 80, 296, 158
        self._card_box(img, sx, sy, sw, sh)
        img.draw_rect(sx, sy, 3, sh, self.blue, -1)
        draw_text(img, sx + 14, sy + 10, "频谱", self.muted, "ui16")
        draw_text(img, sx + sw - 96, sy + 12, "60 Hz — 8 kHz", self.dim, "ui12")
        spx, spy, spw, sph = sx + 14, sy + 44, sw - 28, 88
        draw_text(img, spx, spy + sph + 8, "60", self.dim, "ui12")
        draw_text(img, spx + spw // 2 - 12, spy + sph + 8, "1k", self.dim, "ui12")
        draw_text(img, spx + spw - 18, spy + sph + 8, "8k", self.dim, "ui12")

        # Waveform card.
        wx, wy, ww, wh = 16, 246, 608, 150
        self._card_box(img, wx, wy, ww, wh)
        draw_text(img, wx + 14, wy + 10, "波形", self.muted, "ui16")
        draw_text(img, wx + ww - 86, wy + 12, "140 ms", self.dim, "ui12")

        # Footer and exit button.
        fx, fy, fw, fh = 16, 404, 608, 60
        img.draw_line(fx, fy, fx + fw, fy, self.grid, 1)
        bx, by, bw, bh = EXIT_RECT
        img.draw_rect(bx, by, bw, bh, self.exit_bg, -1)
        img.draw_rect(bx, by, bw, bh, self.exit_edge, 1)
        draw_text(img, bx + 24, by + 9, "退出", self.exit_edge, "ui16")
        return img

    def _draw_status(self, live: bool):
        if self._last_status is live:
            return
        self.img.draw_rect(16, 14, 74, 36, self.bg, -1)
        color = self.green if live else self.red
        self.img.draw_circle(26, 31, 5, color, -1)
        draw_text(self.img, 38, 23, "LIVE" if live else "WAIT", color, "ui14")
        self._last_status = live

    def _draw_level(self, state: VisualState, live: bool):
        x, y, w, h = 16, 80, 304, 158

        # Big numeric value and unit.  Quantise to 0.5 dB so the text is not
        # repainted on every audio callback.
        if live:
            db_q = round(state.db * 2.0) / 2.0
            text = f"{db_q:5.1f}" if db_q > DB_FLOOR else "--"
            key = ("live", text)
        else:
            text = "等待麦克风"
            key = ("wait", text)

        if key != self._last_level_text:
            self.img.draw_rect(x + 14, y + 28, 200, 56, self.card, -1)
            if live:
                draw_text(self.img, x + 14, y + 28, text, self.text, "ui40")
                if text != "--":
                    draw_text(self.img, x + 150, y + 52, "dBFS", self.muted, "ui14")
            else:
                draw_text(self.img, x + 14, y + 38, text, self.yellow, "ui24")
                draw_text(self.img, x + 14, y + 72,
                          "USB Audio / Hub 检查中", self.muted, "ui14")
            self._last_level_text = key

        # Meter area, including the peak-hold marker.
        mx, my, mw, mh = x + 14, y + 88, w - 28, 20
        self.img.draw_rect(mx, my - 5, mw, mh + 10, self.card, -1)
        self.img.draw_rect(mx, my, mw, mh, self.bar_bg, -1)
        n = 32
        gap = 2
        seg_w = (mw - (n - 1) * gap) / n
        fill = 0.0
        if live:
            fill = clamp((state.db - DB_FLOOR) / (DB_TOP - DB_FLOOR), 0.0, 1.0)
        for i in range(n):
            pos = (i + 0.5) / n
            if pos <= fill:
                if pos > 0.86:
                    color = self.red
                elif pos > 0.70:
                    color = self.yellow
                else:
                    color = self.green
            else:
                color = self.bar_bg
            sx = mx + i * (seg_w + gap)
            self.img.draw_rect(int(sx), my, int(seg_w), mh, color, -1)

        if live and state.peak_db_hold > DB_FLOOR:
            px = mx + int(
                clamp((state.peak_db_hold - DB_FLOOR) / (DB_TOP - DB_FLOOR),
                      0.0, 1.0) * (mw - 3)
            )
            self.img.draw_rect(px, my - 4, 3, mh + 8, self.white, -1)

        # One compact RMS/PEAK line instead of two separate text draws.
        if live:
            db_q = round(state.db * 2.0) / 2.0
            peak_q = round(db_from_amplitude(state.peak) * 2.0) / 2.0
            line = f"RMS {db_q:5.1f} · PEAK {peak_q:5.1f} dBFS"
        else:
            line = "设备恢复后自动重试"
        if line != self._last_level_line:
            self.img.draw_rect(x + 14, y + 114, w - 28, 20, self.card, -1)
            draw_text(self.img, x + 14, y + 118, line, self.dim, "ui12")
            self._last_level_line = line

    def _draw_wave(self, state: VisualState, live: bool):
        x, y, w, h = 16, 246, 608, 150
        px, py, pw, ph = x + 14, y + 38, w - 28, 96
        self.img.draw_rect(px, py, pw, ph, self.card, -1)

        # Redraw the five grid lines in the cleared plot area.
        for gy in (py, py + ph // 2, py + ph):
            self.img.draw_line(px, gy, px + pw, gy, self.grid, 1)
        for gx in (px, px + pw // 2, px + pw):
            self.img.draw_line(gx, py, gx, py + ph, self.grid, 1)

        center = py + ph // 2
        if live and state.wave.size:
            buf = state.wave
            # Auto-scale the waveform: quiet room noise is still visible, but
            # a loud voice is not clipped into a solid block.
            gain = clamp(0.75 / max(state.peak, 0.005), 1.5, 8.0)
            half = ph / 2.0 - 3
            # 100 columns with a 6-pixel brush gives a continuous envelope
            # while keeping the number of draw_line calls low.
            cols = 100
            step = pw / cols
            for i in range(cols):
                a = int(i * buf.size / cols)
                b = int((i + 1) * buf.size / cols)
                b = max(a + 1, b)
                seg = buf[a:b]
                if seg.size == 0:
                    continue
                mn = float(np.min(seg))
                mx = float(np.max(seg))
                y1 = int(center - clamp(mx * gain, -1.0, 1.0) * half)
                y2 = int(center - clamp(mn * gain, -1.0, 1.0) * half)
                y1 = int(clamp(y1, py + 2, py + ph - 2))
                y2 = int(clamp(y2, py + 2, py + ph - 2))
                if y1 == y2:
                    y2 += 1
                sx = px + int(i * step + step / 2)
                self.img.draw_line(sx, y1, sx, y2, self.cyan, 6)
        else:
            self.img.draw_line(px, center, px + pw, center, self.dim, 1)
            draw_text(self.img, x + 14, y + 70, "等待音频数据", self.dim, "ui14")

    def _draw_spectrum(self, state: VisualState, live: bool):
        x, y, w, h = 328, 80, 296, 158
        px, py, pw, ph = x + 14, y + 44, w - 28, 88
        self.img.draw_rect(px, py, pw, ph, self.card, -1)
        for gy in (py, py + ph // 2, py + ph):
            self.img.draw_line(px, gy, px + pw, gy, self.grid, 1)

        n = BAND_COUNT
        gap = 3
        bar_w = (pw - (n - 1) * gap) / n
        baseline = py + ph
        for i in range(n):
            bx = px + i * (bar_w + gap)
            level = float(state.bars[i]) if live else 0.0
            bh = int(level * (ph - 2))
            if level > 0.84:
                color = self.red
            elif level > 0.62:
                color = self.yellow
            else:
                color = self.cyan
            if bh > 0:
                self.img.draw_rect(int(bx), baseline - bh,
                                   max(1, int(bar_w)), bh, color, -1)

        # Dominant frequency label; quantise to 5 Hz and only repaint on change.
        freq_text = ""
        if live and state.dom_freq > 0:
            freq_text = f"主频 {int(round(state.dom_freq / 5.0)) * 5} Hz"
        if freq_text != self._last_freq_text:
            self.img.draw_rect(x + 54, y + 10, 130, 18, self.card, -1)
            if freq_text:
                draw_text(self.img, x + 54, y + 10, freq_text, self.cyan, "ui12")
            self._last_freq_text = freq_text

    def _draw_footer(self, live: bool, device: str, fps: float):
        x, y, w, h = 16, 404, 608, 60
        primary = "USB 麦克风在线" if live else "未检测到 USB 麦克风"
        if primary != self._last_footer_primary:
            self.img.draw_rect(x + 4, y + 4, 230, 18, self.bg, -1)
            color = self.green if live else self.red
            draw_text(self.img, x + 4, y + 4, primary, color, "ui14")
            self._last_footer_primary = primary

        detail = f"{device} · 16 kHz · 20 ms" if device else "16 kHz · 20 ms"
        if detail != self._last_footer_detail:
            self.img.draw_rect(x + 4, y + 24, 310, 18, self.bg, -1)
            draw_text(self.img, x + 4, y + 24, detail, self.dim, "ui12")
            self._last_footer_detail = detail

        # FPS is a diagnostic, update it twice a second only.
        now = pytime.monotonic()
        if now - self._last_fps_at >= 0.5:
            fps_text = f"{fps:4.1f} FPS"
            if fps_text != self._last_fps_text:
                self.img.draw_rect(x + w - 170, y + 4, 60, 18, self.bg, -1)
                draw_text(self.img, x + w - 166, y + 4, fps_text, self.dim, "ui12")
                self._last_fps_text = fps_text
            self._last_fps_at = now

    def render(self, state: VisualState, live: bool, device: str, fps: float):
        self._draw_status(live)
        self._draw_level(state, live)
        self._draw_wave(state, live)
        self._draw_spectrum(state, live)
        self._draw_footer(live, device, fps)
        return self.img


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="MaixCAM2 USB microphone visualizer")
    p.add_argument("--device", default=None,
                   help="ALSA device, e.g. plughw:1,0. Auto-detect USB if omitted")
    p.add_argument("--rate", type=int, default=DEFAULT_RATE)
    p.add_argument("--chunk-ms", type=int, default=DEFAULT_CHUNK_MS)
    p.add_argument("--fps", type=float, default=DEFAULT_FPS)
    p.add_argument("--duration", type=float, default=0.0,
                   help="exit after N seconds; 0 = run until touch/Ctrl-C")
    p.add_argument("--headless", action="store_true",
                   help="do not open display; useful for screenshot test")
    p.add_argument("--screenshot", default="",
                   help="save the rendered frame to this PNG path")
    p.add_argument("--screenshot-after", type=float, default=2.0,
                   help="save screenshot after N seconds")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    rate = max(8000, int(args.rate))
    chunk_samples = max(80, int(rate * args.chunk_ms / 1000.0))

    try:
        app.register_default_signal_handle()
    except Exception:
        pass

    stop_requested = {"value": False}

    def _on_signal(signum, frame):
        stop_requested["value"] = True
        try:
            app.set_exit_flag(True)
        except Exception:
            pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except Exception:
            pass

    load_ui_fonts()
    ui = MicUI()
    state = VisualState(rate)

    disp = None
    if not args.headless:
        try:
            disp = display.Display(WIDTH, HEIGHT, image.Format.FMT_RGB888)
        except Exception as exc:
            print(f"display init failed: {exc}", file=sys.stderr)
            disp = None

    touch = None
    try:
        touch = touchscreen.TouchScreen()
    except Exception:
        touch = None

    selected = None
    cap = None
    last_device = args.device or ""
    next_retry = 0.0
    screenshot_saved = False
    start = pytime.monotonic()
    last_frame = start
    fps = 0.0

    def ensure_capture(now: float):
        nonlocal selected, cap, last_device
        if args.device:
            if cap is not None and cap.is_alive():
                return
            selected = {"alsa": args.device, "line": args.device}
        else:
            info = find_usb_capture_device()
            if info is None:
                if cap is not None:
                    cap.stop()
                cap = None
                selected = None
                return
            selected = info
            if cap is not None and cap.is_alive() and last_device == info["alsa"]:
                return
        if cap is not None and cap.is_alive() and last_device == selected["alsa"]:
            return
        if cap is not None:
            cap.stop()
        last_device = selected["alsa"]
        cap = AlsaCapture(selected["alsa"], rate, chunk_samples)
        if not cap.start():
            print(f"capture start failed: {cap.error}", file=sys.stderr)

    ensure_capture(start)

    try:
        while not stop_requested["value"] and not app.need_exit():
            now = pytime.monotonic()
            elapsed = now - start
            if args.duration > 0 and elapsed >= args.duration:
                break

            if now >= next_retry:
                ensure_capture(now)
                next_retry = now + 2.0

            chunks = cap.get_chunks() if cap is not None else []
            if chunks:
                state.feed(chunks, now)

            live = bool(cap is not None and cap.is_alive() and state.total_samples > 0)
            device_label = selected["alsa"] if selected else ""
            fps = (1.0 / max(now - last_frame, 1e-4)) if last_frame else 0.0
            # Smooth the FPS readout so it does not flicker.
            if fps > 120.0:
                fps = 0.0
            last_frame = now

            img = ui.render(state, live, device_label, fps)

            if args.screenshot and not screenshot_saved and elapsed >= args.screenshot_after:
                try:
                    img.save(args.screenshot)
                    print(f"screenshot: {args.screenshot}")
                except Exception as exc:
                    print(f"screenshot failed: {exc}", file=sys.stderr)
                screenshot_saved = True

            if disp is not None:
                try:
                    disp.show(img)
                except Exception as exc:
                    print(f"display show failed: {exc}", file=sys.stderr)
                    disp = None

            if touch is not None:
                try:
                    if touch.available(0):
                        p = touch.read()
                        if len(p) >= 3 and p[2]:
                            tx, ty = int(p[0]), int(p[1])
                            bx, by, bw, bh = EXIT_RECT
                            # Also accept any touch in the bottom bar so the
                            # control still works if the touch panel reports
                            # the panel in a slightly different orientation.
                            if (bx <= tx <= bx + bw and by <= ty <= by + bh) or ty >= 400:
                                break
                except Exception:
                    pass

            frame_dt = 1.0 / max(args.fps, 1.0)
            remain = frame_dt - (pytime.monotonic() - now)
            if remain > 0:
                pytime.sleep(remain)
    finally:
        if cap is not None:
            cap.stop()
        if touch is not None:
            try:
                touch.close()
            except Exception:
                pass
        if disp is not None:
            try:
                disp.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
