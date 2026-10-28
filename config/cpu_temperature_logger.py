#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通过无线 SSH 按 1 Hz 采集 MaixCAM/SG2002 的 CPU 结温。

数据源:
    192.168.1.183:/sys/class/thermal/thermal_zone0/temp

输出:
    /home/jlu/桌面/config/CPU-temperature/cpu_temperature_YYYYMMDD.txt
    每行: 本机时间  temp_c  temp_mc
    文件头会写明列名和数据源。

脚本会一直运行并自动重连，直到手动停止或指定 --duration。
"""

from __future__ import annotations

import argparse
import fcntl
import os
import select
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

BASE = Path("/home/jlu/桌面/config")
OUT_DIR = BASE / "CPU-temperature"
LOCK_PATH = BASE / ".cpu_temperature_logger.lock"

HOST = "192.168.1.183"
REMOTE_TEMP = "/sys/class/thermal/thermal_zone0/temp"
REMOTE_CMD = (
    "while true; do "
    f"cat {REMOTE_TEMP} 2>/dev/null || echo ERR; "
    "sleep 1; "
    "done"
)

# 复用现有语音日志器的 SSH ControlMaster/keyring 逻辑，避免重复维护密码读取。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from voice_keyword_logger import SSH_BASE, ensure_master, status  # noqa: E402


def open_daily_log(now: datetime):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"cpu_temperature_{now:%Y%m%d}.txt"
    is_new = (not path.exists()) or path.stat().st_size == 0
    fh = open(path, "a", encoding="utf-8", buffering=1)
    if is_new:
        fh.write("# MaixCAM/SG2002 CPU temperature, 1 Hz\n")
        fh.write(f"# host: {HOST}\n")
        fh.write(f"# source: {REMOTE_TEMP}\n")
        fh.write("# columns: local_time temp_c temp_mc\n")
    return path, fh


def write_sample(fh, mc: int) -> None:
    now = datetime.now().astimezone()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    fh.write(f"{ts}  {mc / 1000.0:.3f}  {mc}\n")


def parse_mc(line: str):
    line = line.strip()
    if not line or line == "ERR":
        return None
    try:
        return int(line)
    except ValueError:
        return None


def run(duration: float = 0.0) -> int:
    stop = threading.Event()
    deadline = time.monotonic() + duration if duration > 0 else None

    def on_signal(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lock = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        status("cpu_temperature_logger 已在运行")
        return 1

    log_path = None
    log_date = None
    fh = None
    try:
        status(f"输出目录: {OUT_DIR}")
        while not stop.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                break

            if not ensure_master():
                status("SSH ControlMaster 不可用，5 秒后重试")
                stop.wait(5.0)
                continue

            status("SSH 已连接，开始 1 Hz 采集")
            proc = subprocess.Popen(
                SSH_BASE + [REMOTE_CMD],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            try:
                while not stop.is_set():
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                    if not ready:
                        if proc.poll() is not None:
                            break
                        continue
                    line = proc.stdout.readline()
                    if not line:
                        break
                    mc = parse_mc(line)
                    if mc is None:
                        continue

                    now = datetime.now()
                    today = now.strftime("%Y%m%d")
                    if fh is None or log_date != today:
                        if fh is not None:
                            fh.close()
                        log_path, fh = open_daily_log(now)
                        log_date = today
                        status(f"写入: {log_path}")
                    write_sample(fh, mc)
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=2.0)

            if deadline is not None and time.monotonic() >= deadline:
                break
            if not stop.is_set():
                status("SSH 断开，2 秒后重连")
                stop.wait(2.0)
    finally:
        if fh is not None:
            fh.close()
        try:
            fcntl.flock(lock, fcntl.LOCK_UN)
        finally:
            lock.close()
        status("cpu_temperature_logger 已停止")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="通过无线 SSH 按 1 Hz 记录 SG2002 CPU 温度",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="运行秒数，0=一直运行；默认 0",
    )
    args = parser.parse_args()
    if args.duration < 0:
        parser.error("--duration 不能为负数")
    return run(args.duration)


if __name__ == "__main__":
    raise SystemExit(main())
