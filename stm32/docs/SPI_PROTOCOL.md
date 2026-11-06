# MaixCAM <-> STM32 SPI v1 协议

本协议用于 MaixCAM（SPI 主机）与 STM32F103（SPI 从机）之间的控制、状态和温度数据交换。

- MaixCAM：SPI 主机，产生语音/表演事件和温度样本。
- STM32：SPI 从机，执行字牌 PWM 表演，接收温度，保留后续 PID 加热接口。
- USART3：仅 STM32 本地调试，不参与板间通信，也不作为 SPI 失效后的控制回退。

## 1. 物理层

| 项目 | 值 |
|---|---|
| SPI 模式 | Mode 0（CPOL=0, CPHA=0） |
| 数据位 | 8 bit |
| 位序 | MSB first |
| 片选 | 低有效，硬件 NSS |
| 建议时钟 | 1 MHz 起步，MaixCAM SPI4 上限约 1.25 MHz |
| 电平 | 双方 3.3 V |
| 连接 | SCK/MISO/MOSI/CS + 共地 |

MaixCAM 侧：

| 设备 | SPI 总线 | SCK | MISO | CS | MOSI |
|---|---|---|---|---|---|
| MaixCAM2 | SPI2 / CS1 | B20 | B19 | B21 | B18 |
| MaixCAM / MaixCAM-Pro | SPI4 | A22 | A23 | A24 | A25 |

MaixCAM2 的默认配置已按 `B18/B19/B20/B21` 和 `/dev/spidev2.1` 设计；实际以
板端 `pinmap` 和外部排针为准。

## 2. 帧格式

每次片选事务固定传输 **64 字节**，全双工。主机发送控制帧，同时从 MISO 读回 STM32 状态帧。

| Offset | Size | Field | 说明 |
|---:|---:|---|---|
| 0 | 2 | magic | 线上字节 `5A A5`，按小端读为 `0xA55A` |
| 2 | 1 | version | `1` |
| 3 | 1 | type | `0x01` 控制帧，`0x81` 状态帧 |
| 4 | 4 | seq | 发送方事务序号，u32 小端 |
| 8 | 4 | session_id | MaixCAM 每次启动生成的非零会话 ID，u32 小端 |
| 12 | 2 | payload_len | 0..44，u16 小端 |
| 14 | 2 | flags | 保留，填 0 |
| 16 | 44 | payload | TLV 区 |
| 60 | 2 | crc16 | 对 offset 0..59 计算，u16 小端 |
| 62 | 2 | reserved | 填 0 |

CRC：CRC-16/CCITT-FALSE，多项式 `0x1021`，初值 `0xFFFF`，不反射。

所有多字节整数均为小端。TLV 值不要求内存对齐，STM32 端按字节组装/解析。

## 3. TLV

每个 TLV：

```text
type   u8
len    u8
value  len bytes
```

未知 TLV 必须被跳过；STM32 会在状态中置 `UNKNOWN_TLV` 故障位。

### 3.1 控制 TLV（MaixCAM -> STM32）

#### HELLO = 0x01，len = 8

```text
0  u8   protocol_min     最小协议版本
1  u8   protocol_max     最大协议版本
2  u16  heartbeat_ms     主机建议心跳周期
4  u32  features         主机能力位
```

STM32 支持版本 1。收到合法 HELLO 后进入 ACTIVE，所有字牌保持 OFF，等待后续 PERFORM/STANDBY。

#### TEMP = 0x02，len = 10

```text
0  i32  temp_mc          主控温度，毫摄氏度，带符号
4  u16  sample_seq       温度样本序号
6  u16  age_ms           从采样到本帧发送的年龄，毫秒
8  u8   valid            0/1
9  u8   source           0=sysfs, 1=reg, 2=maix_sys, 0xFF=unknown
```

建议 1 Hz 发送。STM32 不要求每帧都有 TEMP，但会用 `age_ms` 和维护的接收时刻计算当前温度年龄。

#### PERFORM = 0x10，len = 12

```text
0  u32  glyph_mask       目标字牌位掩码
4  u8   action           动作，见下表
5  u8   profile_id       表演 profile，v1 仅 0
6  u32  event_seq        事件序号，必须递增
10 u16  value            保留；v1 填 0
```

动作：

