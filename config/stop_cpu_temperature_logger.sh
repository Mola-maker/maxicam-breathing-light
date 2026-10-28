#!/bin/sh
set -eu
BASE="/home/jlu/桌面/config"
cd "$BASE"

if [ ! -f cpu_temperature_logger.pid ]; then
    echo "cpu_temperature_logger 未运行"
    exit 0
fi

PID=$(cat cpu_temperature_logger.pid 2>/dev/null || true)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    # 先结束 ssh 子进程，再通知 Python 主进程退出。
    pkill -TERM -P "$PID" 2>/dev/null || true
    kill "$PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
        pkill -KILL -P "$PID" 2>/dev/null || true
        kill -9 "$PID" 2>/dev/null || true
    fi
    echo "cpu_temperature_logger 已停止: PID=$PID"
else
    echo "PID $PID 不在运行"
fi
rm -f cpu_temperature_logger.pid
