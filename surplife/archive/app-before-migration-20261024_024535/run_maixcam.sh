#!/bin/sh
# MaixCAM 启动脚本: 依赖装在 /root/surplife/lib (纯 Python, 含 pure-python dbus_fast)
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="/root/surplife/lib:$APP_DIR"
hciconfig hci0 up 2>/dev/null
bluetoothctl power on >/dev/null 2>&1
cd "$APP_DIR" && exec python3 main.py
