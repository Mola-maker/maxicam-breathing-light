#!/usr/bin/env python3
"""
MaixCAM Pro 语音门控 18 kHz PWM 灯控

业务:
    "长春" (chang2 chun1) 是门, 语音模型识别到后从待机进入业务状态。
    独立音量线程持续监听麦克风, 做降噪/人声增强, 用相对声量控制:
        - 业务亮度 (40% ~ 100%)
        - 闪烁频率 (A19/PWM7 的占空比作为频率给定, 或按配置输出方波)
    亮度采用“快攻慢放”的非对称包络:
        有人声时每个 tick 只衰减 1, 声音变大立即跳上去;
        人声结束(voice inactive)时每个 tick 衰减 3;
        亮度衰减到 LIGHT_THRESHOLD 以下后回到待机呼吸。

关键点:
    nn.Speech.run() 会长时间占用 Python GIL。因此 PWM 控制和音量 DSP
    都放在独立进程里, 主进程只负责 KWS, 保证 100 Hz 的 PWM 更新不被阻塞。

硬件:
    A18 -> PWM6 -> /sys/class/pwm/pwmchip4/pwm2
    A19 -> PWM7 -> /sys/class/pwm/pwmchip4/pwm3
    载波 18 kHz, duty 0~100%。

环境变量:
    VOICE_AM_MODEL        KWS 声学模型, 默认 /root/models/am_3332_192_int8.mud
    VOICE_KEYWORD_PINYIN  关键词拼音, 默认 "chang2 chun1"
    VOICE_GATE_THRESHOLD  门限概率, 默认 0.5
    VOICE_GATE_REARM      概率回落到该值以下才重新武装, 默认 0.28 (无时间不应期)
    VOICE_ALSA_DEVICE     默认 pwm_mic (见 /root/.asoundrc)
    VOICE_TAP_FIFO        默认 /root/surplife/run/surplife_pwm_mic.pcm

    PWM_FREQ              载波频率, 默认 18000
    PWM_UPDATE_HZ         PWM 更新率, 默认 100
    PWM6_PATH / PWM7_PATH sysfs 通道路径
    PWM7_MODE             freq | mirror | square | off, 默认 freq
    A18_BLINK             1 = A18 也按闪烁频率做亮灭翻转, 默认 0
    BLINK_HZ_MIN/MAX      闪烁频率范围, 默认 1 / 8 Hz
    BLINK_INVERT          1 = 声量越大闪得越慢
    STANDBY_MIN/MAX       待机呼吸占空比, 默认 5 / 35 %
    STANDBY_PERIOD        待机呼吸周期, 默认 4 秒
    BUSINESS_MIN/MAX      业务亮度映射, 默认 40 / 100 %
    LIGHT_THRESHOLD       亮度衰减到该值以下回待机, 默认 35 %
    DECAY_TICK_MS         “每 tick”的时间长度, 默认 20 ms
    WORK_DECAY_PER_TICK   有人声时每 tick 衰减量, 默认 1
    RELEASE_DECAY_PER_TICK 人声结束后每 tick 衰减量, 默认 3
    VOICE_ACTIVE_MIN      判为人声的最小线性 RMS, 默认 0.0015
    VOICE_ACTIVE_RATIO    判为人声的相对门限, 默认 0.02 * ref
    MIN_REF               最小人声参考 (线性 RMS), 默认 0.002
    PWM_DRY_RUN           1 = 只计算不写 PWM
    PWM_DEMO              1 = 不依赖语音, 自动演示 2s 待机 + 5s 业务 + 衰减
    SURPLIFE_LOG          日志级别, 默认 INFO
"""

from __future__ import annotations

import collections
import errno
import logging
import math
import multiprocessing as mp
import os
import signal
import sys
import time

log = logging.getLogger("voice_pwm")


# ======================================================================
# 纯逻辑 (可在没有硬件的机器上测试)
# ======================================================================

