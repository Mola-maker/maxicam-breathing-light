#!/bin/sh
# 语音门控 18kHz PWM 灯控 (A18/PWM6, A19/PWM7)
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR" && exec python3 voice_pwm.py
