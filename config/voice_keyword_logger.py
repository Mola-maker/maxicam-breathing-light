#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
持续记录 MaixCAM 语音模型的关键词与置信度。

数据源:
    192.168.1.183:/root/surplife/pwm.log
    （voice_pwm.py 输出的 CHAR 单字事件、SEQ GATE 拼装结果、
     GATE[...] 门控事件；兼容旧版 KWS p=... 行）

输出:
    /home/jlu/桌面/config/voice_keyword_log.txt
    格式: 本机时间  事件  关键词  置信度

脚本会一直运行并自动重连，直到手动停止。
"""

import fcntl
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path("/home/jlu/桌面/config")
LOG_PATH = BASE / "voice_keyword_log.txt"
LOCK_PATH = BASE / ".voice_keyword_logger.lock"

HOST = "192.168.1.183"
SOCK = "/tmp/opencode/maixcam-183.sock"
REMOTE_LOG = "/root/surplife/pwm.log"

# 与 voice_pwm.py 的 KWS 调试输出保持一致：低于该值不记入 txt。
MIN_CONFIDENCE = 0.02
# 初始主关键词；连接后如果看到启动日志会自动更新。
main_keyword = "changchun"

KWS_RE = re.compile(r"KWS p=([0-9]*\.?[0-9]+)(.*)$")
CHAR_RE = re.compile(r"CHAR\s+([A-Za-z0-9_]+)\s+p=([0-9]*\.?[0-9]+)")
SEQ_GATE_RE = re.compile(
    r"SEQ GATE branch=(\S+)\s+score=([0-9]*\.?[0-9]+)")
KV_RE = re.compile(r"([A-Za-z0-9_]+)\s*=\s*([0-9]*\.?[0-9]+)")
GATE_RE = re.compile(r"GATE\[([^\]]+)\]:\s*(.*)$")

SSH_BASE = [
    "ssh",
    "-S", SOCK,
    "-o", "StrictHostKeyChecking=no",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=8",
    "-o", "ServerAliveInterval=10",
    "-o", "ServerAliveCountMax=2",
    "-o", "BatchMode=yes",
    f"root@{HOST}",
]


def status(msg: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}", file=sys.stderr, flush=True)


def ssh_ok() -> bool:
    if not os.path.exists(SOCK):
        return False
    try:
        r = subprocess.run(
            SSH_BASE + ["true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
        )
        return r.returncode == 0
    except Exception:
        return False


def get_password():
    """从当前用户的 GNOME Keyring 读取板子密码。"""
    import gi

    gi.require_version("Secret", "1")
    from gi.repository import Secret

    svc = Secret.Service.get_sync(Secret.ServiceFlags.LOAD_COLLECTIONS, None)
    for col in svc.get_collections():
        for item in col.get_items():
            attrs = item.get_attributes() or {}
            if (attrs.get("server") == "maixcam-4e47.local"
                    and attrs.get("user") == "root"):
                item.load_secret_sync(None)
                secret = item.get_secret()
                return secret.get_text() if secret else None
    return None


def ensure_master() -> bool:
    """确保 SSH ControlMaster 可用；失效时用 keyring 密码重建。"""
    if ssh_ok():
        return True

    try:
        if os.path.exists(SOCK):
            os.unlink(SOCK)
    except OSError:
        pass
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)

    try:
        pw = get_password()
    except Exception as exc:
        status(f"读取 keyring 失败: {exc!r}")
        return False
    if not pw:
        status("没有找到板子密码（keyring）")
        return False

    try:
        import pexpect
    except Exception as exc:
        status(f"缺少 pexpect: {exc!r}")
        return False

    args = [
        "ssh", "-M", "-S", SOCK,
        "-o", "ControlPersist=900",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=no",
        "-o", "PubkeyAuthentication=no",
        "-o", "PreferredAuthentications=password,keyboard-interactive",
        "-o", "NumberOfPasswordPrompts=1",
        "-o", "LogLevel=ERROR",
        "-fN", f"root@{HOST}",
    ]
    child = pexpect.spawn(args[0], args[1:], timeout=15, encoding="utf-8")
    i = child.expect([
        r"[Pp]assword:",
        r"Permission denied",
        pexpect.EOF,
        pexpect.TIMEOUT,
    ])
    if i == 0:
        child.sendline(pw)
        j = child.expect([pexpect.EOF, r"Permission denied", pexpect.TIMEOUT],
                         timeout=15)
        if j == 1:
            status("SSH 密码认证失败")
            return False
    elif i == 1:
        status("SSH 密码认证失败")
        return False

    for _ in range(30):
        if os.path.exists(SOCK) and ssh_ok():
            return True
        time.sleep(0.2)
    status("SSH ControlMaster 创建失败")
    return False


def emit(out, event: str, keyword: str, confidence: float) -> None:
    ts = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    out.write(f"{ts}  {event:<4}  {keyword}  {confidence:.4f}\n")
    out.flush()


def handle_line(out, line: str) -> None:
    global main_keyword

    # 启动/重连日志里带有当前关键词名，自动同步，避免写死。
    if "监听中 OR:" in line:
        try:
            part = line.split("监听中 OR:", 1)[1]
            main_keyword = part.split("|", 1)[0].strip()
        except Exception:
            pass
        return
    if "监听中:" in line:
        try:
            part = line.split("监听中:", 1)[1]
            main_keyword = part.split("(", 1)[0].strip()
        except Exception:
            pass
        return
    if "识别单字:" in line:
        try:
            part = line.split("识别单字:", 1)[1]
            main_keyword = part.split("(", 1)[0].strip()
        except Exception:
            pass
        return

    # 新版单字事件: CHAR chang1 p=0.106 t=... mono=... dt=...
    m = CHAR_RE.search(line)
    if m:
        keyword = m.group(1)
        try:
            confidence = float(m.group(2))
        except ValueError:
            return
        if confidence >= MIN_CONFIDENCE:
            emit(out, "CHAR", keyword, confidence)
        return

    # 新版序列结果: SEQ GATE branch=changchun score=0.175 ...
    m = SEQ_GATE_RE.search(line)
    if m:
        try:
            confidence = float(m.group(2))
        except ValueError:
            return
        if confidence >= MIN_CONFIDENCE:
            emit(out, "SEQ", m.group(1), confidence)
        return

    # 兼容旧版 KWS 概率行: KWS p=0.567 ang1=0.000
    m = KWS_RE.search(line)
    if m:
        try:
            pairs = [(main_keyword, float(m.group(1)))]
        except ValueError:
            return
        for name, val in KV_RE.findall(m.group(2)):
            try:
                pairs.append((name, float(val)))
            except ValueError:
                pass
        if not pairs:
            return
        keyword, confidence = max(pairs, key=lambda x: x[1])
        if confidence >= MIN_CONFIDENCE:
            emit(out, "KWS", keyword, confidence)
        return

    # 门控事件: GATE[chang2 chun1]: chang2 chun1=0.567, ang1=0.000
    m = GATE_RE.search(line)
    if m:
        branch = m.group(1).strip()
        values = {}
        for name, val in KV_RE.findall(m.group(2)):
            try:
                values[name] = float(val)
            except ValueError:
                pass
        candidates = [x.strip() for x in branch.split("+") if x.strip()]
        confs = [values[x] for x in candidates if x in values]
        if len(candidates) > 1 and len(confs) == len(candidates):
            confidence = sum(confs) / len(confs)
        elif confs:
            confidence = max(confs)
        else:
            confidence = max(values.values(), default=0.0)
        emit(out, "GATE", branch, confidence)


def main() -> int:
    BASE.mkdir(parents=True, exist_ok=True)

    lock = LOCK_PATH.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("voice_keyword_logger 已经在运行", file=sys.stderr)
        return 1

    new_file = (not LOG_PATH.exists()) or LOG_PATH.stat().st_size == 0
    out = LOG_PATH.open("a", encoding="utf-8", buffering=1)
    if new_file:
        out.write("# 时间                         事件  关键词             置信度\n")
        out.write(f"# 数据源: {HOST}:{REMOTE_LOG}\n")
        out.flush()

    status(f"记录到 {LOG_PATH}")
    status("启动，等待语音日志……")

    while True:
        if not ensure_master():
            time.sleep(5)
            continue

        status("已连接，开始 tail 语音日志")
        cmd = SSH_BASE + ["tail", "-n", "0", "-F", REMOTE_LOG]
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            for line in proc.stdout:
                handle_line(out, line)
            proc.wait()
        except Exception as exc:
            status(f"tail 异常: {exc!r}")
        finally:
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

        status("tail 断开，3 秒后重连")
        time.sleep(3)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
