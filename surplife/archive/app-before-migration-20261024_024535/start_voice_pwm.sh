#!/bin/sh
# 后台启动 voice_pwm, 记录 PID 和日志。环境变量会原样传给 Python。
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE=/root/surplife/pwm.pid
LOGFILE=/root/surplife/pwm.log

if [ -f "$PIDFILE" ]; then
    OLD="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
        echo "voice_pwm 已在运行: PID=$OLD"
        exit 0
    fi
fi

cd "$APP_DIR" || exit 1
nohup ./run_voice_pwm.sh >>"$LOGFILE" 2>&1 &
NEW=$!
echo "$NEW" >"$PIDFILE"
echo "voice_pwm 已启动: PID=$NEW"
echo "日志: $LOGFILE"
