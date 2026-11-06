# 资产清单与迁移记录

生成时间：2026-11-06  
项目：语音控制的灯牌 PWM 效果  
仓库：`Mola-maker/maxicam-breathing-light`，`main` 分支

## 1. 来源与处置

| 来源 | 内容 | 处置 |
|---|---|---|
| `/home/jlu/桌面/EnlightenJLU/surplife/app` | 一代 Pro KWS、门控、A18/A19 PWM、UI、温度读取 | 只保留语音 PWM 相关文件，迁入 `maixcam/pro/app/` |
| `/home/jlu/桌面/CubeMX/C8T6/PWM-Heater/maixcam2_app` | 二代 SenseVoice、SPI、USB 麦克风、A30/PWM6、UI | 迁入 `maixcam/maixcam2/` |
| `/home/jlu/桌面/CubeMX/C8T6/PWM-Heater` | STM32 15 路 PWM、SPI、表演引擎、保温板占位 | 迁入 `stm32/`，排除 build 和 MaixCAM 子目录 |
| MaixCAM2 `/root/models/sensevoice-maixcam2` | SenseVoice 权重和运行支撑 | 支撑文件复制到 `model/maixcam2/`；权重外置 |
| MaixCAM Pro `/root/models/am_3332_192_int8.mud` | 一代 KWS 权重/描述 | 未复制；仅记录 |

清理前目标目录所在文件系统在当前会话中是只读挂载，未能生成额外本地备份；旧版本仍可通过远端 Git 历史和一代 MaixCAM Pro 设备追溯。

## 2. 新结构

```text
EnlightenJLU/
├── README.md
├── .gitignore
├── docs/ASSET_INVENTORY.md
├── model/
├── maixcam/
│   ├── pro/
│   └── maixcam2/
└── stm32/
```

## 3. MaixCAM Pro（一代）

来源：`EnlightenJLU/surplife/app`  
目标：`maixcam/pro/app/`

| 文件 | 作用 |
|---|---|
| `voice_pwm.py` | Maix-Speech KWS、单字/整词门控、A18/PWM6 + A19/PWM7 1 kHz 灯效 |
| `live_kws.py` | UI 专用 KWS/音量事件发布 |
| `lamp_ui.py` | 640×480 触摸灯效测试 UI |
| `sg2002_temp.py` | SG2002 温度读取 |
| `asoundrc.surplife` | ALSA file 插件麦克风分流 |
| `run_voice_pwm.sh` / `start_voice_pwm.sh` / `stop_voice_pwm.sh` / `status_voice_pwm.sh` | 运行和后台管理 |
| `run_lamp_ui.sh` | UI 启动，暂停/恢复后台语音 |
| `README_pwm.md` | KWS、门限、灯效曲线、接线 |
| `README_lamp_ui.md` | UI 操作、触摸方向、资源优先级 |
| `README_TEMP_SENSOR.md` | 温度寄存器和换算 |
| `tests/test_voice_pwm.py` | 门控/评分测试 |
| `tests/test_sg2002_temp.py` | 温度换算测试 |
| `VERSION` | 一代业务版本 `0.3.0` |

规模：

```text
voice_pwm.py    1534 行
live_kws.py      258 行
lamp_ui.py      2375 行
sg2002_temp.py   166 行
```

板端运行路径保持：

```text
/root/surplife/app
/root/surplife/run
/root/surplife/logs
/root/surplife/artifacts
```

模型：

```text
/root/models/am_3332_192_int8.mud
```

KWS 词表：

```text
chang1 chang2 chang4
chun1 chun2 chun3
ang1 ang2
chang2 chun1
```

## 4. MaixCAM2（二代）

来源：`PWM-Heater/maixcam2_app`  
目标：`maixcam/maixcam2/`

| 文件/目录 | 作用 |
|---|---|
| `app/main.py` | SenseVoice、关键词匹配、VAD、SPI 发布、本地 PWM 调度 |
| `app/keyword_matcher.py` | “长/春/长春”字符族和整词匹配 |
| `app/local_pwm.py` | A30/PWM6 2 kHz 本地表演状态机 |
| `app/stm32_protocol.py` | SPI v1 帧/TLV/CRC 参考实现 |
| `app/maixcam_spi_link.py` | SPI2/CS1 主机传输 |
| `app/test_keyword_matcher.py` | 关键词匹配单元测试 |
| `config/keywords.json` | 注册词、`glyph_mask=3`、保持 1.2 s |
| `config/sensevoice.mud` | 外部 SenseVoice 描述符 |
| `audio_ui/app/mic_ui.py` | 640×480 麦克风电平/波形/频谱 UI |
| `audio_ui/run_mic_ui.sh` | host/launcher 切换和 UI 启动 |
| `audio_ui/preview.png` | UI 预览 |
| `usb_audio/enable_usb_mic.sh` | USB host + `snd-usb-audio` |
| `usb_audio/disable_usb_mic.sh` | 恢复 device/gadget |
| `usb_audio/record_usb_mic.sh` | USB 麦克风录音和 RMS/峰值 |
| `bench/REPORT.md` | 13 字标语 SenseVoice 评测 |
| `bench/USB_MIC_TEST.md` | USB Audio 测试记录 |
| `run_voice.sh` / `start.sh` / `stop.sh` | 运行和后台管理 |
| `start_usb_local.sh` | USB 麦克风 + 临时“长春” + A30/PWM6 |
| `README.md` | 二代运行说明 |

