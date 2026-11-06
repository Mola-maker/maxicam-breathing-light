#!/bin/sh
ROOT="/root/JLU_LEDLAB"
PIDFILE="$ROOT/run/voice.pid"

if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        kill -INT "$PID" 2>/dev/null
        i=0
        while [ "$i" -lt 30 ]; do
            kill -0 "$PID" 2>/dev/null || break
            sleep 0.1
            i=$((i + 1))
        done
        kill -0 "$PID" 2>/dev/null && kill -TERM "$PID" 2>/dev/null
    fi
fi
rm -f "$PIDFILE"
echo "JLU_LEDLAB voice stopped"
