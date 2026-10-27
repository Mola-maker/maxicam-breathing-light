#!/bin/sh
set -eu
BASE="/home/jlu/桌面/config"
cd "$BASE"

if [ -f voice_keyword_logger.pid ]; then
    PID=$(cat voice_keyword_logger.pid 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "voice_keyword_logger 已在运行: PID=$PID"
        exit 0
    fi
fi

nohup python3 -u voice_keyword_logger.py >> voice_keyword_logger.out 2>&1 &
echo $! > voice_keyword_logger.pid
echo "voice_keyword_logger 已启动: PID=$(cat voice_keyword_logger.pid)"
echo "输出: $BASE/voice_keyword_log.txt"
echo "运行日志: $BASE/voice_keyword_logger.out"
