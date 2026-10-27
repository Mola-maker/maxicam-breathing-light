"""
语音关键词控制: 说 "长春" 让窗帘灯变色, 并按说话音量打分

规则: "长春" 关键词概率超过阈值才算有效 (门槛), 有效后按这句话的音量打分 (0-100),
音量越大分数越高。分数、关键词概率和实时音量都显示在 MaixCAM 屏幕上。

作为独立进程运行, 通过本机 HTTP API (main.py) 控制灯光, 不直接占用 BLE 连接。

音量来源 (kws 后端):
    nn.Speech 独占麦克风, 无法再开一路录音。因此让它从 ALSA 设备 surplife_mic 读音频,
    该设备 (asoundrc.surplife, 装到 /root/.asoundrc) 用 file 插件把同一份音频复制到
    命名管道 /root/surplife/run/surplife_mic.pcm, 由独立子进程读取并计算音量。
    (同进程线程读管道会被 speech.run() 阻塞, 所以必须是子进程。)
    找不到 surplife_mic 时退回默认麦克风, 只显示关键词概率, 不打音量分。

后端:
    kws         MaixCAM / MaixCAM Pro (SG2002), nn.Speech 关键词识别 (默认)
    sensevoice  MaixCAM2, SenseVoice 流式识别, 在识别文本里匹配 "长春" (未真机验证)

环境变量:
    SURPLIFE_API        API 地址, 默认 http://127.0.0.1:8000
    SURPLIFE_TOKEN      API 令牌 (与 main.py 相同, 可选)
    VOICE_BACKEND       kws / sensevoice, 默认 kws
    VOICE_THRESHOLD     关键词门槛 0-1, 默认 0.5
    VOICE_COOLDOWN      两次触发的最小间隔 (秒), 默认 2
    VOICE_DB_MIN        音量 0 分对应的 dBFS, 默认 -50 (约为环境底噪)
    VOICE_DB_MAX        音量 100 分对应的 dBFS, 默认 -10
    VOICE_AM_MODEL      kws 声学模型, 默认 /root/models/am_3332_192_int8.mud
    VOICE_SV_MODEL      SenseVoice 模型, 默认 /root/models/sensevoice-maixcam2/model.mud
    VOICE_DISPLAY       1=屏幕显示 (默认), 0=关闭
"""

import array
import collections
import json
import logging
import math
import multiprocessing as mp
import os
import queue
import threading
import time
import urllib.request

log = logging.getLogger("surplife.voice")

