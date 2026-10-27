"""
Surplife BLE 协议编码/解码器

参考:
- https://codeberg.org/ge0rg/surplife-curtain   (抓包日志, 16-bit HSV, 文本位图)
- https://gist.github.com/marcelrv/36f9d2c66a273289211cc5fa73b00018 (传输层源码分析, 各模式命令)

分两层:
- 传输层 (SurplifeProtocol): 8 字节头 + cmd_id(0x0A) + payload, 支持 V0 分段
- 应用层 (cmd_* 函数): 生成 0x0A 之后的命令 payload, 纯函数便于测试
"""

from __future__ import annotations

import colorsys
from datetime import datetime

# 应用层命令 ID: 普通控制命令都走 0x0A
CMD_CONTROL = 0x0A

# 设备 -> 主机通知的 cmd_id
NOTIFY_JSON = 0x0C
NOTIFY_QUERY_REPLY = 0x15   # 对 ea818a8b59 的回复
NOTIFY_STATUS = 0x16        # 状态变化

# 窗帘尺寸 (20x20 = 400 LEDs)
WIDTH = 20
HEIGHT = 20
NUM_PIXELS = WIDTH * HEIGHT

# 状态通知中 byte7 的模式码 (来自两份抓包日志)
MODE_NAMES = {
    0x62: "music",
    0x66: "color",
    0x67: "effect",
    0x72: "animation",
    0x73: "text",
    0x74: "image",
}

TEXT_DIRECTIONS = {
    "fixed": 0x00,
    "twinkle": 0x01,
    "left": 0x02,
    "right": 0x03,
    "up": 0x04,
    "down": 0x05,
}


# ======================================================================
# 传输层
# ======================================================================

class SurplifeProtocol:
    """传输层 V0 编码器/解码器 (LowerTransportLayerEncoder)"""

    MULTILINE = 0x40   # bit 6: 多段消息
    PROTECT = 0x20     # bit 5: 保护/加密
    ACK = 0x10         # bit 4: 需要确认

    FIRST_HEADER = 8
    CONT_HEADER = 5

    def __init__(self, mtu: int = 186) -> None:
        self._seq = 0
        self.set_mtu(mtu)

    def set_mtu(self, mtu: int) -> None:
        # ATT 开销 3 字节; V0 的段长度字段只有 8 bit, 因此单段最大 255
        self.max_packet = max(23, min(mtu, 258)) - 3

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def encode(self, cmd_id: int, payload: bytes = b"") -> list[bytes]:
        """
        将命令编码为一个或多个 BLE 写入块。

        单段格式 (与抓包一致):
            00 seq 80 00 [len_hi len_lo] [len+1] cmd_id payload...
        其中 len 为 payload 长度 (不含 cmd_id), 段长度含 cmd_id。
        """
        seq = self._next_seq()
        total = len(payload)
        body = bytes([cmd_id]) + payload

        if self.FIRST_HEADER - 1 + len(body) <= self.max_packet:
            header = bytes([
                0x00, seq, 0x80, 0x00,
                (total >> 8) & 0xFF, total & 0xFF,
                len(body) & 0xFF,
            ])
            return [header + body]

        # 多段: 首段 8 字节头 (line id = 0), 续段 5 字节头 (seg id, 末段 MSB=1)
        first_cap = self.max_packet - (self.FIRST_HEADER - 1)
        cont_cap = self.max_packet - self.CONT_HEADER
        first, rest = body[:first_cap], body[first_cap:]

        chunks = [bytes([
            self.MULTILINE, seq, 0x00, 0x00,
            (total >> 8) & 0xFF, total & 0xFF,
            len(first) & 0xFF,
        ]) + first]

        seg_idx = 0
        while rest:
            part, rest = rest[:cont_cap], rest[cont_cap:]
            seg_idx += 1
            seg_id = seg_idx | (0x8000 if not rest else 0)
            chunks.append(bytes([
                self.MULTILINE, seq,
                (seg_id >> 8) & 0xFF, seg_id & 0xFF,
                len(part) & 0xFF,
            ]) + part)
        return chunks

    @staticmethod
    def decode(data: bytes) -> dict | None:
        """解码单段通知 (设备回复一般 33 字节, 不分段)"""
        if len(data) < 8:
            return None
        return {
            "control": data[0],
            "seq": data[1],
            "line_id": (data[2] << 8) | data[3],
            "total_len": (data[4] << 8) | data[5],
            "chunk_len": data[6],
            "cmd_id": data[7],
            "payload": bytes(data[8:]),
        }


