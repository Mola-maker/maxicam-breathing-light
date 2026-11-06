# MaixCAM 业务代码

两代 MaixCAM 都负责音频、语音判断和高层表演决策；STM32 负责最终 15 路灯牌 PWM。

| 项目 | MaixCAM Pro（一代） | MaixCAM2（二代） |
|---|---|---|
| SoC | SG2002，约 128 MB | AX620E/AX630C，约 1 GB |
| 语音 | Maix-Speech KWS | SenseVoice ASR |
| 模型 | `/root/models/am_3332_192_int8.mud` | `/root/models/sensevoice-maixcam2/` |
| 本地灯控 | A18/PWM6、A19/PWM7，1 kHz | A30/PWM6，2 kHz 临时联调 |
| STM32 链路 | 参考 SPI 主机 | SPI2/CS1，B18/B19/B20/B21 |
| 运行目录 | `/root/surplife/app` | `/root/JLU_LEDLAB` |
| 入口 | `voice_pwm.py` | `app/main.py` |

```text
麦克风 → MaixCAM KWS/ASR → 高层 PERFORM/TEMP/HEARTBEAT → STM32 → 15 PWM
```

## 目录

```text
maixcam/
├── pro/
│   ├── VERSION
│   ├── README.md
│   └── app/                 # voice_pwm.py, live_kws.py, lamp_ui.py, temp, scripts, tests
└── maixcam2/
    ├── app/                 # SenseVoice + SPI + local PWM
    ├── config/              # keywords + SenseVoice descriptor
    ├── audio_ui/            # USB mic visualizer
    ├── usb_audio/           # snd-usb-audio scripts
    ├── bench/               # recognition/USB tests
    └── run/start/stop scripts
```

## 规范

- MaixCAM 不生成 STM32 的 15 路波形；只发送 `glyph_mask` 和动作；
- 一代 Pro 的 A18/A19、二代 MaixCAM2 的 A30/PWM6 都是本地回退；
- 模型权重不进入业务目录；
- 同一块板的语音业务和麦克风 UI 不能同时占用麦克风；
- 绝对路径是板端运行路径，不是仓库路径。