核心代码规模：

```text
app/main.py                    441 行
app/local_pwm.py               227 行
app/stm32_protocol.py          232 行
app/maixcam_spi_link.py        160 行
audio_ui/app/mic_ui.py         850 行
```

板端运行路径保持：

```text
/root/JLU_LEDLAB
```

模型：

```text
/root/models/sensevoice-maixcam2/
```

## 5. 模型

### 已纳入仓库的 MaixCAM2 支撑

目录：`model/maixcam2/sensevoice-maixcam2/`

| 文件 | 大小 |
|---|---:|
| `SenseVoiceAx.py` | 23,098 B |
| `am.mvn` | 11,203 B |
| `chn_jpn_yue_eng_ko_spectok.bpe.model` | 377,341 B |
| `client.py` | 11,254 B |
| `embeddings.npy` | 25,523 B |
| `frontend.py` | 17,726 B |
| `model.mud` | 317 B |
| `pe_nonstream.npy` | 573,568 B |
| `pe_streaming.npy` | 58,368 B |
| `server.py` | 11,282 B |
| `tokenizer.py` | 4,810 B |

完整 SHA256 见 `model/manifest.json`。

### 外置权重

| 平台 | 文件 | 大小 | SHA256 |
|---|---|---:|---|
| MaixCAM2 | `sensevoice.axmodel` | 256,550,253 B | `67d290cf7cebf45db5f37b2e93b8bdfff44dc35110bb29d84204a5f9eae9fd4d` |
| MaixCAM2 | `streaming_sensevoice.axmodel` | 249,023,211 B | `ba1ddd60841297903bfdae059ad88092d0fd1c543e1d80d7f64199d4e27b8263` |
| MaixCAM Pro | `am_3332_192_int8.mud` + 配套 | 未获取 | 未获取 |

`model/**/*.axmodel` 等权重已在 `.gitignore` 中排除。

## 6. STM32

来源：`/home/jlu/桌面/CubeMX/C8T6/PWM-Heater`  
目标：`stm32/`

纳入：

- `Core/Inc`、`Core/Src`；
- `Drivers/`；
- `cmake/`、`CMakeLists.txt`、`CMakePresets.json`；
- `PWM-Heater.ioc`、`.mxproject`；
- `STM32F103xx_FLASH.ld`、`startup_stm32f103xb.s`；
- `docs/SPI_PROTOCOL.md`、`docs/BUILD.md`、`docs/HARDWARE.md`；
- `tools/`；
- `firmware/PWM-Heater.hex`、`.bin`。

排除：

- `build/`；
- `maixcam2_app/`；
- 临时原理图裁剪图片。

文件规模：

```text
946 个文件，约 69 MB（主要 Drivers/CMSIS/HAL）
```

已验证固件：

```text
PWM-Heater.bin   16,576 B
SHA256 4dd2531314719912d362bdd68c30d4070f1af02e951cdb218111c1f67ebab609
```

行为：

- 15 路 PWM 上电全部 0；
- HEAT1/HEAT2 固定 0%；
- 无 SPI HELLO 时全关；
- 500 ms 超时全关；
- 温度只接收并回显，不做 PID。

## 7. 明确移除的旧内容

- `surplife/archive/` 全部历史副本；
- `surplife/pwm.log`、`server.log`、`voice.log`、`logs/`；
- `surplife/artifacts/` 截图和 KWS 输出；
- `surplife/app/main.py`、`ble_client.py`、`protocol.py`、`static/` 等 BLE/HTTP 窗帘控制；
- `config/` 主机端语音关键词记录器；
- `light-dots/`；
- 旧 `maixcam/` YOLO11 姿态示例；
- `__pycache__/`、`.pyc`、PID/FIFO/WAV；
- 旧模型副本和本地构建产物。

原版本可从一代 Pro 的 `/root/surplife/app` 和远端 Git 历史追溯。

## 8. 验证记录

- Python `py_compile`：通过；
- Shell `sh -n`：通过；
- Pro 单元测试：19 项通过；
- MaixCAM2 关键词测试：6 项通过；
- STM32 协议测试：6 项通过；
- STM32 固件已烧录并读回 SHA256 校验；
- TIM2/TIM4 CEN 已置位、CCR 全 0；
- 完整 15 路灯牌 SPI 联调仍待现场完成。
