#!/usr/bin/env python3
"""
LUMEN UI 的实时 KWS 进程。

复用 voice_pwm.py 的麦克风 DSP、门控检测和 Maix-Speech KWS，但**不写 PWM**。
它把 gate / env / env_slow / peak / prob 通过一个非阻塞 FIFO 发给 lamp_ui.py，
由 UI 继续使用自己的衰减参数驱动画面（以及可选的 A18/A19 硬件输出）。

架构:
  lamp_ui.py
      └─ live_kws.py (KWS 主进程)
           ├─ voice_pwm.MicTap 子进程 (100 Hz 音量 DSP)
           └─ publisher 子进程 (20 Hz 写 JSON FIFO)

publisher 必须是独立进程而不是线程: speech.run(1) 每次会占住 GIL 数百毫秒，
线程拿不到足够的时间片，UI 收到的包络会变成 ~1 Hz。

单独调试:
    python3 live_kws.py --fifo /tmp/lamp_ui_kws.fifo
    # 另一个终端: cat /tmp/lamp_ui_kws.fifo

测试注入（不依赖真人说话）:
    LIVE_KWS_TEST_GATE_AFTER=4 LIVE_KWS_TEST_ENV=0.8 \
        python3 live_kws.py --fifo /tmp/lamp_ui_kws.fifo
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import signal
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

import voice_pwm as vp  # noqa: E402


class EventWriter:
    """向 UI 的 FIFO 写 JSON 行；没有读者时丢弃，绝不阻塞 KWS。"""

    def __init__(self, path: str):
        self.path = path
        self.fd = None

    def _open(self) -> bool:
        if self.fd is not None:
            return True
        try:
            self.fd = os.open(self.path, os.O_WRONLY | os.O_NONBLOCK)
            return True
        except OSError:
            return False

    def write(self, obj: dict) -> None:
        if not self._open():
            return
        try:
            line = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
            os.write(self.fd, line)
        except (BrokenPipeError, OSError):
            try:
                if self.fd is not None:
                    os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def close(self) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _publisher_worker(fifo, rate, stop_event, ready_flag, gate_counter,
                      business_until, env_fast, env_slow, peak_rms, kws_prob,
                      business, test_gate_after, test_env, test_env_hold):
    """独立发布进程：即使 KWS 主进程被 speech.run 占住，也保持 20 Hz。"""
    writer = EventWriter(fifo)
    started = None
    test_sent = False
    test_env_until = 0.0
    try:
        while not stop_event.is_set() and os.getppid() != 1:
            now = time.monotonic()
            ready = bool(ready_flag.value)
            if ready:
                if started is None:
                    started = now
                if (test_gate_after > 0.0 and not test_sent
                        and now - started >= test_gate_after):
                    test_sent = True
                    with gate_counter.get_lock():
                        gate_counter.value += 1
                    business_until.value = now + 4.0
                    business.value = 1.0
                    if test_env >= 0.0:
                        test_env_until = now + max(0.5, test_env_hold)
                    print("TEST GATE: seq=%d" % gate_counter.value, flush=True)
            business.value = 1.0 if now < business_until.value else 0.0
            env = env_fast.value
            env_s = env_slow.value
            peak = peak_rms.value
            if test_env >= 0.0 and now < test_env_until:
                env = test_env
                env_s = test_env
                peak = max(peak, test_env)
            writer.write({
                "ready": ready,
                "state": "listening" if ready else "loading",
                "gate": int(gate_counter.value),
                "env": round(float(env), 6),
                "env_slow": round(float(env_s), 6),
                "peak": round(float(peak), 6),
                "prob": round(float(kws_prob.value), 6),
                "business": round(float(business.value), 3),
                "t": round(now - started, 3) if started is not None else 0.0,
            })
            delay = 1.0 / rate - (time.monotonic() - now)
            if delay > 0.0:
                time.sleep(delay)
    finally:
        writer.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fifo", required=True, help="UI 事件 FIFO")
    parser.add_argument("--rate", type=float,
                        default=_env_float("LIVE_KWS_PUBLISH_HZ", 20.0))
    parser.add_argument("--business-hold", type=float,
                        default=_env_float("LIVE_KWS_BUSINESS_HOLD", 4.0))
    args = parser.parse_args()
    rate = max(2.0, min(50.0, args.rate))
    cfg = vp.build_config()
    ctx = mp.get_context("fork")
    stop_event = ctx.Event()
    ready_flag = ctx.Value("i", 0)
    gate_counter = ctx.Value("i", 0)
    business_until = ctx.Value("d", 0.0)
    writer = None
    tap = None
    pub_proc = None
    speech = None

    def _stop(_signum, _frame):
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except Exception:
            pass

    gate = vp.GateDetector(cfg["gate_threshold"], cfg["gate_rearm"])

    def callback(data, length):
        if length < 1:
            return
        try:
            prob = float(data[0])
        except (TypeError, ValueError):
            return
        if tap is not None:
            tap.kws_prob.value = prob
        if gate.feed(prob):
            with gate_counter.get_lock():
                gate_counter.value += 1
            business_until.value = time.monotonic() + max(0.0, args.business_hold)
            if tap is not None:
                tap.business.value = 1.0
            print("GATE: '%s' p=%.3f seq=%d" %
                  (cfg["keyword_pinyin"], prob, gate_counter.value), flush=True)

    try:
        # 先 fork DSP，再 fork publisher，最后才导入 maix / nn.Speech。
        # 这与 voice_pwm.py 的顺序一致，避免把 maix 的多媒体状态带进 fork。
        tap = vp.MicTap(cfg["fifo"], stop_event)
        test_gate_after = _env_float("LIVE_KWS_TEST_GATE_AFTER", 0.0)
        test_env = _env_float("LIVE_KWS_TEST_ENV", -1.0)
        test_env_hold = _env_float("LIVE_KWS_TEST_ENV_HOLD", 3.0)
        pub_proc = ctx.Process(
            target=_publisher_worker,
            args=(args.fifo, rate, stop_event, ready_flag, gate_counter,
                  business_until, tap.env_fast, tap.env_slow, tap.peak_rms,
                  tap.kws_prob, tap.business, test_gate_after, test_env,
                  test_env_hold),
            daemon=True)
        pub_proc.start()

        # 父进程的 writer 在 publisher fork 之后才创建，避免继承同一个 fd。
        writer = EventWriter(args.fifo)
        writer.write({"ready": False, "state": "loading", "gate": 0})

        from maix import app, err, nn  # noqa: PLC0415

        speech = nn.Speech(cfg["model"])
        ret = speech.init(nn.SpeechDevice.DEVICE_MIC, cfg["alsa_device"])
        if ret != err.Err.ERR_NONE:
            raise RuntimeError("打开 ALSA 设备 %s 失败: %s" %
                               (cfg["alsa_device"], ret))

        speech.kws([cfg["keyword_pinyin"]], [0.1], callback, True)
        ready_flag.value = 1
        writer.write({"ready": True, "state": "ready",
                      "gate": int(gate_counter.value)})
        print("READY: %s (threshold %.2f, rearm %.2f)" %
              (cfg["keyword_pinyin"], cfg["gate_threshold"],
               cfg["gate_rearm"]), flush=True)

        while (not stop_event.is_set() and not app.need_exit()
               and os.getppid() != 1):
            if pub_proc is not None and not pub_proc.is_alive():
                print("publisher 已退出", flush=True)
                break
            if speech.run(1) < 1:
                print("音频输入结束", flush=True)
                break
    except Exception as exc:  # noqa: BLE001
        print("live_kws error: %s" % exc, flush=True)
        if writer is not None:
            writer.write({"ready": False, "state": "error", "error": str(exc)})
        return 1
    finally:
        stop_event.set()
        if pub_proc is not None:
            pub_proc.join(timeout=1.0)
            if pub_proc.is_alive():
                pub_proc.terminate()
                pub_proc.join(timeout=0.5)
        if tap is not None:
            tap.close()
        if writer is not None:
            writer.write({"ready": False, "state": "stopped"})
            writer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
