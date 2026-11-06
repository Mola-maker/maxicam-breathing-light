# EnlightenJLU

**语音控制的灯牌 PWM 效果**：MaixCAM 负责音频、语音判断和高层表演决策，STM32F103C8T6 负责 15 路灯牌 PWM、安全看门狗和预留的保温板加热执行。

> 当前工作树是清理后的结构。旧 Surplife BLE/HTTP 窗帘代码、旧备份、日志、截图和运行归档没有迁入；原版本仍在一代 MaixCAM Pro 设备和远端 Git 历史中。

## 1. 系统架构

```text
麦克风
  ├─ MaixCAM Pro（一代）── Maix-Speech KWS ──┐
  └─ MaixCAM2（二代）──── SenseVoice ASR ───┤
                                             ▼
                         PERFORM / TEMP / HEARTBEAT（SPI v1）
                                             │
                                             ▼
                              STM32F103C8T6 执行器
                        15 路灯牌 PWM + 2 路加热 PWM
                                             │
                                             ▼
                                灯牌 / 保温板（6 个功率电阻）
```

设计原则：

- 语音识别和判断放在 MaixCAM；
- STM32 只接受数字化的 `glyph_mask`、动作和温度，不运行语音模型；
- STM32 上电、未握手、SPI 断链、`ALL_OFF` 时所有输出关闭；
- 两代 MaixCAM 都保留本地 PWM 作为脱机联调回退，不替代最终 STM32 15 路输出。

## 2. 目录结构

```text
EnlightenJLU/
├── README.md
├── .gitignore
├── docs/
│   └── ASSET_INVENTORY.md
├── model/                         # 模型描述、运行支撑、清单
│   ├── README.md
│   ├── manifest.json
│   ├── maixcam_pro/
│   └── maixcam2/
├── maixcam/
│   ├── README.md
│   ├── pro/                       # 一代 MaixCAM Pro
│   └── maixcam2/                  # 二代 MaixCAM2
└── stm32/                         # 15 PWM + 保温板
    ├── Core/
    ├── Drivers/
    ├── cmake/
    ├── docs/
    ├── tools/
    ├── firmware/
    ├── CMakeLists.txt
    ├── CMakePresets.json
    ├── PWM-Heater.ioc
    └── README.md
```

## 3. 资产总览

| 目录 | 文件数 | 大小 | 说明 |
|---|---:|---:|---|
| `maixcam/pro/` | 17 | 约 256 KB | 一代 KWS、门控、A18/A19 PWM、触摸 UI、温度 |
| `maixcam/maixcam2/` | 23 | 约 260 KB | 二代 SenseVoice、SPI、USB 麦克风、A30/PWM6、麦克风 UI |
| `model/` | 18 | 约 1.2 MB | 描述符、SenseVoice 运行支撑、清单；大权重外置 |
| `stm32/` | 946 | 约 69 MB | HAL/CMSIS、15 路 PWM、SPI v1、表演引擎、协议、已验证固件 |
| `docs/` | 1 | 约 12 KB | 资产来源、迁移关系、排除项和验证状态 |

文件级清单见 [`docs/ASSET_INVENTORY.md`](docs/ASSET_INVENTORY.md)。

## 4. 模型

### MaixCAM Pro（一代）

```text
/root/models/am_3332_192_int8.mud
```

Maix-Speech KWS 注册：

```text
chang1 chang2 chang4
chun1 chun2 chun3
ang1 ang2
chang2 chun1
```

`ang` 仅调试，不触发。权重只在一代 Pro 设备上，未进入仓库；见 [`model/maixcam_pro/README.md`](model/maixcam_pro/README.md)。

### MaixCAM2（二代）

```text
/root/models/sensevoice-maixcam2/
```

SenseVoice 非流式 + 流式模型。仓库已包含除两个 `.axmodel` 权重外的全部运行支撑：

```text
model/maixcam2/sensevoice-maixcam2/
```

两个权重约 505 MB，不进入普通 Git；大小和 SHA256 见 [`model/maixcam2/README.md`](model/maixcam2/README.md) 和 [`model/manifest.json`](model/manifest.json)。

## 5. 快速开始

### 5.1 MaixCAM Pro（一代）

```sh
cp -a maixcam/pro/app/. /root/surplife/app/
mkdir -p /root/surplife/run /root/surplife/logs /root/surplife/artifacts
```

模型保持在 `/root/models/am_3332_192_int8.mud`。

```sh
cd /root/surplife/app
./run_voice_pwm.sh
```

后台管理：

```sh
./start_voice_pwm.sh
./status_voice_pwm.sh
./stop_voice_pwm.sh
```

触摸 UI：

```sh
./run_lamp_ui.sh
```

一代约 128 MB 内存，后台语音和 UI 不要同时长期运行。

### 5.2 MaixCAM2（二代）

```sh
cp -a maixcam/maixcam2/. /root/JLU_LEDLAB/
```

准备模型支撑：

```sh
cp -a model/maixcam2/sensevoice-maixcam2/. \
      /root/models/sensevoice-maixcam2/
cp model/maixcam2/sensevoice.mud \
   /root/JLU_LEDLAB/config/sensevoice.mud
```

两个 SenseVoice 权重从已有设备/受控存储另行放置。

