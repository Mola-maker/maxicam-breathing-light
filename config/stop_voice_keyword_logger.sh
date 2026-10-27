#!/bin/sh
set -eu
BASE="/home/jlu/桌面/config"
cd "$BASE"

if [ ! -f voice_keyword_logger.pid ]; then
    echo "voice_keyword_logger 未运行"
    exit 0
fi

PID=$(cat voice_keyword_logger.pid 2>/dev/null || true)
if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    # 先结束 ssh tail 子进程，避免留下孤儿连接。
    pkill -TERM -P "$PID" 2>/dev/null || true
    kill "$PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$PID" 2>/dev/null; then
        pkill -KILL -P "$PID" 2>/dev/null || true
        kill -9 "$PID" 2>/dev/null || true
    fi
    echo "voice_keyword_logger 已停止: PID=$PID"
else
    echo "PID $PID 不在运行"
fi
rm -f voice_keyword_logger.pid
