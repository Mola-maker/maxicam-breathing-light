#!/bin/sh
ROOT="/root/JLU_LEDLAB"
PIDFILE="$ROOT/run/voice.pid"
LOGFILE="$ROOT/logs/voice.log"

if [ -f "$PIDFILE" ]; then
    OLD="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
        echo "JLU_LEDLAB voice already running: PID=$OLD"
        exit 0
    fi
fi

cd "$ROOT" || exit 1
nohup ./run_voice.sh "$@" >>"$LOGFILE" 2>&1 &
NEW=$!
echo "$NEW" >"$PIDFILE"
echo "JLU_LEDLAB voice started: PID=$NEW"
echo "log: $LOGFILE"
