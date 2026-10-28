#!/usr/bin/env python3
import os
import time
from maix import app, display, image, touchscreen

W, H = 640, 480
image.load_font("ui10", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 10)
image.load_font("ui12", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 12)
image.load_font("ui14", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 14)
image.load_font("ui16", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 16)
image.load_font("ui20", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 20)
image.load_font("ui28", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 28)
image.load_font("ui44", "/maixapp/share/font/SourceHanSansCN-Regular.otf", 44)
image.load_font("mono12", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf", 12)
image.load_font("mono16", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf", 16)

img = image.Image(W, H, image.Format.FMT_RGB888)
img.draw_rect(0, 0, W, H, image.Color.from_rgb(10, 11, 13), thickness=-1)
img.draw_rect(24, 24, 592, 432, image.Color.from_rgb(19, 21, 25), thickness=1)
img.draw_rect(24, 24, 592, 48, image.Color.from_rgb(26, 29, 35), thickness=-1)
img.draw_string(40, 38, "LUMEN/1k", image.Color.from_rgb(244, 241, 234), font="ui16")
img.draw_string(160, 40, "长春 · 灯效测试台", image.Color.from_rgb(255, 180, 94), font="ui16")
img.draw_string(42, 96, "待机呼吸", image.Color.from_rgb(167, 173, 184), font="ui14")
img.draw_string(42, 126, "STANDBY BREATH", image.Color.from_rgb(110, 116, 128), font="mono12")
img.draw_string(42, 180, "35", image.Color.from_rgb(255, 180, 94), font="ui44")
img.draw_string(96, 204, "%", image.Color.from_rgb(255, 180, 94), font="ui20")
img.draw_string(42, 256, "按住说「长春」", image.Color.from_rgb(244, 241, 234), font="ui20")
img.draw_string(42, 292, "chang2 chun1", image.Color.from_rgb(95, 214, 229), font="mono16")
img.draw_string(42, 330, "只接受完整短语，不提供 chun 单独触发。", image.Color.from_rgb(167, 173, 184), font="ui14")
img.draw_string(42, 390, "LIGHT_THRESHOLD 35%", image.Color.from_rgb(167, 173, 184), font="mono12")
img.draw_string(40, 438, "字体测试: 你好，世界。 0123456789", image.Color.from_rgb(244, 241, 234), font="ui14")
os.makedirs("/root/surplife/artifacts", exist_ok=True)
img.save("/root/surplife/artifacts/ui-test.png")
print("saved", image.fonts())

disp = display.Display()
ts = touchscreen.TouchScreen()
disp.show(img)
start = time.time()
while time.time() - start < 8:
    x, y, pressed = ts.read()
    if pressed:
        print("TOUCH", x, y, pressed, flush=True)
        time.sleep(0.1)
    time.sleep(0.02)
print("done")