def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def breathing_duty(t: float, period: float = 4.0,
                   lo: float = 5.0, hi: float = 35.0) -> float:
    """待机慢速呼吸: 从 lo 开始, 在 lo~hi 之间正弦变化。"""
    phase = 2.0 * math.pi * t / max(period, 0.1) - math.pi / 2.0
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(phase))


def business_brightness(level: float, lo: float = 40.0, hi: float = 100.0) -> float:
    """业务亮度: level 0 -> lo, level 1 -> hi, 默认始终高于 35%。"""
    return lo + (hi - lo) * clamp(level, 0.0, 1.0)


def blink_hz(level: float, lo: float = 1.0, hi: float = 8.0) -> float:
    """声量越大 -> 闪烁频率越高 (默认)。"""
    return lo + (hi - lo) * clamp(level, 0.0, 1.0)


def decay_step(light: float, target: float, decay_per_tick: float,
               dt: float, tick_seconds: float) -> float:
    """
    非对称包络的单步:

        light -= decay_per_tick * (dt / tick_seconds)
        if target > light:
            light = target

    声音变大时 target 直接覆盖当前亮度(快攻); 声音变小时
    亮度按 decay_per_tick 慢慢下降(慢放)。返回 0~100。
    """
    tick_seconds = max(0.001, tick_seconds)
    decayed = light - max(0.0, decay_per_tick) * (max(0.0, dt) / tick_seconds)
    if target > decayed:
        decayed = target
    return clamp(decayed, 0.0, 100.0)


class GateDetector:
    """
    只做“上升沿”检测, 不做任何时间不应期。
    概率超过 threshold 触发一次, 回落到 rearm 以下后才允许下一次。
    这样同一句 "长春" 不会每帧重复触发, 但用户连续说两次可以立刻响应。
    """

    def __init__(self, threshold: float = 0.5, rearm: float = 0.28):
        if rearm >= threshold:
            raise ValueError("rearm 必须小于 threshold")
        self.threshold = threshold
        self.rearm = rearm
        self.armed = True

    def feed(self, prob: float) -> bool:
        if prob >= self.threshold:
            if self.armed:
                self.armed = False
                return True
            return False
        if prob < self.rearm:
            self.armed = True
        return False


# ======================================================================
# 音量 DSP (在子进程里运行, 避免被 nn.Speech 的 GIL 阻塞)
# ======================================================================