临时“长春”语音 + 本地 A30/PWM6 灯效：

```sh
cd /root/JLU_LEDLAB
./start_usb_local.sh
```

停止：

```sh
./stop.sh
```

麦克风实时可视化 UI：

```sh
cd /root/JLU_LEDLAB/audio_ui
./run_mic_ui.sh
```

麦克风 UI 和语音业务都使用 USB capture，不能同时运行。

### 5.3 STM32

```sh
cd stm32
cmake --preset Release
cmake --build --preset Release
```

烧录已验证固件：

```sh
st-flash --reset write stm32/firmware/PWM-Heater.bin 0x08000000
```

文档：

- [`stm32/README.md`](stm32/README.md)
- [`stm32/docs/BUILD.md`](stm32/docs/BUILD.md)
- [`stm32/docs/SPI_PROTOCOL.md`](stm32/docs/SPI_PROTOCOL.md)
- [`stm32/docs/HARDWARE.md`](stm32/docs/HARDWARE.md)

## 6. 当前功能

### MaixCAM Pro

- Maix-Speech 单字/整词 KWS；
- 单字 `chang`/`chun` 时序拼装，整词 `chang2 chun1` 直接开门；
- A18/PWM6、A19/PWM7 本地 1 kHz 灯效；
- 待机呼吸、30 ms 上升、保持、2.5 s 释放、10 s 肺活量彩蛋；
- 触摸调试 UI；
- SG2002 温度读取。

### MaixCAM2

- SenseVoice 中文/多语种 ASR；
- “长/春/长春”字符族和整词匹配；
- USB 外接麦克风 + `snd-usb-audio`；
- SPI2/CS1 v1 主机传输；
- A30/PWM6 本地临时表演；
- 640×480 麦克风电平/波形/频谱 UI；
- 13 字标语评测和 USB 麦克风测试记录。

### STM32

- 15 路 PWM：13 路灯牌 + HEAT1/HEAT2；
- “长”→PWM1，“春”→PWM2；
- STANDBY/INTRO/HOLD/RELEASE/EGG/OFF；
- SPI v1 固定 64 字节帧、TLV、CRC16、会话/序号去重；
- 500 ms 链路超时全关；
- TEMP 接收和 STATUS 回显；
- **v1 不做 PID，HEAT1/HEAT2 固定 0%**。

## 7. 已验证状态和限制

2026-11-04 已用 ST-Link V2 烧录 STM32 固件并读回校验：

```text
PWM-Heater.bin
SHA256 4dd2531314719912d362bdd68c30d4070f1af02e951cdb218111c1f67ebab609
```

烧录后读到：

```text
TIM2 CR1=0x00000001 PSC=35 ARR=999  CCR1..4=0
TIM4 CR1=0x00000081 PSC=8  ARR=399  CCR1..3=0
```

说明新固件运行，15 路输出和 6 个功率电阻全关。

2026-11-06 已用同一 ST-Link V2 烧录 MaixCAM Pro 测试扩展固件并校验通过：

```text
PWM-Heater-test.bin
SHA256 5fcb600380c41cd2619e35c9e5158ee10e6a86e7c56c53df17ff6707ff81ca78
```

该固件包含 `GLYPH_ALL_LAMPS`（PWM1–PWM13，排除 HEAT1/2）、USART3 `[temp]`
打印，以及按最大占空比聚合灯牌输出的修正。MaixCAM Pro 尚未接回，SPI、13 路灯牌
动作和温度打印仍需整机联调。

已知限制：

- SPI 时序和完整 15 路灯牌尚未系统级联调；
- ST-Link NRST 尚未接，建议后续调试补上；
- 保温板 PID、温度闭环、过流/过温保护尚未实现；
- 一代 Pro 权重只存在设备上；
- 语音业务和麦克风 UI 不能同时占用 USB 麦克风；
- 不提交密钥、密码、个人语音录音或 token。

## 8. 旧代码清理说明

已从工作树移除：

- `surplife/archive/`、日志、截图、PID/FIFO 和临时音频；
- 与灯牌 PWM 无关的 Surplife BLE/HTTP 窗帘控制；
- `light-dots`、主机端关键词记录器、旧 `maixcam` 姿态示例；
- `__pycache__`、构建产物和本地模型副本。

原版本仍可从一代 MaixCAM Pro 的 `/root/surplife/app` 和远端 Git 历史追溯。

## 9. 相关文档

- [`docs/ASSET_INVENTORY.md`](docs/ASSET_INVENTORY.md)
- [`model/README.md`](model/README.md)
- [`maixcam/README.md`](maixcam/README.md)
- [`maixcam/pro/README.md`](maixcam/pro/README.md)
- [`maixcam/maixcam2/README.md`](maixcam/maixcam2/README.md)
- [`stm32/README.md`](stm32/README.md)
- [`stm32/docs/SPI_PROTOCOL.md`](stm32/docs/SPI_PROTOCOL.md)
- [`stm32/docs/HARDWARE.md`](stm32/docs/HARDWARE.md)

## 10. 许可与第三方代码

STM32 HAL/CMSIS、MaixPy/MaixCDK、SenseVoice 支撑代码及其他第三方组件遵循各自许可证；使用前请核对原始项目许可。本仓库不额外声明第三方代码的所有权。
