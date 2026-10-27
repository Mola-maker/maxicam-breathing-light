#!/bin/sh
# 语音门控 18kHz PWM 灯控 (A18/PWM6, A19/PWM7)
APP_DIR="$(cd "$(dirname "$0")" && pwd)"

# 语音模型是后台关键进程：尽早降低 OOM 被杀概率。
# nice 值由 voice_pwm.py 里的 raise_voice_priority() 设置。
if [ "$(id -u)" = "0" ]; then
    echo "${VOICE_OOM_SCORE_ADJ:--800}" > /proc/$$/oom_score_adj 2>/dev/null || true
fi

cd "$APP_DIR" || exit 1
exec python3 -u voice_pwm.py