class VoiceEnhancer:
    """
    512 点 STFT 的轻量人声增强:

    1. 频域高通: 削弱 80 Hz 以下的风噪/低频轰鸣。
    2. 谱减: 慢速估计噪声幅度谱, 从当前帧减掉, 抑制环境白噪声。
    3. 人声频带加权: 150~1200 Hz (元音/ang、en、un 鼻韵) 提升,
       1200~3500 Hz 适度提升, 5 kHz 以上衰减。
    4. 风噪检测: 120 Hz 以下能量占比过高时进一步压低低频。
    5. 与语音模型联动: KWS 概率高或业务态时, 降低噪声门限并额外
       提升人声频带; 此时冻结噪声估计, 避免把拖音当成噪声学进去。
    6. 快/慢双包络: 快包络给亮度, 慢包络给闪烁频率。
    """

    def __init__(self, sample_rate: int = 16000, n_fft: int = 512):
        import numpy as np

        self.np = np
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.frame_seconds = n_fft / float(sample_rate)

        self.window = np.hanning(n_fft).astype(np.float32)
        self.window_gain = float(np.sqrt(np.mean(self.window * self.window)))
        self.freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate).astype(np.float32)

        w = np.ones_like(self.freqs, dtype=np.float32)
        w[self.freqs < 80.0] = 0.03
        w[(self.freqs >= 80.0) & (self.freqs < 150.0)] = 0.35
        w[(self.freqs >= 150.0) & (self.freqs <= 1200.0)] = 1.60
        w[(self.freqs > 1200.0) & (self.freqs <= 3500.0)] = 1.25
        w[self.freqs > 5000.0] = 0.50
        self.band_weight = w

        self.noise_mag = None
        self.noise_db = -60.0
        self.env_fast = 0.0
        self.env_slow = 0.0
        self.wind = 0.0
        self.peak_hist = collections.deque()

    def process(self, frame, kws_prob: float, business: float):
        np = self.np
        frame = frame.astype(np.float32, copy=False)
        frame = frame - float(frame.mean())

        x = frame * self.window
        spectrum = np.fft.rfft(x)
        mag = np.abs(spectrum).astype(np.float32)
        power = mag * mag
        total_power = float(power.sum()) + 1e-12

        frame_rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)
        frame_db = 20.0 * math.log10(frame_rms + 1e-9)

        low_ratio = float(power[self.freqs < 120.0].sum()) / total_power
        voice_hint = (kws_prob > 0.15) or (business > 0.5)

        if self.noise_mag is None:
            self.noise_mag = np.maximum(mag * 0.25, 1e-6)
            self.noise_db = frame_db - 6.0

        # 安静时快速学习噪声; 有人声/业务时几乎冻结, 防止把拖音吃掉。
        if (not voice_hint) and frame_db < self.noise_db + 8.0:
            self.noise_mag = 0.98 * self.noise_mag + 0.02 * mag
            self.noise_db = 0.98 * self.noise_db + 0.02 * frame_db
        else:
            capped = np.minimum(mag, self.noise_mag * 1.2)
            self.noise_mag = 0.9995 * self.noise_mag + 0.0005 * capped

        # 谱减
        clean_mag = np.maximum(mag - 1.6 * self.noise_mag, 0.0)

        # 风噪: 低频占比高时进一步压掉低频, 并记录一个平滑标志。
        wind_now = 1.0 if (low_ratio > 0.62 and kws_prob < 0.15) else 0.0
        self.wind = 0.90 * self.wind + 0.10 * wind_now
        if self.wind > 0.30:
            clean_mag[self.freqs < 180.0] *= 0.15

        weight = self.band_weight
        if voice_hint:
            # 鼻韵/拖音主要能量在 150~1500 Hz, 语音模型在场时再抬一点。
            weight = weight.copy()
            band = (self.freqs >= 150.0) & (self.freqs <= 1500.0)
            weight[band] *= 1.20
        clean_mag *= weight

        # 用原相位重建, 计算干净信号的 RMS。
        ratio = clean_mag / (mag + 1e-9)
        clean = np.fft.irfft(spectrum * ratio, n=self.n_fft)
        rms = float(np.sqrt(np.mean(clean * clean))) / max(self.window_gain, 1e-6)

        clean_db = 20.0 * math.log10(rms + 1e-9)
        gate_db = self.noise_db + (3.0 if voice_hint else 6.0)
        if clean_db < gate_db:
            rms = 0.0
        if self.wind > 0.60 and kws_prob < 0.10:
            rms = 0.0

        # 快包络: 20 ms attack / 150 ms release, 跟住音节和拖音。
        dt = self.frame_seconds
        attack_fast = 1.0 - math.exp(-dt / 0.020)
        release_fast = 1.0 - math.exp(-dt / 0.150)
        if rms > self.env_fast:
            self.env_fast += attack_fast * (rms - self.env_fast)
        else:
            self.env_fast += release_fast * (rms - self.env_fast)

        # 慢包络: 100 ms attack / 500 ms release, 给闪烁频率, 避免抖动。
        attack_slow = 1.0 - math.exp(-dt / 0.100)
        release_slow = 1.0 - math.exp(-dt / 0.500)
        if rms > self.env_slow:
            self.env_slow += attack_slow * (rms - self.env_slow)
        else:
            self.env_slow += release_slow * (rms - self.env_slow)

        now = time.monotonic()
        self.peak_hist.append((now, rms))
        while self.peak_hist and now - self.peak_hist[0][0] > 1.5:
            self.peak_hist.popleft()
        peak = max((v for _, v in self.peak_hist), default=0.0)

        return rms, self.env_fast, self.env_slow, peak, self.noise_db, self.wind