| 值 | 名称 | 行为 |
|---:|---|---|
| 0 | STANDBY | 进入待机呼吸 |
| 1 | GATE | 从当前亮度 30 ms 上升到 100%，进入 HOLD |
| 2 | RELEASE | 开始 2.5 s 释放曲线 |
| 3 | EGG | 进入 3.6 s 不可打断彩蛋 |
| 4 | OFF | 立即熄灭 |

`event_seq` 按会话递增，从 1 开始。重复的 `event_seq` 不会再次执行；主机在收到 ACK 前可重发同一事件。

#### HEARTBEAT = 0x20，len = 8

```text
0  u32  maix_uptime_ms
4  u16  state_flags
6  u16  reserved
```

心跳也可以由任何合法控制帧隐含表达。STM32 以最后一次合法控制帧刷新链路超时。

#### ALL_OFF = 0x7F，len = 0

立即关闭所有字牌输出和加热输出。该命令不要求已经完成 HELLO。

#### THERMAL_CONFIG = 0x30，保留

v1 不实现加热/PID。收到该 TLV 时 STM32 置 `HEATER_UNSUPPORTED`，HEAT1/HEAT2 保持 0%。

### 3.2 状态 TLV（STM32 -> MaixCAM）

#### STATUS = 0x81，len = 29 + GLYPH_COUNT

```text
0  u32  last_control_seq   最后处理的合法控制帧 seq
4  u32  last_event_seq     最后接受的 PERFORM event_seq
8  u32  active_mask        当前处于 INTRO/HOLD/RELEASE/EGG 的字牌掩码
12 u32  stm32_uptime_ms
16 u16  fault_flags
18 i32  temp_mc            STM32 当前使用的温度
22 u16  temp_age_ms        当前温度年龄，0xFFFF 表示无有效样本
24 u8   temp_valid         0/1
25 u8   link_state         0=BOOT, 1=WAIT_HELLO, 2=ACTIVE, 3=LOST, 4=FAULT
26 u16  temp_sample_seq    最近一次 TEMP 的样本序号
28 u8   temp_source        0=sysfs, 1=reg, 0xFF=unknown
29 u8   glyph_state[GLYPH_COUNT]
```

#### CAPS = 0x82，len = 8

```text
0  u8   protocol_version   1
1  u8   glyph_count        当前字牌数
2  u8   pwm_channel_count  15
3  u8   reserved
4  u32  features           STM32 能力位
```

能力位：

| bit | 名称 |
|---:|---|
| 0 | PERFORM |
| 1 | TEMP |
| 2 | HEARTBEAT |
| 3 | EGG |
| 4 | THERMAL_PID（v1 为 0） |
| 5 | DIRECT（v1 为 0） |

## 4. 故障位

| bit | 名称 | 含义 |
|---:|---|---|
| 0 | CRC | CRC 错误 |
| 1 | FORMAT | 帧格式/长度错误 |
| 2 | SPI | SPI 外设错误或事务超时 |
| 3 | UNKNOWN_TLV | 未知 TLV |
| 4 | NEED_HELLO | 未握手却收到 PERFORM |
| 5 | TEMP_STALE | 温度样本过旧 |
| 6 | TEMP_INVALID | 温度值无效 |
| 7 | HEATER_UNSUPPORTED | 收到 v1 未实现的加热配置 |
| 8 | BAD_MASK | glyph_mask 含未知位或为 0 |
| 9 | PROTOCOL | 协议版本不兼容 |
| 10 | LINK_LOST | 链路超时 |
| 11..15 | 保留 |

## 5. 主从交互

### 5.1 上电

1. STM32 上电后所有 PWM=0，HEAT1/2=0，进入 BOOT。
2. MaixCAM 生成非零 `session_id`，发送 HELLO。
3. STM32 记录会话，回到安全状态，进入 ACTIVE，并在下一次事务的 STATUS 中确认。
4. MaixCAM 收到 ACTIVE 后发送 STANDBY 或 GATE。

### 5.2 ACK 延迟

STM32 在本次 SPI 传输结束后才能解析请求，因此 **STATUS 是下一帧事务返回的**。在 20 Hz 事务下，ACK 延迟约 50 ms。

主机规则：

