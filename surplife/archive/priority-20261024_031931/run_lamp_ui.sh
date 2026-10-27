#!/bin/sh
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE=/root/surplife/pwm.pid
KWS_PID=/root/surplife/run/lamp_ui_kws.pid

cleanup_kws() {
    if [ -f "$KWS_PID" ]; then
        KPID="$(cat "$KWS_PID" 2>/dev/null)"
        if [ -n "$KPID" ]; then
            kill -TERM "$KPID" 2>/dev/null
            sleep 1
            kill -KILL "$KPID" 2>/dev/null
        fi
        rm -f "$KWS_PID"
    fi
    rm -f /root/surplife/run/lamp_ui_kws.fifo
}

cleanup_kws

WAS_RUNNING=0
if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        WAS_RUNNING=1
        "$APP_DIR/stop_voice_pwm.sh" >/dev/null 2>&1
    fi
fi

cd "$APP_DIR" || exit 1
python3 lamp_ui.py "$@"
RC=$?

cleanup_kws
sleep 1

if [ "$WAS_RUNNING" = "1" ]; then
    "$APP_DIR/start_voice_pwm.sh" >/dev/null 2>&1
fi
exit $RC