def _tap_reader(fifo: str, stop_event, env_fast, env_slow, peak_rms,
                noise_db, wind, kws_prob, business) -> None:
    """子进程: 从 ALSA file 插件写出的 FIFO 读 PCM, 做降噪和音量包络。"""
    try:
        import numpy as np
        enhancer = VoiceEnhancer()
    except Exception as exc:  # noqa: BLE001
        os.write(2, f"[dsp] init failed: {exc}\n".encode())
        os._exit(2)

    frame_bytes = enhancer.n_fft * 2
    buf = bytearray()

    while not stop_event.is_set() and os.getppid() != 1:
        try:
            with open(fifo, "rb", buffering=0) as f:
                while not stop_event.is_set() and os.getppid() != 1:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
                    while len(buf) >= frame_bytes:
                        raw = bytes(buf[:frame_bytes])
                        del buf[:frame_bytes]
                        frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                        rms, ef, es, peak, ndb, wnd = enhancer.process(
                            frame, kws_prob.value, business.value)
                        env_fast.value = ef
                        env_slow.value = es
                        peak_rms.value = peak
                        noise_db.value = ndb
                        wind.value = wnd
        except FileNotFoundError:
            time.sleep(0.2)
        except Exception as exc:  # noqa: BLE001
            os.write(2, f"[dsp] {exc}\n".encode())
            time.sleep(0.2)

    os._exit(0)


class MicTap:
    """管理音量 DSP 子进程; 必须在 nn.Speech 打开 pwm_mic 之前启动。"""

    def __init__(self, fifo: str, stop_event):
        self.fifo = fifo
        ctx = mp.get_context("fork")
        self.env_fast = ctx.Value("d", 0.0, lock=False)
        self.env_slow = ctx.Value("d", 0.0, lock=False)
        self.peak_rms = ctx.Value("d", 0.0, lock=False)
        self.noise_db = ctx.Value("d", -60.0, lock=False)
        self.wind = ctx.Value("d", 0.0, lock=False)
        self.kws_prob = ctx.Value("d", 0.0, lock=False)
        self.business = ctx.Value("d", 0.0, lock=False)

        parent = os.path.dirname(fifo)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(fifo):
            os.remove(fifo)
        os.mkfifo(fifo, 0o600)
        self.proc = ctx.Process(
            target=_tap_reader,
            args=(fifo, stop_event, self.env_fast, self.env_slow,
                  self.peak_rms, self.noise_db, self.wind,
                  self.kws_prob, self.business),
            daemon=True,
        )
        self.proc.start()

    def close(self) -> None:
        if self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(1)
        if os.path.exists(self.fifo):
            try:
                os.remove(self.fifo)
            except OSError:
                pass


# ======================================================================
# PWM 子进程 (sysfs, 不依赖 maix, 避免下次 fork 破坏多媒体状态)
# ======================================================================

class SysfsPwm:
    """直接写 Linux PWM sysfs, 周期单位 ns。"""

    def __init__(self, path: str, period_ns: int, dry_run: bool = False):
        self.path = path
        self.period_ns = period_ns
        self.dry_run = dry_run
        if not dry_run:
            self._ensure_export()
            self._write("enable", 0)
            self._write("period", self.period_ns)
            self._write("duty_cycle", 0)
            self._write("enable", 1)

    def _ensure_export(self) -> None:
        if os.path.isdir(self.path):
            return
        chip = os.path.dirname(self.path)
        channel = os.path.basename(self.path).replace("pwm", "")
        try:
            with open(os.path.join(chip, "export"), "w") as f:
                f.write(str(channel))
        except OSError as exc:
            if exc.errno != errno.EBUSY:
                raise
        for _ in range(50):
            if os.path.isdir(self.path):
                return
            time.sleep(0.01)
        raise RuntimeError(f"PWM export failed: {self.path}")

    def _write(self, name: str, value: int) -> None:
        with open(os.path.join(self.path, name), "w") as f:
            f.write(str(value))

    def set_duty(self, percent: float) -> None:
        if self.dry_run:
            return
        percent = clamp(percent, 0.0, 100.0)
        duty_ns = int(round(self.period_ns * percent / 100.0))
        self._write("duty_cycle", duty_ns)

    def disable(self) -> None:
        if self.dry_run:
            return
        try:
            self._write("duty_cycle", 0)
            self._write("enable", 0)
        except OSError:
            pass