- 待发送事件保存在 pending 队列。
- 每帧都带当前 pending 事件，直到 STATUS 的 `last_event_seq >= event_seq`。
- 同一事件重发时保持相同 `event_seq`。
- 收到重复帧时 STM32 只回状态，不重复执行。

### 5.3 链路超时

- 建议主机 20 Hz 发送控制帧；TEMP 可 1 Hz。
- STM32 连续 **500 ms** 未收到 CRC 合法控制帧：
  - 所有字牌 OFF；
  - HEAT1/HEAT2=0；
  - 进入 LOST；
  - 要求新的 HELLO 才能恢复 ACTIVE。
- 任何合法帧都可以刷新“物理链路在线”，但只有 HELLO 能恢复执行权限。

## 6. v1 表演语义

### GATE

对 `glyph_mask` 中每个字牌：

- 记录当前亮度；
- 30 ms smoothstep 上升到 100%；
- 进入 HOLD，保持 100%。

### RELEASE

对 `glyph_mask` 中每个字牌：

```text
0..500 ms       当前亮度 -> 50%
500..1300 ms    50% -> 35%
1300..2500 ms   35% -> 8%（线性）
2500 ms 后      回到待机呼吸，从 8% 高点接上
```

当前 v1 的 0..1300 ms 段使用整数 ease-out 近似，后续可替换为与原 Python 完全一致的 LUT。

### EGG

对 `glyph_mask` 中每个字牌：

```text
0..1600 ms      0.1 s 100% / 0.1 s 0%，共 8 个周期
1600..3600 ms   0%
3600 ms 后      回到待机呼吸，从 1% 低点接上
```

彩蛋期间该字牌忽略 GATE/RELEASE/STANDBY；ALL_OFF 仍然可以立即关闭。

### STANDBY

1%..8%，4 s 正弦呼吸。

### OFF

输出 0%，直到下一条 GATE/STANDBY。

## 7. 当前字牌映射

`Core/Inc/glyph_map.h` 中的 X-Macro 是唯一映射源：

```text
GLYPH_CHANG ("长") -> BOARD_PWM_PWM1 -> TIM2_CH1 / PA0 / 2 kHz
GLYPH_CHUN  ("春") -> BOARD_PWM_PWM2 -> TIM2_CH2 / PA1 / 2 kHz
```

协议只传数字 `glyph_id`/`glyph_mask`，不传 TIM/CH，也不传中文字符串。

## 8. 当前 STM32 实现

| 文件 | 作用 |
|---|---|
| `Core/Inc/glyph_map.h` | 汉字/字牌 ID 到 `BOARD_PWM_*` 的 X-Macro 映射 |
| `Core/Inc/board_pwm.h` | 15 路 PWM 逻辑输出到 TIM/CH 的映射 |
| `Core/Src/app_perf.c` | 待机呼吸、GATE、HOLD、RELEASE、EGG 本地表演引擎 |
| `Core/Src/app_spi_link.c` | SPI 从机固定帧、TLV、CRC、会话/序号、状态、TEMP 接收 |
| `Core/Src/app_debug.c` | USART3 本地调试输出 |
| `tools/stm32_protocol.py` | 主机侧帧/TLV 参考实现 |
| `tools/maixcam_spi_link.py` | MaixCAM SPI4 主机传输参考 |
| `docs/SPI_PROTOCOL.md` | 本协议 |

当前 v1：

- “长” → PWM1 → TIM2_CH1 / PA0 / 2 kHz
- “春” → PWM2 → TIM2_CH2 / PA1 / 2 kHz
- 15 路 PWM 全部初始化为 0
- HEAT1/HEAT2 固定 0%
- 仅接收温度并在 STATUS 回显，不做 PID
- SPI 超时 500 ms，超时后全部输出关闭
- 收到 HELLO 后仍需显式 STANDBY/GATE 才点灯
- USART3 只打印本地调试日志

## 9. 加热接口预留

v1 接收 TEMP，但不控制 HEAT1/HEAT2。后续 PID 接入时扩展：

- `THERMAL_CONFIG`：目标温度、Kp/Ki/Kd、最大占空比、超时；
- `HEATER_ENABLE`：显式使能；
- 温度过期、链路丢失、未使能时加热强制关闭；
- 控制周期建议 1 s 或更慢，因为 SG2002 温度传感器约 1.048 s 更新一次。
