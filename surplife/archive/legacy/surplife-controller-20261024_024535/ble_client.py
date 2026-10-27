"""
Surplife LED 窗帘灯 BLE 客户端

使用 bleak 库进行 BLE 通信。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

from protocol import SurplifeProtocol


# BLE GATT UUIDs
SERVICE_UUID = "0000ffff-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

# 设备名称前缀
DEVICE_NAME_PREFIX = "IOTBT"


class SurplifeBLEClient:
    """Surplife LED 窗帘灯 BLE 客户端"""

    def __init__(self) -> None:
        self.client: BleakClient | None = None
        self.protocol = SurplifeProtocol()
        self._status: dict[str, Any] = {}
        self._response_event = asyncio.Event()
        self._last_response: dict | None = None

    # ------------------------------------------------------------------
    # 扫描 & 连接
    # ------------------------------------------------------------------

    async def scan(self, timeout: float = 5.0) -> list[dict[str, Any]]:
        """扫描附近的 Surplife 设备"""
        devices = await BleakScanner.discover(timeout=timeout)
        results = []
        for d in devices:
            if d.name and d.name.startswith(DEVICE_NAME_PREFIX):
                results.append({
                    "name": d.name,
                    "address": d.address,
                    "rssi": d.rssi,
                })
        return results

    async def connect(self, address: str | None = None, timeout: float = 10.0) -> None:
        """
        连接到 Surplife 窗帘灯。

        Args:
            address: 设备 MAC 地址; 为 None 时自动扫描并连接第一个找到的设备
            timeout: 扫描超时时间 (秒)
        """
        if address is None:
            devices = await self.scan(timeout)
            if not devices:
                raise ConnectionError("未找到 Surplife 窗帘灯设备")
            address = devices[0]["address"]

        self.client = BleakClient(address)
        await self.client.connect()

        # 尝试设置 MTU (某些平台可能不支持)
        try:
            if hasattr(self.client, "_backend") and hasattr(self.client._backend, "_mtu_size"):
                await self.client._backend._mtu_size(186)
        except Exception:
            pass

        # 启用通知
        await self.client.start_notify(
            NOTIFY_CHAR_UUID,
            self._on_notification,
        )

        # 发送初始化序列
        await self._initialize()

    async def disconnect(self) -> None:
        """断开与设备的连接"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
        self.client = None

    # ------------------------------------------------------------------
    # 通知处理
    # ------------------------------------------------------------------

    def _on_notification(
        self, sender: BleakGATTCharacteristic, data: bytearray
    ) -> None:
        """处理来自设备的通知"""
        msg = self.protocol.decode(bytes(data))
        if msg:
            self._last_response = msg
            self._response_event.set()
            self._response_event.clear()
            self._parse_status(msg)

    def _parse_status(self, msg: dict) -> None:
        """从通知中解析设备状态"""
        if msg["cmd_id"] == 0x16:  # 二进制状态
            payload = msg["payload"]
            if len(payload) >= 10 and payload[0] == 0xEA and payload[1] == 0x81:
                self._status = {
                    "power": "on" if payload[6] == 0x23 else "off",
                    "mode": payload[4],
                    "model": payload[5],
                    "brightness": payload[9] if len(payload) > 9 else None,
                    "speed": payload[10] if len(payload) > 10 else None,
                }

    # ------------------------------------------------------------------
    # 初始化序列
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """发送初始化序列 (时间同步 + 握手)"""
        # 时间同步
        now = datetime.now()
        time_payload = bytes([
            0x10,
            0x14,                    # 世纪 (20xx)
            now.year % 100,          # 年
            now.month,               # 月
            now.day,                 # 日
            now.hour,                # 时
            now.minute,              # 分
            now.second,              # 秒
            now.weekday() + 1,       # 星期 (1=Mon...7=Sun)
            0x00,                    # 保留
        ])
        await self._send_raw(0x0A, time_payload)
        await asyncio.sleep(0.1)

        # 握手
        await self._send_raw(0x0A, bytes([0xEA, 0x81, 0x8A, 0x8B, 0x59]))
        await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # 底层发送
    # ------------------------------------------------------------------

    async def _send_raw(self, cmd_id: int, payload: bytes) -> None:
        """发送原始命令"""
        chunks = self.protocol.encode(cmd_id, payload)
        for chunk in chunks:
            await self.client.write_gatt_char(WRITE_CHAR_UUID, chunk)
            await asyncio.sleep(0.05)

    async def send_command(
        self,
        cmd_id: int,
        payload: bytes,
        wait_response: bool = False,
        timeout: float = 2.0,
    ) -> dict | None:
        """
        发送命令并可选等待响应。

        Args:
            cmd_id: 命令 ID
            payload: 命令 payload
            wait_response: 是否等待响应
            timeout: 等待超时时间 (秒)

        Returns:
            响应消息字典, 或 None (超时)
        """
        await self._send_raw(cmd_id, payload)

        if wait_response:
            try:
                await asyncio.wait_for(self._response_event.wait(), timeout)
                return self._last_response
            except asyncio.TimeoutError:
                return None
        return None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    @property
    def status(self) -> dict[str, Any]:
        return self._status.copy()