def parse_status(payload: bytes) -> dict | None:
    """
    解析 cmd 0x15/0x16 的二进制状态 (以 EA 81 开头, 25 字节)。

    例: ea 81 01 00 c2 06 23 67 0b 64 f0 ...
        [3-4] 型号 00C2, [5] 硬件版本, [6] 电源 23=开/24=关,
        [7] 模式码, [8] 效果 ID/子参数, [9] 速度或亮度 (随模式变化)
    """
    if len(payload) < 10 or payload[0] != 0xEA or payload[1] != 0x81:
        return None
    mode = payload[7]
    return {
        "power": payload[6] == 0x23,
        "model": f"{payload[3]:02X}{payload[4]:02X}",
        "hw_version": payload[5],
        "mode_code": mode,
        "mode": MODE_NAMES.get(mode, f"unknown_0x{mode:02x}"),
        "value1": payload[8],
        "value2": payload[9],
        "raw": payload.hex(),
    }


# ======================================================================
# 颜色: 16-bit HSV (7 bit 色相 / 4 bit 饱和度 / 5 bit 亮度)
# ======================================================================

def hsv16(hue: float, saturation: float = 100, value: float = 100) -> int:
    """
    hue: 0-360°, saturation: 0-100, value: 0-100 -> 16-bit 设备色值

    色相刻度为 3°/步 (绿 0x51ff -> 40, 蓝 0xa1ff -> 80), 共 120 级。
    """
    h = int(round((hue % 360) / 3)) % 120
    s = int(round(max(0, min(100, saturation)) * 15 / 100))
    v = int(round(max(0, min(100, value)) * 31 / 100))
    return (h << 9) | (s << 5) | v


def rgb_to_hsv16(r: int, g: int, b: int) -> int:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return hsv16(h * 360, s * 100, v * 100)


def parse_hex_color(color: str) -> tuple[int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"无效颜色: {color}")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _u16(v: int) -> bytes:
    return bytes([(v >> 8) & 0xFF, v & 0xFF])


def _pct(v: int) -> int:
    return max(0, min(100, int(v)))


# ======================================================================
# 应用层命令 (返回 0x0A 之后的 payload)
# ======================================================================

def cmd_time_sync(now: datetime | None = None) -> bytes:
    """10 [世纪][年][月][日][时][分][秒][星期] 00 0F [校验和]"""
    now = now or datetime.now()
    body = bytes([
        0x10, now.year // 100, now.year % 100, now.month, now.day,
        now.hour, now.minute, now.second, now.isoweekday(), 0x00, 0x0F,
    ])
    return body + bytes([sum(body) & 0xFF])


def cmd_query_status() -> bytes:
    """握手 / 保活 / 查询状态"""
    return bytes.fromhex("ea818a8b59")


def cmd_power(on: bool) -> bytes:
    return bytes([0x71, 0x23 if on else 0x24])


def cmd_color(hsv: int) -> bytes:
    """整幅单色"""
    return bytes([0xE2, 0x0B]) + _u16(hsv)


def cmd_effect(effect_id: int, speed: int, brightness: int) -> bytes:
    """内置效果 0x00-0x11"""
    return bytes([0xE0, 0x02, 0x00, effect_id & 0xFF, _pct(speed), _pct(brightness)])


def cmd_animation_params(speed: int, brightness: int, once: bool = False) -> bytes:
    """动画/图片播放参数: E2 09 01 [speed 0-75] [bri 0-100] [00 循环 / 02 单次]"""
    return bytes([
        0xE2, 0x09, 0x01, max(0, min(75, int(speed))), _pct(brightness),
        0x02 if once else 0x00,
    ])


def cmd_paint(hsv: int, mask: bytes) -> bytes:
    """把 mask 中为 1 的像素设成 hsv; hsv=0 即擦除"""
    if len(mask) != NUM_PIXELS // 8:
        raise ValueError("mask 必须为 50 字节 (400 bit)")
    return bytes([0xE2, 0x0C, 0x90]) + _u16(hsv) + mask


