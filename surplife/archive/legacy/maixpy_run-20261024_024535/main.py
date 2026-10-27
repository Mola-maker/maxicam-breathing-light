"""
Surplife 400 LED 窗帘灯控制器 API

基于 BLE 的 REST API, 用于控制 Surplife 智能 LED 窗帘灯。
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ble_client import SurplifeBLEClient


# ----------------------------------------------------------------------
# 全局状态
# ----------------------------------------------------------------------

ble_client = SurplifeBLEClient()


# ----------------------------------------------------------------------
# 请求/响应模型
# ----------------------------------------------------------------------

class ConnectRequest(BaseModel):
    address: str | None = Field(None, description="设备 MAC 地址 (为空则自动扫描)")


class PowerRequest(BaseModel):
    on: bool = Field(..., description="True=开, False=关")


class ColorRequest(BaseModel):
    hue: int = Field(0, ge=0, le=255, description="色相 0-255 (对应 0-360°)")
    brightness: int = Field(255, ge=0, le=255, description="亮度 0-255 (0-100%)")


class EffectRequest(BaseModel):
    effect_id: int = Field(0, ge=0, le=17, description="效果 ID (0-17)")
    speed: int = Field(50, ge=0, le=100, description="速度 0-100")
    brightness: int = Field(50, ge=0, le=100, description="亮度 0-100")


class BrightnessRequest(BaseModel):
    brightness: int = Field(50, ge=0, le=100, description="亮度 0-100")


class SpeedRequest(BaseModel):
    speed: int = Field(50, ge=0, le=100, description="速度 0-100")


class MusicModeRequest(BaseModel):
    active: bool = Field(True, description="是否激活")
    brightness: int = Field(100, ge=0, le=100, description="亮度 0-100")
    effect_id: int = Field(0, ge=0, le=17, description="效果 ID")
    sensitivity: int = Field(100, ge=0, le=100, description="灵敏度 0-100")


class PhoneMusicRequest(BaseModel):
    bands: list[int] = Field(
        ..., description="17 个频段的振幅值 (0-100)"
    )


class TextRequest(BaseModel):
    text: str = Field(..., max_length=100, description="要显示的文本")
    speed: int = Field(50, ge=0, le=100, description="滚动速度 0-100")
    brightness: int = Field(100, ge=0, le=100, description="亮度 0-100")


class PixelsRequest(BaseModel):
    pixels: list[dict[str, Any]] = Field(
        ..., description="像素列表, 每项包含 index 和 color (16-bit HSV)"
    )


class AnimationRequest(BaseModel):
    frames: list[str] = Field(
        ..., description="base64 编码的帧数据列表"
    )
    frame_delay: int = Field(100, ge=10, le=1000, description="帧间隔 (ms)")


# ----------------------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------------------

def _check_connection() -> None:
    if not ble_client.is_connected:
        raise HTTPException(status_code=400, detail="未连接到设备")


# ----------------------------------------------------------------------
# FastAPI 应用
# ----------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await ble_client.disconnect()


app = FastAPI(
    title="Surplife Curtain Controller",
    description="Surplife 400 LED 窗帘灯 BLE 控制器 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ----------------------------------------------------------------------
# 连接管理
# ----------------------------------------------------------------------

@app.post("/connect")
async def connect(req: ConnectRequest):
    """连接到 Surplife 窗帘灯"""
    try:
        await ble_client.connect(req.address)
        return {
            "status": "connected",
            "address": ble_client.client.address,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/disconnect")
async def disconnect():
    """断开连接"""
    await ble_client.disconnect()
    return {"status": "disconnected"}


@app.get("/scan")
async def scan():
    """扫描附近的 Surplife 设备"""
    try:
        devices = await ble_client.scan()
        return {"devices": devices}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def get_status():
    """获取设备状态"""
    _check_connection()
    return ble_client.status


# ----------------------------------------------------------------------
# 电源控制
# ----------------------------------------------------------------------

@app.post("/power")
async def set_power(req: PowerRequest):
    """电源开关"""
    _check_connection()
    payload = bytes([0x71, 0x23 if req.on else 0x24])
    await ble_client.send_command(0x0A, payload)
    return {"power": "on" if req.on else "off"}


# ----------------------------------------------------------------------
# 颜色控制
# ----------------------------------------------------------------------

@app.post("/color")
async def set_color(req: ColorRequest):
    """设置整个窗帘为单一颜色"""
    _check_connection()
    await ble_client.send_command(
        0x0A,
        bytes([0xE2, 0x0B, req.hue, req.brightness]),
    )
    return {"hue": req.hue, "brightness": req.brightness}


# ----------------------------------------------------------------------
# 效果模式
# ----------------------------------------------------------------------

@app.post("/effect")
async def set_effect(req: EffectRequest):
    """设置内置效果模式"""
    _check_connection()
    await ble_client.send_command(
        0x0A,
        bytes([0xE0, 0x02, 0x00, req.effect_id, req.speed, req.brightness]),
    )
    return {
        "effect_id": req.effect_id,
        "speed": req.speed,
        "brightness": req.brightness,
    }


# ----------------------------------------------------------------------
# 亮度 & 速度
# ----------------------------------------------------------------------

@app.post("/brightness")
async def set_brightness(req: BrightnessRequest):
    """设置全局亮度"""
    _check_connection()
    await ble_client.send_command(
        0x0A,
        bytes([0xE2, 0x09, 0x01, 0x00, req.brightness, 0x00]),
    )
    return {"brightness": req.brightness}


@app.post("/speed")
async def set_speed(req: SpeedRequest):
    """设置全局速度"""
    _check_connection()
    await ble_client.send_command(
        0x0A,
        bytes([0xE2, 0x09, 0x01, req.speed, 0x00, 0x00]),
    )
    return {"speed": req.speed}


# ----------------------------------------------------------------------
# 音乐模式
# ----------------------------------------------------------------------

@app.post("/music")
async def set_music_mode(req: MusicModeRequest):
    """设置音乐模式 (设备麦克风)"""
    _check_connection()
    await ble_client.send_command(
        0x0A,
        bytes([
            0xE1, 0x05,
            0x01 if req.active else 0x00,
            req.brightness,
            req.effect_id,
            0x00, 0x00,
            req.sensitivity,
        ]),
    )
    return {"active": req.active}


@app.post("/phone-music")
async def set_phone_music(req: PhoneMusicRequest):
    """发送手机音乐可视化数据"""
    _check_connection()
    bands = [max(0, min(100, b)) for b in req.bands[:17]]
    payload = bytes([0xE2, 0x0A] + bands)
    await ble_client.send_command(0x0A, payload)
    return {"bands": len(bands)}


# ----------------------------------------------------------------------
# 文本显示
# ----------------------------------------------------------------------

@app.post("/text")
async def set_text(req: TextRequest):
    """设置滚动文本"""
    _check_connection()
    # 文本渲染需要位图字体数据, 这里使用简化实现
    text_data = req.text.encode("ascii", errors="ignore")[:20]
    await ble_client.send_command(
        0x0A,
        bytes([0xE2, 0x04, 0x00, 0x00]) + text_data,
    )
    # 设置文本速度和亮度
    await ble_client.send_command(
        0x0A,
        bytes([
            0xE2, 0x05, 0xFF, 0x01, 0x00, 0x00, 0x00,
            req.speed, 0x00, 0x00, 0x00, 0x00, 0x00,
            req.brightness, 0x00, 0x02,
        ]),
    )
    return {"text": req.text}


# ----------------------------------------------------------------------
# 像素控制
# ----------------------------------------------------------------------

@app.post("/pixels")
async def set_pixels(req: PixelsRequest):
    """设置单个像素"""
    _check_connection()
    # 构建 400 位位图 (50 字节)
    bitmap = bytearray(50)
    for p in req.pixels:
        idx = p.get("index", 0)
        if 0 <= idx < 400:
            byte_idx = idx // 8
            bit_idx = idx % 8
            bitmap[byte_idx] |= 1 << bit_idx

    payload = bytes([0xE2, 0x0C, 0x90, 0x00, 0x00]) + bytes(bitmap)
    await ble_client.send_command(0x0A, payload)
    return {"pixels": len(req.pixels)}


# ----------------------------------------------------------------------
# 动画上传
# ----------------------------------------------------------------------

@app.post("/animation")
async def upload_animation(req: AnimationRequest):
    """上传动画到设备"""
    _check_connection()
    frames = [base64.b64decode(f) for f in req.frames]
    num_frames = len(frames)

    # EA 01: 开始上传 (元数据)
    metadata = bytearray(38)
    metadata[0] = 0xEA
    metadata[1] = 0x01
    await ble_client.send_command(0x0A, bytes(metadata))
    await asyncio.sleep(0.1)

    # EA 02: 帧长度
    lengths = b"".join(len(f).to_bytes(4, "big") for f in frames)
    await ble_client.send_command(
        0x0A, bytes([0xEA, 0x02, 0x00, 0x00]) + lengths
    )
    await asyncio.sleep(0.1)

    # EA 03: 帧数据
    for i, frame in enumerate(frames):
        header = bytes([0xEA, 0x03]) + i.to_bytes(4, "big")
        await ble_client.send_command(0x0A, header + frame)
        await asyncio.sleep(0.05)

    # EA 04: 结束上传
    await ble_client.send_command(0x0A, bytes([0xEA, 0x04, 0x00]))

    return {"frames": num_frames}


# ----------------------------------------------------------------------
# 主页 (Web UI)
# ----------------------------------------------------------------------

@app.get("/")
async def root():
    """重定向到 Web UI"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


# ----------------------------------------------------------------------
# 入口
# ----------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