def _clog(msg: str) -> None:
    try:
        os.write(1, f"[pwm {time.strftime('%H:%M:%S')}] {msg}\n".encode())
    except OSError:
        pass


def _pwm_worker(stop_event, ready_event, gate_seq, env_fast, env_slow, peak_rms,
                business, cfg) -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # 这个进程在导入 maix 之前 fork, 只等父进程把 A18/A19 复用成 PWM6/PWM7。
    if not ready_event.wait(10.0):
        _clog("pinmap ready timeout")
        os._exit(2)
    if stop_event.is_set():
        os._exit(0)

    try:
        pwm6 = SysfsPwm(cfg["pwm6_path"], cfg["period_ns"], cfg["dry_run"])
        pwm7 = SysfsPwm(cfg["pwm7_path"], cfg["period_ns"], cfg["dry_run"])
    except Exception as exc:  # noqa: BLE001
        _clog(f"PWM init failed: {exc}")
        os._exit(2)

    state = "standby"
    ref = cfg["min_ref"]
    light_level = 0.0
    last_gate_seq = gate_seq.value
    blink_phase = 0.0
    start = time.monotonic()
    last_tick = start
    last_log = 0.0

    _clog("start, standby breathing on A18/PWM6, A19/PWM7 mode=%s" % cfg["pwm7_mode"])

    try:
        while not stop_event.is_set() and os.getppid() != 1:
            now = time.monotonic()
            dt = clamp(now - last_tick, 0.001, 0.10)
            last_tick = now
            level = 0.0
            level_slow = 0.0
            bright = 0.0
            hz = cfg["blink_hz_min"]
            voice_active = False

            if cfg["demo"]:
                t = now - start
                tick_s = cfg["decay_tick_ms"] / 1000.0
                if 2.0 <= t < 7.0:
                    state = "business"
                    business.value = 1.0
                    voice_active = True
                    level = 0.5 + 0.5 * math.sin(2.0 * math.pi * 0.25 * (t - 2.0))
                    level_slow = level
                    ref = 1.0
                    target = business_brightness(
                        level, cfg["business_min"], cfg["business_max"])
                    light_level = decay_step(
                        light_level, target, cfg["work_decay"], dt, tick_s)
                    bright = light_level
                    hz = blink_hz(level_slow, cfg["blink_hz_min"], cfg["blink_hz_max"])
                    if cfg["blink_invert"]:
                        hz = cfg["blink_hz_min"] + cfg["blink_hz_max"] - hz
                elif 7.0 <= t and state == "business":
                    business.value = 1.0
                    voice_active = False
                    level = 0.0
                    level_slow = 0.0
                    light_level = decay_step(
                        light_level, 0.0, cfg["release_decay"], dt, tick_s)
                    bright = light_level
                    hz = blink_hz(0.0, cfg["blink_hz_min"], cfg["blink_hz_max"])
                    if light_level < cfg["light_threshold"]:
                        state = "standby"
                        business.value = 0.0
                        light_level = 0.0
                        bright = breathing_duty(t, cfg["standby_period"],
                                                cfg["standby_min"], cfg["standby_max"])
                else:
                    if state == "business":
                        business.value = 0.0
                    state = "standby"
                    light_level = 0.0
                    bright = breathing_duty(t, cfg["standby_period"],
                                            cfg["standby_min"], cfg["standby_max"])
            else:
                if gate_seq.value != last_gate_seq:
                    last_gate_seq = gate_seq.value
                    state = "business"
                    ref = max(peak_rms.value, env_fast.value, cfg["min_ref"])
                    init_level = clamp(env_fast.value / ref, 0.0, 1.0)
                    init_target = business_brightness(
                        init_level, cfg["business_min"], cfg["business_max"])
                    light_level = max(init_target, cfg["light_threshold"] + 1.0)
                    blink_phase = 0.0
                    business.value = 1.0
                    _clog(f"GATE -> business, ref={ref:.4f} "
                          f"init={light_level:.1f}%")

                if state == "standby":
                    bright = breathing_duty(now - start, cfg["standby_period"],
                                            cfg["standby_min"], cfg["standby_max"])
                else:
                    env = env_fast.value
                    env_s = env_slow.value
                    level = clamp(env / ref, 0.0, 1.0) if ref > 0 else 0.0
                    level_slow = clamp(env_s / ref, 0.0, 1.0) if ref > 0 else 0.0

                    voice_floor = max(cfg["voice_active_min"],
                                      cfg["voice_active_ratio"] * ref)
                    voice_active = env >= voice_floor

                    if voice_active:
                        target = business_brightness(
                            level, cfg["business_min"], cfg["business_max"])
                        decay = cfg["work_decay"]
                    else:
                        # 伪代码的 else 分支: 人声结束, 目标回 0, 以 -3/tick 加速暗化。
                        target = 0.0
                        decay = cfg["release_decay"]

                    light_level = decay_step(
                        light_level, target, decay, dt,
                        cfg["decay_tick_ms"] / 1000.0)
                    bright = light_level

                    hz = blink_hz(level_slow, cfg["blink_hz_min"], cfg["blink_hz_max"])
                    if cfg["blink_invert"]:
                        hz = cfg["blink_hz_min"] + cfg["blink_hz_max"] - hz

                    if light_level < cfg["light_threshold"]:
                        _clog(f"EXIT -> standby, light={light_level:.1f}% "
                              f"env={env:.4f} ref={ref:.4f} "
                              f"voice_active={int(voice_active)}")
                        state = "standby"
                        business.value = 0.0
                        ref = cfg["min_ref"]
                        light_level = 0.0
                        bright = breathing_duty(
                            now - start, cfg["standby_period"],
                            cfg["standby_min"], cfg["standby_max"])

            # 闪烁相位
            blink_phase += hz * dt
            if blink_phase >= 1.0:
                blink_phase -= math.floor(blink_phase)
            blink_on = blink_phase < 0.5
            in_business = (state == "business")

            duty6 = bright
            if in_business and cfg["a18_blink"] and not blink_on:
                duty6 = 0.0

            mode = cfg["pwm7_mode"]
            if not in_business:
                duty7 = duty6 if mode == "mirror" else 0.0
            elif mode == "mirror":
                duty7 = bright if (not cfg["a18_blink"] or blink_on) else 0.0
            elif mode == "freq":
                duty7 = level_slow * 100.0
            elif mode == "square":
                duty7 = 100.0 if blink_on else 0.0
            else:  # off
                duty7 = 0.0

            pwm6.set_duty(duty6)
            pwm7.set_duty(duty7)

            if now - last_log >= 1.0:
                last_log = now
                if in_business:
                    _clog(f"business level={level:.2f}/{level_slow:.2f} "
                          f"env={env_fast.value:.4f} light={light_level:.0f}% "
                          f"voice={int(voice_active)} bright={duty6:.0f}% "
                          f"hz={hz:.1f} A19={duty7:.0f}%")
                else:
                    _clog(f"standby breath={duty6:.1f}% raw_env={env_fast.value:.4f}")

            elapsed = time.monotonic() - now
            time.sleep(max(0.0, 1.0 / cfg["update_hz"] - elapsed))
    finally:
        try:
            pwm6.set_duty(0)
            pwm7.set_duty(0)
            pwm6.disable()
            pwm7.disable()
        except Exception:  # noqa: BLE001
            pass
        _clog("stopped, PWM off")
        os._exit(0)


