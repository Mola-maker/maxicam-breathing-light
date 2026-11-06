#!/bin/sh
# 查看 voice_pwm 进程、日志和 PWM 输出状态。
PIDFILE=/root/surplife/pwm.pid
LOGFILE=/root/surplife/pwm.log

echo "== 进程 =="
if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "PID=$PID (运行中)"
    else
        echo "PID 文件存在但进程未运行: $PID"
    fi
else
    echo "没有 PID 文件"
fi
ps -o pid,ppid,rss,stat,args 2>/dev/null | grep -E "voice_pwm|python3" | grep -v grep || true

echo ""
echo "== PWM (1 kHz, period=1000000 ns) =="
for d in /sys/class/pwm/pwmchip4/pwm2 /sys/class/pwm/pwmchip4/pwm3; do
    if [ -d "$d" ]; then
        PERIOD="$(cat "$d/period" 2>/dev/null)"
        DUTY="$(cat "$d/duty_cycle" 2>/dev/null)"
        ENABLE="$(cat "$d/enable" 2>/dev/null)"
        echo "$d period=$PERIOD duty=$DUTY enable=$ENABLE"
    else
        echo "$d 未导出"
    fi
done

echo ""
echo "== 最近日志 =="
tail -20 "$LOGFILE" 2>/dev/null || echo "暂无日志"
