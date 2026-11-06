#!/usr/bin/env python3
"""Probe Maix-Speech KWS keyword probabilities for one WAV file."""
import sys, time
from maix import nn, err

def main():
    if len(sys.argv) < 3:
        print("usage: probe_kws.py model.wav kw1 [kw2 ...]")
        return 2
    model, wav = sys.argv[1], sys.argv[2]
    kws = sys.argv[3:]
    speech = nn.Speech(model)
    ret = speech.init(nn.SpeechDevice.DEVICE_WAV, wav)
    if ret != err.Err.ERR_NONE:
        print("init error", ret)
        return 1
    maxima = [0.0] * len(kws)
    counts = [0] * len(kws)
    def cb(data, length):
        for i in range(min(length, len(kws))):
            p = float(data[i])
            if p > maxima[i]: maxima[i] = p
            counts[i] += 1
    ret = speech.kws(kws, [0.0] * len(kws), cb, True)
    print("kws ret", ret, "keywords", kws)
    if ret != err.Err.ERR_NONE:
        return 1
    frames = 0
    while True:
        n = speech.run(1)
        if n < 1:
            break
        frames += n
        if frames > 20000:
            break
    print("frames", frames, "callbacks", counts)
    for kw, p in zip(kws, maxima):
        print(f"{kw}\t{p:.6f}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
