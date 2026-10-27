import sys
sys.path.insert(0, "/root/surplife/lib")
from maix import nn, app
print("loading 7332", flush=True)
speech = nn.Speech("/root/models/am_7332_192_int8.mud")
speech.init(nn.SpeechDevice.DEVICE_WAV, "/root/surplife/run/changchun_baidu.wav")
def cb(data, n):
    print("KWS", [round(float(x), 3) for x in data[:n]], flush=True)
speech.kws(["chang2 chun1"], [0.01], cb, True)
print("running", flush=True)
while not app.need_exit():
    frames = speech.run(1)
    print("frames", frames, flush=True)
    if frames < 1:
        break
print("done", flush=True)
