"""
Surplife LED 窗帘灯 BLE 客户端 (bleak)

在 MaixCAM (BlueZ 5.68 + bleak 3.x) 和普通 Linux/Mac/Windows 上都可运行。
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Any

# 直接导入/运行本文件时，也能找到项目内的纯 Python 依赖。
_LIB_DIR = os.environ.get("SURPLIFE_LIB", "/root/surplife/lib")
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

import protocol as P

log = logging.getLogger("surplife.ble")

SERVICE_UUID = "0000ffff-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

DEVICE_NAME_PREFIX = "IOTBT"

# 官方 App 使用的 MTU; V0 传输层单段不能超过 255 字节
APP_MTU = 186


class SurplifeBLEClient:
    """Surplife LED 窗帘灯 BLE 客户端"""

    def __init__(self) -> None:
        self.client: BleakClient | None = None
        self.address: str | None = None
        self.protocol = P.SurplifeProtocol(APP_MTU)
        self._status: dict[str, Any] = {}
        self._status_event = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._keepalive_task: asyncio.Task | None = None
        self.last_notify_ts: float | None = None

    # ------------------------------------------------------------------
    # 扫描 & 连接
    # ------------------------------------------------------------------

    async def scan(self, timeout: float = 5.0) -> list[dict[str, Any]]:
        """扫描附近的 Surplife 设备 (名称 IOTBTxxx)"""
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        results = []
        for device, adv in found.values():
            name = device.name or adv.local_name or ""
            if name.startswith(DEVICE_NAME_PREFIX):
                results.append({"name": name, "address": device.address, "rssi": adv.rssi})
        results.sort(key=lambda d: d["rssi"], reverse=True)
        return results

    async def connect(self, address: str | None = None, timeout: float = 10.0,
                      retries: int = 3) -> str:
        """
        连接窗帘灯。address 为空时扫描并选信号最强的设备。

        BlueZ 下设备缓存可能过期 (报 "device not found"), 因此每次连接前
        都先扫描拿到最新的 BLEDevice, 并在失败时重试。
        """
        async with self._connect_lock:
            await self._disconnect_unlocked()

            last_err: Exception | None = None
            for attempt in range(1, retries + 1):
                try:
                    if address:
                        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
                        if device is None:
                            raise ConnectionError(f"未找到设备 {address}")
                    else:
                        devices = await self.scan(timeout)
                        if not devices:
                            raise ConnectionError("未找到 Surplife 窗帘灯设备")
                        device = await BleakScanner.find_device_by_address(
                            devices[0]["address"], timeout=timeout)
                        if device is None:
                            raise ConnectionError("设备在扫描后消失")

                    client = BleakClient(device, disconnected_callback=self._on_disconnect,
                                         timeout=timeout)
                    await client.connect()
                    self.client = client
                    self.address = device.address
                    await self._setup()
                    return device.address
                except Exception as e:  # noqa: BLE001 - 汇总后重试
                    last_err = e
                    log.warning("连接失败 (%d/%d): %r", attempt, retries, e)
                    await self._disconnect_unlocked()
                    await asyncio.sleep(1.0)
            raise ConnectionError(f"连接失败: {last_err}")

    async def _setup(self) -> None:
        assert self.client is not None
        # BlueZ 后端需要主动获取 MTU, 否则 mtu_size 默认 23
        try:
            acquire = getattr(self.client._backend, "_acquire_mtu", None)
            if acquire:
                await acquire()
        except Exception as e:  # noqa: BLE001
            log.info("获取 MTU 失败, 使用默认值: %r", e)
        mtu = self.client.mtu_size or 23
        self.protocol.set_mtu(min(mtu, APP_MTU))
        log.info("已连接 %s, MTU=%d", self.address, mtu)

        await self.client.start_notify(NOTIFY_CHAR_UUID, self._on_notification)

        # 初始化序列: 时间同步 -> 查询状态 (与官方 App 一致)
        await self.send(P.cmd_time_sync())
        await self.send(P.cmd_query_status())
        await self.wait_status(2.0)

        self._keepalive_task = asyncio.create_task(self._keepalive())

    async def _keepalive(self, interval: float = 30.0) -> None:
        """周期性查询状态, 防止连接闲置被断开"""
        try:
            while self.is_connected:
                await asyncio.sleep(interval)
                if self.is_connected:
                    await self.send(P.cmd_query_status())
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            log.warning("保活失败: %r", e)

    def _on_disconnect(self, _client: BleakClient) -> None:
        log.warning("设备已断开")

    async def _disconnect_unlocked(self) -> None:
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self.client:
            try:
                if self.client.is_connected:
                    await self.client.disconnect()
            except Exception as e:  # noqa: BLE001
                log.info("断开时出错: %r", e)
        self.client = None

    async def disconnect(self) -> None:
        async with self._connect_lock:
            await self._disconnect_unlocked()

    async def ensure_connected(self) -> None:
        """意外断开后自动重连上一次的设备"""
        if self.is_connected:
            return
        if not self.address:
            raise ConnectionError("未连接到设备")
        await self.connect(self.address)

    # ------------------------------------------------------------------
    # 通知
    # ------------------------------------------------------------------

    def _on_notification(self, _sender: BleakGATTCharacteristic, data: bytearray) -> None:
        msg = self.protocol.decode(bytes(data))
        if not msg:
            return
        log.debug("<< %s", bytes(data).hex())
        self.last_notify_ts = time.time()
        if msg["cmd_id"] in (P.NOTIFY_STATUS, P.NOTIFY_QUERY_REPLY):
            st = P.parse_status(msg["payload"])
            if st:
                self._status = st
                self._status_event.set()

    async def wait_status(self, timeout: float = 2.0) -> dict[str, Any] | None:
        try:
            await asyncio.wait_for(self._status_event.wait(), timeout)
            return self.status
        except asyncio.TimeoutError:
            return None

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------

    async def send(self, payload: bytes, cmd_id: int = P.CMD_CONTROL) -> None:
        """发送一条应用层命令 (自动分段, 写入串行化)"""
        if not self.is_connected:
            raise ConnectionError("未连接到设备")
        async with self._write_lock:
            self._status_event.clear()
            for chunk in self.protocol.encode(cmd_id, payload):
                log.debug(">> %s", chunk.hex())
                await self.client.write_gatt_char(WRITE_CHAR_UUID, chunk, response=True)

    async def send_many(self, payloads: list[bytes], delay: float = 0.05) -> None:
        for p in payloads:
            await self.send(p)
            if delay:
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self.client is not None and self.client.is_connected

    @property
    def status(self) -> dict[str, Any]:
        return dict(self._status)
