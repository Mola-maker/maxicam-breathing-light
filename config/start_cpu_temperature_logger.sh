#!/bin/sh
set -eu
BASE="/home/jlu/桌面/config"
cd "$BASE"

if [ -f cpu_temperature_logger.pid ]; then
    PID=$(cat cpu_temperature_logger.pid 2>/dev/null || true)
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "cpu_temperature_logger 已在运行: PID=$PID"
        exit 0
    fi
fi

nohup python3 -u cpu_temperature_logger.py >> cpu_temperature_logger.out 2>&1 &
echo $! > cpu_temperature_logger.pid
echo "cpu_temperature_logger 已启动: PID=$(cat cpu_temperature_logger.pid)"
echo "输出目录: $BASE/CPU-temperature"
echo "运行日志: $BASE/cpu_temperature_logger.out"
