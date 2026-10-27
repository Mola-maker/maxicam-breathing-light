"""
Surplife 400 LED 窗帘灯控制器 API

基于 BLE 的 REST API。兼容 pydantic v1 (MaixCAM, 无需编译) 和 v2。

环境变量:
    SURPLIFE_HOST      监听地址, 默认 0.0.0.0
    SURPLIFE_PORT      端口, 默认 8000
    SURPLIFE_ADDRESS   启动时自动连接的 MAC 地址 (可选)
    SURPLIFE_TOKEN     设置后所有 API 需要 Header "X-Token: <token>" (可选)
    SURPLIFE_LOG       日志级别, 默认 INFO
"""

import asyncio
import base64
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import List, Optional, Tuple, Union

# MaixVision 运行时会把 main.py 复制到 /tmp/maixpy_run；
# 依赖仍安装在项目目录，因此显式加入 sys.path，保证任何启动位置都能导入。
_LIB_DIR = os.environ.get("SURPLIFE_LIB", "/root/surplife/lib")
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

_APP_DIR = "/root/surplife/app"
if os.path.isdir(_APP_DIR) and _APP_DIR not in sys.path:
    sys.path.append(_APP_DIR)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import protocol as P
from ble_client import SurplifeBLEClient

logging.basicConfig(
    level=os.environ.get("SURPLIFE_LOG", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("surplife.api")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
API_TOKEN = os.environ.get("SURPLIFE_TOKEN") or None
AUTO_ADDRESS = os.environ.get("SURPLIFE_ADDRESS") or None

ble_client = SurplifeBLEClient()

# 最近一次的模式和参数, 供 /brightness /speed 在当前模式上调整
state = {
    "mode": None,
    "color": {"hue": 0, "saturation": 100, "brightness": 100},
    "effect": {"effect_id": 0, "speed": 50, "brightness": 100},
    "animation": {"speed": 50, "brightness": 100, "once": False},
    "text": {"speed": 50, "brightness": 100, "direction": "left"},
    "music": {"effect_id": 0, "brightness": 100, "sensitivity": 100},
}


# ----------------------------------------------------------------------
# 请求模型
# ----------------------------------------------------------------------

class ConnectRequest(BaseModel):
    address: Optional[str] = Field(None, description="设备 MAC 地址 (为空则自动扫描)")


class PowerRequest(BaseModel):
    on: bool = Field(..., description="True=开, False=关")


class ColorRequest(BaseModel):
    hue: Optional[float] = Field(None, ge=0, le=360, description="色相 0-360°")
    saturation: float = Field(100, ge=0, le=100, description="饱和度 0-100 (0=白)")
    brightness: float = Field(100, ge=0, le=100, description="亮度 0-100")
    rgb: Optional[str] = Field(None, description="或直接给 #RRGGBB, 优先于 hue")


class EffectRequest(BaseModel):
    effect_id: int = Field(0, ge=0, le=0x11, description="效果 ID 0-17")
    speed: int = Field(50, ge=0, le=100)
    brightness: int = Field(100, ge=0, le=100)


class LevelRequest(BaseModel):
    value: int = Field(..., ge=0, le=100)


class MusicModeRequest(BaseModel):
    effect_id: int = Field(0, ge=0, le=0x0D, description="音乐律动效果 0-13")
    brightness: int = Field(100, ge=0, le=100)
    sensitivity: int = Field(100, ge=0, le=100, description="麦克风灵敏度")
    hues: Optional[List[int]] = Field(None, description="最多 6 个色相 (0-360)")


class PhoneMusicRequest(BaseModel):
    bands: List[int] = Field(..., description="20 列振幅 0-100")


class TextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=64)
    speed: int = Field(50, ge=0, le=100)
    brightness: int = Field(100, ge=0, le=100)
    direction: str = Field("left", description="fixed/twinkle/left/right/up/down")


class Pixel(BaseModel):
    x: Optional[int] = Field(None, ge=0, lt=P.WIDTH)
    y: Optional[int] = Field(None, ge=0, lt=P.HEIGHT)
    index: Optional[int] = Field(None, ge=0, lt=P.NUM_PIXELS, description="行优先线性索引")
    color: str = Field("#ffffff", description="#RRGGBB, #000000 为熄灭")


class PixelsRequest(BaseModel):
    pixels: List[Pixel]
    clear: bool = Field(False, description="先清屏")


class FrameRequest(BaseModel):
    frame: List[List[str]] = Field(..., description="20 行 x 20 列 #RRGGBB")


class AnimationParamsRequest(BaseModel):
    speed: int = Field(50, ge=0, le=75)
    brightness: int = Field(100, ge=0, le=100)
    once: bool = False


class ImageUploadRequest(BaseModel):
    frame_hex: Optional[str] = Field(None, description="设备格式的帧数据 (hex)")
    frame_b64: Optional[str] = Field(None, description="或 base64")
    speed: int = Field(75, ge=0, le=75)
    brightness: int = Field(100, ge=0, le=100)


class CalibrationRawRequest(BaseModel):
    channels: List[int] = Field(..., min_items=3, max_items=5, description="各引脚 0-255")


class CalibrationMapRequest(BaseModel):
    order: str = Field("RGB", description="如 RGB / GRB / BRG")
    save: bool = True


class RawRequest(BaseModel):
    hex: str = Field(..., description="0x0A 之后的 payload, 如 e20b01ff")


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------

async def send(*payloads: bytes) -> None:
    try:
        await ble_client.ensure_connected()
        await ble_client.send_many(list(payloads))
    except ConnectionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("发送失败")
        raise HTTPException(status_code=502, detail=f"BLE 写入失败: {e}")


def color_to_hsv16(color: str) -> int:
    try:
        return P.rgb_to_hsv16(*P.parse_hex_color(color))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


async def paint_groups(groups: dict, clear: bool) -> int:
    """按颜色分组, 每种颜色一条 E2 0C 命令"""
    cmds = []
    if clear:
        cmds.append(P.cmd_paint(0, b"\xff" * (P.NUM_PIXELS // 8)))
    for hsv, coords in groups.items():
        cmds.append(P.cmd_paint(hsv, P.pixel_mask(coords)))
    await send(*cmds)
    state["mode"] = "paint"
    return len(cmds)


# ----------------------------------------------------------------------
# 应用
# ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    if AUTO_ADDRESS:
        try:
            await ble_client.connect(AUTO_ADDRESS)
        except Exception as e:  # noqa: BLE001
            log.warning("自动连接 %s 失败: %s", AUTO_ADDRESS, e)
    yield
    await ble_client.disconnect()


app = FastAPI(
    title="Surplife Curtain Controller",
    description="Surplife 400 LED (20x20) 窗帘灯 BLE 控制器 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def token_auth(request: Request, call_next):
    if API_TOKEN and request.method != "OPTIONS":
        path = request.url.path
        public = path == "/" or path.startswith("/static") or path in ("/docs", "/openapi.json")
        if not public and request.headers.get("x-token") != API_TOKEN:
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
    return await call_next(request)


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/static/index.html")


# ---------------------------- 连接 ------------------------------------

@app.get("/scan")
async def scan(timeout: float = 5.0):
    try:
        return {"devices": await ble_client.scan(timeout)}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/connect")
async def connect(req: ConnectRequest):
    try:
        address = await ble_client.connect(req.address)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "connected", "address": address, "device": ble_client.status}


@app.post("/disconnect")
async def disconnect():
    await ble_client.disconnect()
    return {"status": "disconnected"}


@app.get("/status")
async def get_status(refresh: bool = False):
    if refresh and ble_client.is_connected:
        await send(P.cmd_query_status())
        await ble_client.wait_status(2.0)
    return {
        "connected": ble_client.is_connected,
        "address": ble_client.address,
        "device": ble_client.status,
        "mode": state["mode"],
        "state": state,
    }


# ---------------------------- 基本控制 --------------------------------

@app.post("/power")
async def set_power(req: PowerRequest):
    await send(P.cmd_power(req.on))
    return {"power": req.on}


@app.post("/color")
async def set_color(req: ColorRequest):
    if req.rgb:
        hsv = color_to_hsv16(req.rgb)
    else:
        hue = req.hue if req.hue is not None else state["color"]["hue"]
        state["color"] = {"hue": hue, "saturation": req.saturation, "brightness": req.brightness}
        hsv = P.hsv16(hue, req.saturation, req.brightness)
    await send(P.cmd_color(hsv))
    state["mode"] = "color"
    return {"hsv16": f"{hsv:04x}"}


@app.get("/effects")
async def list_effects():
    # 来自 ge0rg 抓包的已知名称, 其余未记录
    known = {1: "blinking colors", 5: "rainbow scrolling down", 8: "pattern moving up"}
    return {"effects": [{"id": i, "name": known.get(i, f"effect {i}")} for i in range(0x12)]}


@app.post("/effect")
async def set_effect(req: EffectRequest):
    state["effect"] = {"effect_id": req.effect_id, "speed": req.speed, "brightness": req.brightness}
    await send(P.cmd_effect(req.effect_id, req.speed, req.brightness))
    state["mode"] = "effect"
    return state["effect"]


async def _reapply() -> dict:
    """用 state 中的参数重发当前模式的命令"""
    mode = state["mode"]
    if mode == "color":
        c = state["color"]
        await send(P.cmd_color(P.hsv16(c["hue"], c["saturation"], c["brightness"])))
    elif mode == "effect":
        e = state["effect"]
        await send(P.cmd_effect(e["effect_id"], e["speed"], e["brightness"]))
    elif mode in ("animation", "paint"):
        a = state["animation"]
        await send(P.cmd_animation_params(a["speed"], a["brightness"], a["once"]))
    elif mode == "text":
        t = state["text"]
        await send(P.cmd_text_config(t["speed"], t["brightness"], t["direction"]))
    elif mode == "music":
        m = state["music"]
        await send(P.cmd_music_device(m["effect_id"], m["brightness"], m["sensitivity"],
                                      update_only=True))
    else:
        raise HTTPException(status_code=409, detail="尚未设置任何模式")
    return {"mode": mode}


@app.post("/brightness")
async def set_brightness(req: LevelRequest):
    """调整当前模式的亮度 (0-100)"""
    for key in ("color", "effect", "animation", "text", "music"):
        state[key]["brightness"] = req.value
    return await _reapply()


@app.post("/speed")
async def set_speed(req: LevelRequest):
    """调整当前模式的速度 (0-100; 动画模式自动缩放到 0-75)"""
    state["effect"]["speed"] = req.value
    state["text"]["speed"] = req.value
    state["animation"]["speed"] = round(req.value * 75 / 100)
    return await _reapply()


# ---------------------------- 音乐 ------------------------------------

@app.post("/music")
async def set_music_mode(req: MusicModeRequest):
    """设备麦克风音乐律动"""
    state["music"] = {"effect_id": req.effect_id, "brightness": req.brightness,
                      "sensitivity": req.sensitivity}
    await send(P.cmd_music_device(req.effect_id, req.brightness, req.sensitivity, req.hues))
    state["mode"] = "music"
    return state["music"]


@app.post("/phone-music")
async def set_phone_music(req: PhoneMusicRequest):
    """外部音频频谱帧 (需高频调用, 先调用 /music 切换到音乐模式)"""
    await send(P.cmd_music_bands(req.bands))
    return {"bands": min(len(req.bands), P.WIDTH)}


# ---------------------------- 文本 ------------------------------------

@app.post("/text")
async def set_text(req: TextRequest):
    if req.direction not in P.TEXT_DIRECTIONS:
        raise HTTPException(status_code=422, detail=f"direction 可选: {list(P.TEXT_DIRECTIONS)}")
    glyphs = P.render_text_glyphs(req.text)
    state["text"] = {"speed": req.speed, "brightness": req.brightness, "direction": req.direction}
    await send(
        P.cmd_text_bitmap(glyphs),
        P.cmd_text_config(req.speed, req.brightness, req.direction),
    )
    state["mode"] = "text"
    return {"text": req.text, "chars": len(glyphs)}


# ---------------------------- 像素 ------------------------------------

@app.post("/pixels")
async def set_pixels(req: PixelsRequest):
    """设置单个像素, 坐标原点在左上角"""
    groups: dict = {}
    for px in req.pixels:
        if px.index is not None:
            xy: Tuple[int, int] = (px.index % P.WIDTH, px.index // P.WIDTH)
        elif px.x is not None and px.y is not None:
            xy = (px.x, px.y)
        else:
            raise HTTPException(status_code=422, detail="像素需要 index 或 x/y")
        groups.setdefault(color_to_hsv16(px.color), []).append(xy)
    n = await paint_groups(groups, req.clear)
    return {"pixels": len(req.pixels), "commands": n}


@app.post("/frame")
async def set_frame(req: FrameRequest):
    """整幅 20x20 画面, 按颜色分组发送"""
    if len(req.frame) != P.HEIGHT or any(len(r) != P.WIDTH for r in req.frame):
        raise HTTPException(status_code=422, detail="frame 必须为 20x20")
    groups: dict = {}
    for y, row in enumerate(req.frame):
        for x, c in enumerate(row):
            groups.setdefault(color_to_hsv16(c), []).append((x, y))
    n = await paint_groups(groups, clear=False)
    return {"colors": len(groups), "commands": n}


@app.post("/clear")
async def clear():
    await send(P.cmd_paint(0, b"\xff" * (P.NUM_PIXELS // 8)))
    state["mode"] = "paint"
    return {"cleared": True}


# ---------------------------- 动画/图片 -------------------------------

@app.post("/animation")
async def set_animation_params(req: AnimationParamsRequest):
    """调整已上传动画/图片的播放速度与亮度"""
    state["animation"] = {"speed": req.speed, "brightness": req.brightness, "once": req.once}
    await send(P.cmd_animation_params(req.speed, req.brightness, req.once))
    state["mode"] = "animation"
    return state["animation"]


@app.post("/image")
async def upload_image(req: ImageUploadRequest):
    """
    上传一帧设备格式的图片数据。压缩格式未完全逆向, 只能回放抓包得到的帧,
    例如 ge0rg/bitmap.md 中的旗帜示例。
    """
    try:
        if req.frame_hex:
            frame = bytes.fromhex(req.frame_hex)
        elif req.frame_b64:
            frame = base64.b64decode(req.frame_b64)
        else:
            raise ValueError("需要 frame_hex 或 frame_b64")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await send(*P.cmd_image_upload(frame),
               P.cmd_animation_params(req.speed, req.brightness))
    state["mode"] = "animation"
    return {"bytes": len(frame)}


# ---------------------------- 校准 / 调试 -----------------------------

@app.post("/calibration/raw")
async def calibration_raw(req: CalibrationRawRequest):
    """直接驱动物理引脚, 用于判断接线顺序"""
    await send(P.cmd_calibration_raw(*req.channels))
    return {"channels": req.channels}


@app.post("/calibration/map")
async def calibration_map(req: CalibrationMapRequest):
    """设置 RGB 引脚映射, 如 GRB 表示物理第 1 脚是绿色"""
    order = req.order.upper()
    if sorted(order) != ["B", "G", "R"]:
        raise HTTPException(status_code=422, detail="order 必须是 R/G/B 的排列")
    r, g, b = (order.index(ch) for ch in "RGB")
    cmds = [P.cmd_calibration_map(r, g, b)]
    if req.save:
        cmds.append(P.cmd_calibration_save())
    await send(*cmds)
    return {"order": order, "saved": req.save}


@app.post("/raw")
async def send_raw(req: RawRequest):
    """发送原始命令 payload (调试用)"""
    try:
        payload = bytes.fromhex(req.hex.replace(" ", ""))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await send(payload)
    status = await ble_client.wait_status(1.0)
    return {"sent": payload.hex(), "status": status}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("SURPLIFE_HOST", "0.0.0.0"),
        port=int(os.environ.get("SURPLIFE_PORT", "8000")),
        log_level=os.environ.get("SURPLIFE_LOG", "info").lower(),
    )
