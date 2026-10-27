"""
Surplife BLE 协议编码/解码器

基于逆向工程文档实现:
- 传输层: 分段/重组, 控制字节, 序列号
- 应用层: 命令封装 (cmd_id + payload)
"""

from __future__ import annotations


class SurplifeProtocol:
    """Surplife BLE 协议编码器/解码器"""

    # 控制字节标志位
    MULTILINE = 0x40   # bit 6: 多段消息
    PROTECT = 0x20     # bit 5: 保护/加密
    ACK = 0x10         # bit 4: 需要确认

    # 每段最大 payload (MTU 186 - 3 ATT 开销 = 183)
    MAX_FIRST_PAYLOAD = 175   # 183 - 8 (首段头)
    MAX_CONT_PAYLOAD = 178    # 183 - 5 (续段头)

    def __init__(self) -> None:
        self._seq = 0

    def _next_seq(self) -> int:
        self._seq = (self._seq + 1) & 0xFF
        return self._seq

    def encode(self, cmd_id: int, payload: bytes = b"") -> list[bytes]:
        """
        将命令编码为一个或多个 BLE 写入块。

        Args:
            cmd_id: 应用层命令 ID (如 0x0A 表示普通命令)
            payload: 命令 payload 字节

        Returns:
            可写入 BLE 特征的字节块列表
        """
        full_payload = bytes([cmd_id]) + payload
        data_len = len(payload)  # cmd_id 之后的长度
        seq = self._next_seq()

        if data_len + 1 <= self.MAX_FIRST_PAYLOAD:
            # 单段消息
            header = bytes([
                0x00,               # 控制: 单段
                seq,                # 序列号
                0x80, 0x00,         # Line ID: 未分段
                (data_len >> 8) & 0xFF, data_len & 0xFF,  # 总长度
                (data_len + 1) & 0xFF,  # 本段长度 (含 cmd_id)
                cmd_id,             # 命令 ID
            ])
            return [header + full_payload]

        # 多段消息
        chunks: list[bytes] = []

        # 首段
        first_data = full_payload[: self.MAX_FIRST_PAYLOAD]
        remaining = full_payload[self.MAX_FIRST_PAYLOAD:]

        header = bytes([
            self.MULTILINE,     # 控制: 多段首段
            seq,
            0x80, 0x00,         # Line ID
            (data_len >> 8) & 0xFF, data_len & 0xFF,
            len(first_data) & 0xFF,
            cmd_id,
        ])
        chunks.append(header + first_data)

        # 续段
        seg_idx = 0
        while remaining:
            chunk_data = remaining[: self.MAX_CONT_PAYLOAD]
            remaining = remaining[self.MAX_CONT_PAYLOAD:]
            seg_idx += 1

            is_last = len(remaining) == 0
            control = 0x00 if is_last else self.MULTILINE
            seg_id = 0x80 if is_last else 0x00

            header = bytes([
                control,
                seq,
                seg_id,
                seg_idx & 0xFF,
                len(chunk_data) & 0xFF,
            ])
            chunks.append(header + chunk_data)

        return chunks

    def decode(self, data: bytes) -> dict | None:
        """
        解码来自设备的消息。

        Returns:
            包含 control, seq, line_id, total_len, chunk_len, cmd_id, payload 的字典
        """
        if len(data) < 8:
            return None

        control = data[0]
        seq = data[1]
        line_id = (data[2] << 8) | data[3]
        total_len = (data[4] << 8) | data[5]
        chunk_len = data[6]
        cmd_id = data[7]
        payload = data[8:]

        return {
            "control": control,
            "seq": seq,
            "line_id": line_id,
            "total_len": total_len,
            "chunk_len": chunk_len,
            "cmd_id": cmd_id,
            "payload": payload,
        }
