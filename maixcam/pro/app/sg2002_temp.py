#!/usr/bin/env python3
"""
SG2002 片上温度传感器读取工具（只读）

用途:
    给低温温控板/上位机提供 SG2002 的实时结温。默认读取 Linux  thermal
    framework 已经暴露的 sysfs 节点；如果该节点不可用，可以退回直接读取
    SG2002 TEMPSEN 寄存器。

数据来源:
    /sys/class/thermal/thermal_zone0/temp      单位 m°C，推荐
    0x030E0000 + 0x20                          TEMPSEN ch0 result

换算公式（与 Linux cv181x_thermal.c 完全一致）:
    temp_mC = raw * 1000 * 716 // 2048 - 273000

注意:
    本工具只读寄存器，不修改 TEMPSEN 配置。生产环境请优先使用 sysfs，
    避免和内核驱动同时操作同一组寄存器。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

SYSFS_TEMP = "/sys/class/thermal/thermal_zone0/temp"
REG_BASE = 0x030E0000
REG_CH0_RESULT = 0x20
RAW_MASK = 0x1FFF


def raw_to_mc(raw: int) -> int:
    """TEMPSEN 13-bit 原始值 -> m°C，复刻 cv181x_thermal.c 的整数算法。"""
    return (raw & RAW_MASK) * 1000 * 716 // 2048 - 273000


def mc_to_c(mc: int) -> float:
    return mc / 1000.0


def read_sysfs_mc(path: str = SYSFS_TEMP) -> int:
    with open(path, "r", encoding="ascii") as f:
        return int(f.read().strip())


def read_reg_raw(base: int = REG_BASE) -> int:
    """通过 devmem 只读 TEMPSEN 寄存器，返回 ch0 结果的 13-bit 原始值。

    不用 Python mmap 直接映射 /dev/mem：在这块 SG2002 上对 device memory
    做多字节读取会触发 SIGSEGV/SIGBUS，busybox devmem 的单次 32-bit 读稳定。
    """
    devmem = shutil.which("devmem") or "/usr/sbin/devmem"
    if not shutil.which(devmem) and not os.path.exists(devmem):
        raise OSError("devmem not found; cannot read TEMPSEN register")
    addr = base + REG_CH0_RESULT
    try:
        out = subprocess.check_output(
            [devmem, hex(addr)],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=2.0,
        ).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(f"devmem {hex(addr)} failed: {exc}") from exc
    try:
        value = int(out, 0)
    except ValueError as exc:
        raise OSError(f"devmem {hex(addr)} returned {out!r}") from exc
    return value & RAW_MASK


def sample(source: str) -> dict:
    """返回一次温度采样。source: auto/sysfs/reg。"""
    if source not in ("auto", "sysfs", "reg"):
        raise ValueError(f"unknown source: {source}")

    if source in ("auto", "sysfs"):
        try:
            mc = read_sysfs_mc()
            return {
                "ts": time.time(),
                "temp_c": round(mc_to_c(mc), 3),
                "temp_mc": mc,
                "source": "sysfs",
            }
        except (OSError, ValueError):
            if source == "sysfs":
                raise

    raw = read_reg_raw()
    mc = raw_to_mc(raw)
    return {
        "ts": time.time(),
        "temp_c": round(mc_to_c(mc), 3),
        "temp_mc": mc,
        "source": "reg",
        "raw": raw,
    }


def format_text(item: dict) -> str:
    suffix = ""
    if item["source"] == "reg":
        suffix = f" (reg raw={item['raw']})"
    else:
        suffix = " (sysfs)"
    return f"{item['temp_c']:.3f} °C{suffix}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="读取 SG2002 片上温度传感器（只读）",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "sysfs", "reg"),
        default="auto",
        help="auto=优先 sysfs，失败时读寄存器；默认 auto",
    )
    parser.add_argument("--json", action="store_true", help="每行输出一个 JSON")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="循环采样间隔秒数，默认 1.0",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="采样次数，0=无限循环；默认 1",
    )
    args = parser.parse_args(argv)

    if args.interval < 0 or args.count < 0:
        parser.error("--interval/--count 不能为负数")

    try:
        n = 0
        while args.count == 0 or n < args.count:
            item = sample(args.source)
            if args.json:
                print(json.dumps(item, ensure_ascii=False), flush=True)
            else:
                print(format_text(item), flush=True)
            n += 1
            if args.count == 0 or n < args.count:
                time.sleep(args.interval)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError) as exc:
        print(f"sg2002_temp: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