def pixel_mask(indices, order: str = "row") -> bytes:
    """
    把像素坐标集合转成 400 bit 掩码 (MSB 优先, 与 ge0rg 的 surp.py 一致)。

    indices: 可迭代的 (x, y) 或线性索引 (按 order 解释)
    order: "row" 行优先 / "col" 列优先 (marcelrv 文档称列优先, 未完全确认)
    """
    bits = bytearray(NUM_PIXELS // 8)
    for item in indices:
        if isinstance(item, int):
            if order == "col":
                x, y = divmod(item, HEIGHT)
            else:
                y, x = divmod(item, WIDTH)
        else:
            x, y = item
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            continue
        bit = (x * HEIGHT + y) if order == "col" else (y * WIDTH + x)
        bits[bit // 8] |= 0x80 >> (bit % 8)
    return bytes(bits)


def cmd_music_device(
    effect_id: int,
    brightness: int = 100,
    sensitivity: int = 100,
    colors_hue: list[int] | None = None,
    update_only: bool = False,
) -> bytes:
    """
    设备麦克风音乐模式 E1 05 (与 gist 抓包逐字节一致, 共 54 字节):
        E1 05 [flag] [bri] [effect] 00 00 [sens] + 17x00
        + A1 00 00 00 [N] + N x (A1 [hue/2] 64 64)
    """
    hues = colors_hue if colors_hue is not None else [0, 300, 240, 180, 120, 60]
    hues = hues[:6]
    out = bytearray([
        0xE1, 0x05, 0x01 if update_only else 0x00, _pct(brightness),
        effect_id & 0xFF, 0x00, 0x00, _pct(sensitivity),
    ])
    out += bytes(17)
    out += bytes([0xA1, 0x00, 0x00, 0x00, len(hues)])
    for h in hues:
        out += bytes([0xA1, (int(h) % 360) // 2, 0x64, 0x64])
    return bytes(out)


def cmd_music_bands(bands: list[int]) -> bytes:
    """手机音乐可视化帧: E2 0A + 20 列振幅 (0-100)"""
    vals = [_pct(b) for b in bands[:WIDTH]]
    vals += [0] * (WIDTH - len(vals))
    return bytes([0xE2, 0x0A] + vals)


# 文本样式 (E2 05 字节 2-12), 取自 ge0rg 抓包中设置成功的报文
DEFAULT_TEXT_STYLE = bytes.fromhex("0201000064640000000000")


def cmd_text_bitmap(glyph_columns: list[list[int]]) -> bytes:
    """
    文本位图 E2 04 00 00 + 每字符 15 字节: 0C + 7 列 x u16 (MSB 为最上一行)
    glyph_columns: 每个字符 7 个 16-bit 列值
    """
    out = bytearray([0xE2, 0x04, 0x00, 0x00])
    for cols in glyph_columns:
        cols = (list(cols) + [0] * 7)[:7]
        out.append(0x0C)
        for c in cols:
            out += _u16(c)
    return bytes(out)


def cmd_text_config(
    speed: int, brightness: int, direction: str = "left", style: bytes | None = None
) -> bytes:
    """文本显示参数 E2 05 [11 字节样式] [speed] [bri] [direction]"""
    style = DEFAULT_TEXT_STYLE if style is None else style
    if len(style) != 11:
        raise ValueError("style 必须为 11 字节")
    if direction not in TEXT_DIRECTIONS:
        raise ValueError(f"direction 可选: {', '.join(TEXT_DIRECTIONS)}")
    return bytes([0xE2, 0x05]) + style + bytes([
        _pct(speed), _pct(brightness), TEXT_DIRECTIONS[direction],
    ])


def render_text_glyphs(text: str, font_path: str | None = None) -> list[list[int]]:
    """用 Pillow 把文本渲染成每字符 7x16 的列位图 (MaixCAM 自带 Pillow)"""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(font_path, 10) if font_path else ImageFont.load_default()
    glyphs = []
    for ch in text:
        img = Image.new("1", (7, 16), 0)
        ImageDraw.Draw(img).text((0, 0), ch, fill=1, font=font)
        px = img.load()
        cols = []
        for x in range(7):
            v = 0
            for y in range(16):
                if px[x, y]:
                    v |= 0x8000 >> y
            cols.append(v)
        glyphs.append(cols)
    return glyphs


def cmd_image_upload(frame: bytes) -> list[bytes]:
    """
    上传一帧已编码的图片 (压缩格式尚未完全解析, 需提供设备格式的原始数据)。
    序列取自 ge0rg 的 surp.py: EA01 元数据 -> EA02 帧长 -> EA03 数据 -> EA04 结束
    """
    return [
        bytes.fromhex(
            "EA010100000320000000000000000000000000000000000001000000000000000000000000000000"
        ),
        bytes([0xEA, 0x02, 0x00, 0x00]) + len(frame).to_bytes(4, "big"),
        bytes([0xEA, 0x03, 0x00, 0x01]) + frame,
        bytes([0xEA, 0x04, 0x00]),
    ]


# 颜色校准 (引脚映射)
def cmd_calibration_raw(ch1: int, ch2: int, ch3: int, ww: int = 0, cw: int = 0) -> bytes:
    return bytes([0xE0, 0x15, 0x00, 0x00] + [v & 0xFF for v in (ch1, ch2, ch3, ww, cw)])


def cmd_calibration_map(r: int, g: int, b: int, ww: int = 3, cw: int = 4) -> bytes:
    return bytes([0xE0, 0x13, r, g, b, ww, cw])


def cmd_calibration_save() -> bytes:
    return bytes([0xE0, 0x0E, 0x01])
