#!/bin/sh
# 停止 voice_pwm（包括主进程和 DSP/音频子进程），并兜底关闭 A18/A19 的 PWM。
PIDFILE=/root/surplife/pwm.pid
PIDS=""

if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        PIDS="$PID"
    fi
fi

# voice_pwm 会 fork 出多个 python3 voice_pwm.py 子进程；PID 文件只记录父进程。
# 这里扫描 /proc，把父进程和所有残留子进程一起停掉，避免只杀掉父进程后子进程继续占麦克风/PWM。
for d in /proc/[0-9]*; do
    [ -r "$d/cmdline" ] || continue
    cmd="$(tr '\0' ' ' <"$d/cmdline" 2>/dev/null)"
    set -- $cmd
    case "$1" in
        python3|/usr/bin/python3)
            case "$2" in
                voice_pwm.py|/root/surplife/app/voice_pwm.py)
                    p="${d#/proc/}"
                    case " $PIDS " in
                        *" $p "*) ;;
                        *) PIDS="$PIDS $p" ;;
                    esac
                    ;;
            esac
            ;;
    esac
done

if [ -n "$PIDS" ]; then
    echo "停止 voice_pwm PID(s):$PIDS ..."
    kill -INT $PIDS 2>/dev/null
    i=0
    while [ "$i" -lt 30 ]; do
        alive=0
        for p in $PIDS; do
            if kill -0 "$p" 2>/dev/null; then
                alive=1
            fi
        done
        if [ "$alive" -eq 0 ]; then
            break
        fi
        sleep 0.1
        i=$((i + 1))
    done
    if [ "$alive" -ne 0 ]; then
        echo "INT 未退出, 发送 TERM"
        kill -TERM $PIDS 2>/dev/null
        sleep 1
    fi
    alive=0
    for p in $PIDS; do
        if kill -0 "$p" 2>/dev/null; then
            alive=1
        fi
    done
    if [ "$alive" -ne 0 ]; then
        echo "TERM 未退出, 强制 KILL"
        kill -KILL $PIDS 2>/dev/null
        sleep 0.3
    fi
else
    echo "voice_pwm 未运行"
fi

rm -f "$PIDFILE"

for d in /sys/class/pwm/pwmchip4/pwm2 /sys/class/pwm/pwmchip4/pwm3; do
    if [ -d "$d" ]; then
        echo 0 >"$d/duty_cycle" 2>/dev/null || true
        echo 0 >"$d/enable" 2>/dev/null || true
    fi
done

echo "A18/PWM6, A19/PWM7 已关闭"