API = os.environ.get("SURPLIFE_API", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("SURPLIFE_TOKEN") or None

# 关键词: kws 用拼音 (带声调, 空格分隔), sensevoice 用汉字
KEYWORD_PINYIN = "chang2 chun1"
KEYWORD_TEXT = "长春"

# asoundrc.surplife 中定义的 ALSA 设备和它复制音频的管道
TAP_DEVICE = "surplife_mic"
TAP_FIFO = "/root/surplife/run/surplife_mic.pcm"

# 打分取触发前这段时间内的最大音量, 覆盖整句 "长春"
SCORE_WINDOW = 1.5

# 每次触发依次切换的颜色 (色相 0-360)
HUE_CYCLE = [0, 30, 60, 120, 180, 240, 280, 320]


# ======================================================================
# 打分 (纯逻辑, 便于测试)
# ======================================================================

class KeywordTrigger:
    """
    把逐帧概率转成一次性触发事件。

    kws 回调每帧都会给出概率, 一句 "长春" 会连续多帧超过阈值,
    因此要求概率先回落到阈值以下 (重新武装) 且超过冷却时间才再次触发。
    """

    def __init__(self, threshold: float = 0.5, cooldown: float = 2.0, clock=time.monotonic):
        self.threshold = threshold
        self.cooldown = cooldown
        self._clock = clock
        self._armed = True
        self._last = float("-inf")

    def feed(self, prob: float) -> bool:
        if prob < self.threshold:
            self._armed = True
            return False
        now = self._clock()
        if self._armed and now - self._last >= self.cooldown:
            self._armed = False
            self._last = now
            return True
        return False

    def hit(self) -> bool:
        """文本匹配类后端: 只按冷却时间去重"""
        now = self._clock()
        if now - self._last >= self.cooldown:
            self._last = now
            return True
        return False


class VolumeMeter:
    """16-bit 单声道 PCM 的音量 (dBFS) 和最近 window 秒内的峰值"""

    SILENCE_DB = -96.0

    def __init__(self, window: float = SCORE_WINDOW, clock=time.monotonic):
        self.window = window
        self.db = self.SILENCE_DB
        self.peak_db = self.SILENCE_DB
        self._clock = clock
        self._hist: "collections.deque[tuple[float, float]]" = collections.deque()
        self._rest = b""

    def feed(self, pcm: bytes) -> float:
        data = self._rest + pcm
        cut = len(data) // 2 * 2
        self._rest = data[cut:]
        samples = array.array("h", data[:cut])
        if not samples:
            return self.db
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        self.db = 20 * math.log10(rms / 32768) if rms >= 1 else self.SILENCE_DB

        now = self._clock()
        self._hist.append((now, self.db))
        while self._hist and now - self._hist[0][0] > self.window:
            self._hist.popleft()
        self.peak_db = max(d for _, d in self._hist)
        return self.db


def volume_score(db: float, db_min: float = -50.0, db_max: float = -10.0) -> float:
    """dBFS 线性映射到 0-100, 音量越大分数越高"""
    if db_max <= db_min:
        raise ValueError("db_max 必须大于 db_min")
    return max(0.0, min(100.0, (db - db_min) * 100.0 / (db_max - db_min)))


class ScoreState:
    """屏幕显示用的状态 (与显示硬件无关)"""

    def __init__(self, history: int = 120, clock=time.monotonic):
        self.keyword = 0.0          # 关键词概率 0-100 (门槛)
        self.volume = 0.0           # 实时音量分 0-100
        self.score: "float | None" = None   # 最近一次有效得分
        self.best = 0.0
        self.hits = 0
        self.last_hit_ts: "float | None" = None
        self.history = [0.0] * history      # 音量分曲线
        self._clock = clock

    def update(self, keyword_prob: float, volume: float) -> None:
        self.keyword = max(0.0, min(1.0, keyword_prob)) * 100
        self.volume = max(0.0, min(100.0, volume))
        self.history = self.history[1:] + [self.volume]

    def record_hit(self, score: float) -> None:
        self.score = score
        self.best = max(self.best, score)
        self.hits += 1
        self.last_hit_ts = self._clock()


def score_color(score: float, threshold: float) -> tuple:
    """低于一半阈值灰 -> 接近阈值黄 -> 超过阈值绿"""
    if score >= threshold:
        return 40, 220, 90
    if score >= threshold * 0.5:
        return 240, 190, 40
    return 120, 120, 130


def volume_color(score: float) -> tuple:
    """音量分: 蓝 (小声) -> 绿 -> 红 (大声)"""
    if score >= 75:
        return 240, 80, 80
    if score >= 40:
        return 40, 220, 90
    return 90, 170, 255


def hue_to_rgb(hue: float) -> tuple:
    import colorsys
    r, g, b = colorsys.hsv_to_rgb((hue % 360) / 360, 1, 1)
    return int(r * 255), int(g * 255), int(b * 255)


# ======================================================================
# 音量子进程
# ======================================================================

def _tap_reader(fifo: str, db_now, db_peak) -> None:
    """子进程: 读管道里的 PCM 副本, 把实时音量和窗口峰值写到共享内存"""
    meter = VolumeMeter()
    while True:
        with open(fifo, "rb", buffering=0) as f:   # 阻塞到 ALSA 打开写端
            while True:
                chunk = f.read(1024)
                if not chunk:
                    break                           # 写端关闭, 重新等待
                meter.feed(chunk)
                db_now.value = meter.db
                db_peak.value = meter.peak_db


class MicTap:
    """管理音量子进程; 必须在 nn.Speech 打开 surplife_mic 之前启动"""

    def __init__(self, fifo: str = TAP_FIFO):
        self.fifo = fifo
        ctx = mp.get_context("fork")
        self.db_now = ctx.Value("d", VolumeMeter.SILENCE_DB, lock=False)
        self.db_peak = ctx.Value("d", VolumeMeter.SILENCE_DB, lock=False)
        parent = os.path.dirname(fifo)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(fifo):
            os.remove(fifo)
        os.mkfifo(fifo, 0o600)
        self.proc = ctx.Process(target=_tap_reader, args=(fifo, self.db_now, self.db_peak),
                                daemon=True)
        self.proc.start()

    def close(self) -> None:
        if self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(1)
        if os.path.exists(self.fifo):
            os.remove(self.fifo)


# ======================================================================
# 灯光
# ======================================================================

class LightWorker(threading.Thread):
    """
    后台发 HTTP 请求, 避免阻塞音频识别循环
    (kws 回调运行在 speech.run() 内部, 回调里做网络请求会丢帧)。
    """

    def __init__(self):
        super().__init__(daemon=True)
        self._q: "queue.Queue[None]" = queue.Queue(maxsize=4)
        self._idx = 0
        self.current_hue: "int | None" = None

    def trigger(self) -> None:
        try:
            self._q.put_nowait(None)
        except queue.Full:
            log.info("灯光请求积压, 丢弃本次触发")

    def run(self) -> None:
        while True:
            self._q.get()
            hue = HUE_CYCLE[self._idx % len(HUE_CYCLE)]
            self._idx += 1
            try:
                post("/color", {"hue": hue, "saturation": 100, "brightness": 100})
                self.current_hue = hue
                log.info("已切换颜色: hue=%d", hue)
            except Exception as e:  # noqa: BLE001 - 失败不影响继续监听
                log.warning("切换颜色失败: %s", e)


def post(path: str, body: dict, timeout: float = 15.0) -> dict:
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Token"] = TOKEN
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


# ======================================================================
# 屏幕
# ======================================================================

class ScoreScreen:
    """MaixCAM 屏幕: 最近得分 + 关键词门槛条 + 实时音量条 + 音量曲线"""

    FONT = "/maixapp/share/font/SourceHanSansCN-Regular.otf"

    def __init__(self, threshold: float, has_volume: bool, fps: float = 12):
        from maix import display, image

        self._image = image
        self.disp = display.Display()
        self.w, self.h = self.disp.width(), self.disp.height()
        self.threshold = threshold * 100
        self.has_volume = has_volume
        self.state = ScoreState()
        self._interval = 1.0 / fps
        self._last_render = 0.0
        self._has_font = False
        try:
            image.load_font("cn20", self.FONT, size=20)
            image.load_font("cn64", self.FONT, size=64)
            self._has_font = True
        except Exception as e:  # noqa: BLE001 - 没有字体时退回默认字体
            log.warning("加载中文字体失败: %s", e)

    def _c(self, rgb):
        return self._image.Color.from_rgb(*rgb)

    def _text(self, x, y, text, rgb, big=False):
        if self._has_font:
            self._image.set_default_font("cn64" if big else "cn20")
            self.img.draw_string(x, y, text, self._c(rgb))
        else:
            self.img.draw_string(x, y, text, self._c(rgb), scale=4 if big else 1.3)

    def _bar(self, y, label, value, rgb, marker=None, marker_rgb=(233, 69, 96)):
        bx, bw, bh = 96, self.w - 108, 22
        self._text(12, y, label, (200, 200, 210))
        self.img.draw_rect(bx, y, bw, bh, self._c((50, 54, 70)), thickness=-1)
        self.img.draw_rect(bx, y, int(bw * value / 100), bh, self._c(rgb), thickness=-1)
        if marker is not None:
            mx = bx + int(bw * marker / 100)
            self.img.draw_line(mx, y - 4, mx, y + bh + 4, self._c(marker_rgb), 2)

    def render(self, light_hue=None) -> None:
        now = time.monotonic()
        if now - self._last_render < self._interval:
            return
        self._last_render = now

        s = self.state
        w, h = self.w, self.h
        self.img = img = self._image.Image(w, h)
        img.draw_rect(0, 0, w, h, self._c((12, 14, 24)), thickness=-1)

        # 标题 + 最近得分
        self._text(12, 6, f"说 \"{KEYWORD_TEXT}\", 越大声分数越高", (230, 230, 240))
        if s.score is None:
            self._text(12, 34, "--", (120, 120, 130), big=True)
        else:
            self._text(12, 34, f"{s.score:3.0f}", volume_color(s.score), big=True)
        self._text(w - 170, 44, f"最高 {s.best:3.0f}", (200, 200, 210))
        self._text(w - 170, 74, f"次数 {s.hits}", (200, 200, 210))

        # 关键词门槛 (红线 = 阈值), 实时音量 (白线 = 最近一次得分)
        self._bar(118, "关键词", s.keyword, score_color(s.keyword, self.threshold),
                  marker=self.threshold)
        if self.has_volume:
            self._bar(152, "音量", s.volume, volume_color(s.volume),
                      marker=s.score, marker_rgb=(255, 255, 255))
        else:
            self._text(12, 152, "音量: 未启用 (缺少 /root/.asoundrc)", (233, 69, 96))

        # 音量曲线
        gx, gy, gw = 12, 188, w - 24
        gh = h - gy - 44
        if self.has_volume and gh > 20:
            img.draw_rect(gx, gy, gw, gh, self._c((30, 34, 48)), thickness=-1)
            n = len(s.history)
            prev = None
            for i, v in enumerate(s.history):
                pt = (gx + i * (gw - 1) // (n - 1), gy + gh - 1 - int((gh - 1) * v / 100))
                if prev:
                    img.draw_line(prev[0], prev[1], pt[0], pt[1], self._c((90, 170, 255)), 2)
                prev = pt

        # 底部提示 + 当前灯光颜色
        if s.last_hit_ts and now - s.last_hit_ts < 2.0:
            msg = f"{KEYWORD_TEXT}! 得分 {s.score:.0f}, 变色" if self.has_volume else f"{KEYWORD_TEXT}! 变色"
            self._text(12, h - 34, msg, (40, 220, 90))
        else:
            self._text(12, h - 34, f"关键词门槛 {self.threshold:.0f}", (150, 150, 165))
        if light_hue is not None:
            img.draw_rect(w - 52, h - 40, 40, 32, self._c(hue_to_rgb(light_hue)), thickness=-1)

        self.disp.show(img)


# ======================================================================
# 后端
# ======================================================================

def run_kws(worker: LightWorker, trigger: KeywordTrigger, db_range: tuple) -> None:
    """MaixCAM / MaixCAM Pro: Maix-Speech 关键词识别 + 管道音量打分"""
    # 先 fork 音量子进程, 再导入 maix (避免把多媒体库状态带进子进程)
    tap = MicTap()

    from maix import app, err, nn

    model = os.environ.get("VOICE_AM_MODEL", "/root/models/am_3332_192_int8.mud")
    speech = nn.Speech(model)
    if speech.init(nn.SpeechDevice.DEVICE_MIC, TAP_DEVICE) == err.Err.ERR_NONE:
        log.info("麦克风: %s (带音量检测)", TAP_DEVICE)
    else:
        log.warning("打开 %s 失败, 改用默认麦克风, 不打音量分", TAP_DEVICE)
        tap.close()
        tap = None
        speech.init(nn.SpeechDevice.DEVICE_MIC)

    screen = (ScoreScreen(trigger.threshold, tap is not None)
              if os.environ.get("VOICE_DISPLAY", "1") != "0" else None)

    def callback(data: list, length: int):
        if length < 1:
            return
        prob = data[0]
        vol = volume_score(tap.db_now.value, *db_range) if tap else 0.0
        if screen:
            screen.state.update(prob, vol)
        if trigger.feed(prob):
            if tap:
                score = volume_score(tap.db_peak.value, *db_range)
                log.info("检测到 '%s' (p=%.3f), 音量 %.1f dBFS, 得分 %.0f",
                         KEYWORD_TEXT, prob, tap.db_peak.value, score)
            else:
                score = 0.0
                log.info("检测到 '%s' (p=%.3f)", KEYWORD_TEXT, prob)
            if screen:
                screen.state.record_hit(score)
            worker.trigger()

    # 门限设低, 由 KeywordTrigger 自行判定; True = 自动合并不同声调的近音
    speech.kws([KEYWORD_PINYIN], [0.1], callback, True)
    log.info("kws 监听中, 关键词: %s (%s), 门槛 %.2f, 音量范围 %s dBFS",
             KEYWORD_TEXT, KEYWORD_PINYIN, trigger.threshold, db_range)

    try:
        while not app.need_exit():
            if speech.run(1) < 1:
                log.warning("音频输入结束")
                break
            if screen:
                screen.render(worker.current_hue)
    finally:
        if tap:
            tap.close()


def run_sensevoice(worker: LightWorker, trigger: KeywordTrigger, db_range: tuple) -> None:
    """
    MaixCAM2: SenseVoice 流式识别, 在文本中匹配关键词, 用录到的 PCM 直接算音量。
    未在真机验证 (当前设备为 MaixCAM Pro, 不支持 SenseVoice);
    audio.Recorder / refer_stream(pcm) 的用法按官方示例推断。
    """
    from maix import app, audio, sensevoice

    model = os.environ.get("VOICE_SV_MODEL", "/root/models/sensevoice-maixcam2/model.mud")
    client = sensevoice.Sensevoice(model=model, stream=True)
    client.start()
    client.is_ready(block=True)

    recorder = audio.Recorder(sample_rate=16000, channel=1)
    meter = VolumeMeter()
    log.info("sensevoice 监听中, 关键词: %s", KEYWORD_TEXT)

    tail = ""  # 保留上一段末尾, 防止关键词被切在两段之间
    while not app.need_exit():
        pcm = recorder.record(500)  # 每次 0.5 秒
        if not pcm:
            continue
        meter.feed(bytes(pcm))
        for text in client.refer_stream(pcm):
            window = tail + (text or "")
            if KEYWORD_TEXT in window and trigger.hit():
                log.info("识别到: %s, 得分 %.0f", text, volume_score(meter.peak_db, *db_range))
                worker.trigger()
                window = ""
            tail = window[-len(KEYWORD_TEXT):]


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("SURPLIFE_LOG", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    trigger = KeywordTrigger(
        threshold=float(os.environ.get("VOICE_THRESHOLD", "0.5")),
        cooldown=float(os.environ.get("VOICE_COOLDOWN", "2")),
    )
    db_range = (float(os.environ.get("VOICE_DB_MIN", "-50")),
                float(os.environ.get("VOICE_DB_MAX", "-10")))
    volume_score(-30, *db_range)  # 参数不合法时尽早报错

    worker = LightWorker()
    worker.start()

    backend = os.environ.get("VOICE_BACKEND", "kws").lower()
    if backend == "sensevoice":
        run_sensevoice(worker, trigger, db_range)
    else:
        run_kws(worker, trigger, db_range)


if __name__ == "__main__":
    main()
