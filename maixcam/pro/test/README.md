# MaixCAM Pro SPI / 英文关键词灯效验证

本目录是 `/root/surplife/test` 的源代码。

## 1. 业务目标

```text
麦克风
  └─ Maix-Speech KWS（板上原有模型）
       ├─ hello   → SPI PERFORM GATE mask=0x4
       └─ welcome → SPI PERFORM GATE mask=0x4
                         │
                         ▼
              STM32F103：PWM1..PWM13 全亮
                         （HEAT1/HEAT2 永远不参与）
```

- 关键词触发后，STM32 的 `GLYPH_ALL_LAMPS` 逻辑字牌驱动 **PWM1–PWM13**；
- `HEAT1/HEAT2`（PB8/PB7，TIM4_CH3/CH2）不激活；
- 触发后保持 `hold_seconds=1.2`，随后发 `RELEASE`，回到 13 路灯牌的待机呼吸；
- MaixCAM 同时以 1 Hz 读取 SG2002 `/sys/class/thermal/thermal_zone0/temp`，
  通过 `TEMP` TLV 发给 STM32；
- STM32 的 USART3 本地调试口会打印 `[temp] ... mC ...`。

## 2. 重要限制：英文词与现有模型

板上已有模型 `am_3332_192_int8` 是 **中文拼音 KWS 模型**，不是英文 ASR：

- 直接 `speech.kws(["hello", "welcome"], ...)` 会报 `parse kws ... error`；
- 英文 TTS `hello/welcome` 在中文拼音候选下概率为 0；
- 本测试使用中文近音代理，日志仍显示英文业务标签：

| 业务标签 | 实际 KWS 拼音 | 说明 |
|---|---|---|
| `hello` | `ha1 lou2` | 哈喽 |
| `welcome` | `wei1 er2 kang1` | 威尔康 |

这可以在现有模型上验证关键词 → SPI → 全灯业务。若必须严格识别英文
发音，需要替换/新增英文 KWS 模型，不能只改 `kws` 字符串。

中文近音测试 WAV：

```text
wav/hallo_zh_16k_pad.wav
wav/weierkang_zh_16k_pad.wav
```

英文原始 TTS 也保留在 `wav/hello_16k_pad.wav`、`wav/welcome_16k_pad.wav`，
用于对比；当前模型不会触发它们。

## 3. 硬件连接

MaixCAM Pro 外部 SPI4：

| MaixCAM Pro | STM32 |
|---|---|
| A22 / SPI4_SCK | PA5 / SPI1_SCK |
| A23 / SPI4_MISO | PA6 / SPI1_MISO |
| A24 / SPI4_CS | PA4 / SPI1_NSS |
| A25 / SPI4_MOSI | PA7 / SPI1_MOSI |
| GND | GND |

Linux 设备：

```text
/dev/spidev3.0
```

SPI 模式 0、8 bit、1 MHz。ST-Link 不在本测试链路上；它只用于烧录 STM32。

## 4. 运行

实时麦克风 + SPI：

```sh
cd /root/surplife/test
./run_test.sh
```

无 SPI，只验证 KWS：

```sh
./run_test.sh --no-spi --wav wav/hallo_zh_16k_pad.wav
./run_test.sh --no-spi --wav wav/weierkang_zh_16k_pad.wav
```

只验证 WAV，但仍尝试打开 SPI：

```sh
./run_test.sh --wav wav/hallo_zh_16k_pad.wav
```

停止：`Ctrl-C`。

## 5. STM32 端要求

本测试要求 STM32 固件包含：

- `GLYPH_ALL_LAMPS = 0x4`，驱动 PWM1..PWM13，不驱动 HEAT1/HEAT2；
- `TEMP` TLV 处理时通过 USART3 打印：

```text
[temp] 41350 mC seq=1 age=0ms valid=1 source=0
```

本目录已放入新测试固件和回退固件：

```text
firmware/PWM-Heater-test.hex        # 新：GLYPH_ALL_LAMPS + [temp] 打印
firmware/PWM-Heater-test.bin
firmware/PWM-Heater-v1-base.hex      # 旧：已验证基线
firmware/PWM-Heater-v1-base.bin
```

新固件 SHA256：

```text
PWM-Heater-test.bin
5fcb600380c41cd2619e35c9e5158ee10e6a86e7c56c53df17ff6707ff81ca78
```

烧录命令（在 ST-Link 所在主机上执行）：

```sh
st-flash --reset write firmware/PWM-Heater-test.bin 0x08000000
```

必须用 ST-Link 烧录 `PWM-Heater-test.bin` 到 STM32 后，SPI 才会返回有效
STATUS。2026-11-06 已在工作站上通过 ST-Link V2 烧录并校验通过；但 MaixCAM Pro
与 STM32 还未连接，SPI、13 路灯牌动作和 USART3 温度打印仍需整机验证。

## 6. 自检

```sh
python3 tools/probe_kws.py /root/models/am_3332_192_int8.mud \
  wav/hallo_zh_16k_pad.wav "ha1 lou2"
```

期望 `kws ret Err.ERR_NONE`，并看到约为 **0.63** 的最大概率。

SPI 探测：

```sh
python3 tools/probe_spi.py 3 0
```

如果返回 `rx magic 5aa5`，说明 STM32 已供电、接线正确并烧录了新固件；如果
持续 `rx magic 0000`，优先检查 3.3V、共地、PA4–PA7 ↔ A22–A25 和 STM32 固件。


## 7. 本次实测状态

在 MaixCAM Pro 上：

- 模型可加载，中文近音 `ha1 lou2` 在线下 WAV 测试中最高概率约 **0.638**，
  `wei1 er2 kang1` 约 **0.158**；
- 原始英文 TTS `hello`/`welcome` 对中文拼音代理关键词概率为 **0**，
  说明现有模型不能直接做英文 KWS；
- SG2002 温度读取正常，实测约 **41.648 °C**，已构造 TEMP TLV；
- `/dev/spidev0.0`～`spidev3.0` 均能打开，但当前没有收到 STM32 的
  `5A A5` STATUS 响应（收到 `00 00`），需要检查 STM32 供电、SPI4 接线和
  是否已经烧录新固件；
- 2026-11-06：ST-Link V2 已在工作站上烧录 `PWM-Heater-test.bin`，`st-flash`
  写入并校验通过，随后软件复位；下次把 STM32 接到 MaixCAM Pro 后重新运行
  `python3 tools/probe_spi.py 3 0`，预期返回 `rx magic 5aa5`。