def _pwm_off(path: str) -> None:
    """父进程兜底关闭 PWM, 防止子进程被 SIGKILL 后灯常亮。"""
    for name, value in (("duty_cycle", 0), ("enable", 0)):
        try:
            with open(os.path.join(path, name), "w") as f:
                f.write(str(value))
        except OSError:
            pass


# ======================================================================
# 配置与主进程
# ======================================================================

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def build_config() -> dict:
    freq = max(1, _env_int("PWM_FREQ", 18000))
    mode = os.environ.get("PWM7_MODE", "freq").strip().lower()
    if mode not in ("freq", "mirror", "square", "off"):
        mode = "freq"
    gate_threshold = _env_float("VOICE_GATE_THRESHOLD", 0.5)
    gate_rearm = _env_float("VOICE_GATE_REARM", 0.28)
    if gate_rearm >= gate_threshold:
        gate_rearm = gate_threshold * 0.5

    light_threshold = clamp(_env_float("LIGHT_THRESHOLD", 35.0), 0.0, 99.0)
    business_min = max(_env_float("BUSINESS_MIN", 40.0), light_threshold + 1.0)
    business_max = clamp(_env_float("BUSINESS_MAX", 100.0), business_min, 100.0)

    return {
        "model": os.environ.get("VOICE_AM_MODEL", "/root/models/am_3332_192_int8.mud"),
        "keyword_pinyin": os.environ.get("VOICE_KEYWORD_PINYIN", "chang2 chun1"),
        "gate_threshold": gate_threshold,
        "gate_rearm": gate_rearm,
        "alsa_device": os.environ.get("VOICE_ALSA_DEVICE", "pwm_mic"),
        "fifo": os.environ.get("VOICE_TAP_FIFO", "/root/surplife/run/surplife_pwm_mic.pcm"),
        "pwm6_path": os.environ.get("PWM6_PATH", "/sys/class/pwm/pwmchip4/pwm2"),
        "pwm7_path": os.environ.get("PWM7_PATH", "/sys/class/pwm/pwmchip4/pwm3"),
        "period_ns": int(1_000_000_000 / freq),
        "update_hz": clamp(_env_int("PWM_UPDATE_HZ", 100), 20, 200),
        "pwm7_mode": mode,
        "a18_blink": _env_bool("A18_BLINK", False),
        "blink_hz_min": _env_float("BLINK_HZ_MIN", 1.0),
        "blink_hz_max": _env_float("BLINK_HZ_MAX", 8.0),
        "blink_invert": _env_bool("BLINK_INVERT", False),
        "standby_min": _env_float("STANDBY_MIN", 5.0),
        "standby_max": _env_float("STANDBY_MAX", 35.0),
        "standby_period": _env_float("STANDBY_PERIOD", 4.0),
        "business_min": business_min,
        "business_max": business_max,
        "light_threshold": light_threshold,
        "decay_tick_ms": clamp(_env_float("DECAY_TICK_MS", 20.0), 1.0, 1000.0),
        "work_decay": max(0.0, _env_float("WORK_DECAY_PER_TICK", 1.0)),
        "release_decay": max(0.0, _env_float("RELEASE_DECAY_PER_TICK", 3.0)),
        "voice_active_min": max(0.0, _env_float("VOICE_ACTIVE_MIN", 0.0015)),
        "voice_active_ratio": max(0.0, _env_float("VOICE_ACTIVE_RATIO", 0.02)),
        "min_ref": _env_float("MIN_REF", 0.002),
        "dry_run": _env_bool("PWM_DRY_RUN", False),
        "demo": _env_bool("PWM_DEMO", False),
        "kws_debug": _env_bool("VOICE_KWS_DEBUG", False),
        # 仅用于无真人说话时的端到端诊断: N 秒后注入一次门控事件。
        "test_gate_after": _env_float("PWM_TEST_GATE_AFTER", 0.0),
    }


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("SURPLIFE_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = build_config()
    log.info("config: model=%s alsa=%s pwm=%d Hz update=%d Hz mode=%s dry=%s demo=%s",
             cfg["model"], cfg["alsa_device"], 1_000_000_000 // cfg["period_ns"],
             cfg["update_hz"], cfg["pwm7_mode"], cfg["dry_run"], cfg["demo"])
    log.info("decay: threshold=%.0f%% tick=%.0fms work=%.1f release=%.1f "
             "voice_min=%.4f voice_ratio=%.3f",
             cfg["light_threshold"], cfg["decay_tick_ms"],
             cfg["work_decay"], cfg["release_decay"],
             cfg["voice_active_min"], cfg["voice_active_ratio"])

    ctx = mp.get_context("fork")
    stop_event = ctx.Event()
    gate_seq = ctx.Value("i", 0, lock=False)

    # 1) 先 fork 音量 DSP, 此时还没有导入 maix, 避免把多媒体状态带进子进程。
    tap = MicTap(cfg["fifo"], stop_event)

    # 2) 再 fork PWM 子进程; 它只写 sysfs, 等父进程设置好 A18/A19 复用后再启动。
    #    这样它不会继承 maix/多媒体状态, 在 128 MB 内存的板子上更省。
    pwm_ready = ctx.Event()
    pwm_proc = ctx.Process(
        target=_pwm_worker,
        args=(stop_event, pwm_ready, gate_seq, tap.env_fast, tap.env_slow,
              tap.peak_rms, tap.business, cfg),
        daemon=True,
    )
    pwm_proc.start()

    speech = None
    try:
        # 3) 父进程导入 maix, 设置 A18/A19 的 PWM 复用功能。
        from maix import app, err, nn, pinmap

        for pin, func in (("A18", "PWM6"), ("A19", "PWM7")):
            ret = pinmap.set_pin_function(pin, func)
            if ret != err.Err.ERR_NONE:
                log.warning("pinmap %s -> %s failed: %s", pin, func, ret)
        pwm_ready.set()

        speech = nn.Speech(cfg["model"])
        ret = speech.init(nn.SpeechDevice.DEVICE_MIC, cfg["alsa_device"])
        if ret != err.Err.ERR_NONE:
            log.error("打开 ALSA 设备 %s 失败: %s", cfg["alsa_device"], ret)
            return 1

        gate = GateDetector(cfg["gate_threshold"], cfg["gate_rearm"])
        last_prob_log = 0.0

        def callback(data, length):
            nonlocal last_prob_log
            if length < 1:
                return
            try:
                prob = float(data[0])
            except (TypeError, ValueError):
                return
            tap.kws_prob.value = prob
            if cfg["kws_debug"]:
                now = time.monotonic()
                if prob >= 0.02 and now - last_prob_log >= 0.2:
                    log.info("KWS p=%.3f", prob)
                    last_prob_log = now
            if gate.feed(prob):
                gate_seq.value = gate_seq.value + 1
                log.info("GATE: '%s' p=%.3f", cfg["keyword_pinyin"], prob)

        speech.kws([cfg["keyword_pinyin"]], [0.1], callback, True)
        log.info("监听中: %s (门限 %.2f, 回武装 %.2f, 无时间不应期)",
                 cfg["keyword_pinyin"], cfg["gate_threshold"], cfg["gate_rearm"])

        loop_start = time.monotonic()
        test_gate_sent = False
        while not app.need_exit():
            if not pwm_proc.is_alive():
                log.error("PWM 子进程退出")
                break
            if not tap.proc.is_alive():
                log.error("音量 DSP 子进程退出")
                break
            if (cfg["test_gate_after"] > 0 and not test_gate_sent
                    and time.monotonic() - loop_start >= cfg["test_gate_after"]):
                gate_seq.value = gate_seq.value + 1
                test_gate_sent = True
                log.info("TEST GATE: 已注入一次门控事件")
            if cfg["kws_debug"] and time.monotonic() - last_prob_log >= 2.0:
                log.info("KWS idle p=%.3f", tap.kws_prob.value)
                last_prob_log = time.monotonic()
            if speech.run(1) < 1:
                log.warning("音频输入结束")
                break
    except KeyboardInterrupt:
        log.info("收到 Ctrl+C")
    finally:
        stop_event.set()
        if pwm_proc.is_alive():
            pwm_proc.join(2.0)
            if pwm_proc.is_alive():
                pwm_proc.terminate()
                pwm_proc.join(1.0)
        _pwm_off(cfg["pwm6_path"])
        _pwm_off(cfg["pwm7_path"])
        tap.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
