#!/bin/sh
# Temporary "长春" voice -> local A30/PWM6 lamp business.
#
# Ensures the USB Audio card is available (switching the USB-C port to host
# mode if needed), then starts the voice app with the external microphone and
# the local PWM performance output.  The SenseVoice model remains external in
# /root/models/sensevoice-maixcam2/.
set -u

ROOT=/root/JLU_LEDLAB
cd "$ROOT" || exit 1

if ! arecord -l 2>/dev/null | grep -qi 'USB Audio'; then
    if [ -x "$ROOT/usb_audio/enable_usb_mic.sh" ]; then
        "$ROOT/usb_audio/enable_usb_mic.sh" || exit 1
    else
        echo "USB Audio is not available and enable_usb_mic.sh is missing" >&2
        exit 1
    fi
fi

exec "$ROOT/start.sh" \
    --usb-mic \
    --local-pwm \
    --pwm-pin A30 \
    --pwm-id 6 \
    --pwm-freq 2000 \
    "$@"
