#!/bin/sh
# Record from the USB microphone and print basic level statistics.
set -e

OUT="${1:-/tmp/usbmic_test.wav}"
SECONDS="${2:-3}"
CARD="${USB_MIC_CARD:-1}"

arecord -D "plughw:${CARD},0" -f S16_LE -r 16000 -c 1 -d "$SECONDS" "$OUT"
python3 - "$OUT" <<'PY'
import array
import math
import sys
import wave

path = sys.argv[1]
with wave.open(path, "rb") as w:
    print("sample_rate", w.getframerate())
    print("channels", w.getnchannels())
    print("frames", w.getnframes())
    print("seconds", w.getnframes() / w.getframerate())
    pcm = w.readframes(w.getnframes())

samples = array.array("h", pcm)
rms = math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768 if samples else 0
peak = max((abs(x) for x in samples), default=0) / 32768
print("rms", round(rms, 6))
print("peak", round(peak, 6))
PY
