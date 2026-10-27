#!/bin/sh
# 语音关键词控制 (需先启动 run_maixcam.sh 提供的 API)
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" && exec python3 voice_kws.py
