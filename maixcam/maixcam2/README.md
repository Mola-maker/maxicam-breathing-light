> **仓库位置**：`maixcam/maixcam2/`；板端部署路径仍为 `/root/JLU_LEDLAB/`。模型描述和支持代码见 `model/maixcam2/`，执行器见 `stm32/`。

# JLU_LEDLAB MaixCAM2 application

Runtime location: `/root/JLU_LEDLAB`

The SenseVoice model is **not copied** into this directory. The application
uses the system model directory:

```text
/root/models/sensevoice-maixcam2/
```

`config/sensevoice.mud` is a small local descriptor that points at the external
`sensevoice.axmodel`, `streaming_sensevoice.axmodel`, and `server.py`.

## Directory layout

```text
/root/JLU_LEDLAB/
  app/
    main.py                 voice recognition + board business
    keyword_matcher.py      legacy keyword matching
    stm32_protocol.py       SPI v1 frame/TLV implementation
    maixcam_spi_link.py     MaixCAM2 SPI2/CS1 master transport
    test_keyword_matcher.py
  config/
    sensevoice.mud          external-model descriptor
    keywords.json           registered phrase/character families
  logs/
  run/
  run_voice.sh
  start.sh
  stop.sh
```

## Registered legacy vocabulary

| Legacy pinyin | SenseVoice family | Chinese aliases |
|---|---|---|
| chang1 / chang2 / chang4 | chang | 长 常 场 厂 唱 昌 畅 尝 肠 偿 敞 倡 |
| chun1 / chun2 / chun3 | chun | 春 纯 唇 醇 淳 蠢 椿 鹑 |
| ang1 / ang2 | ang | 昂 肮 盎 |
| chang2 chun1 | phrase | 长春 / 长 春 |

SenseVoice returns Chinese text without tone labels, so tone variants are kept
as registered metadata but matching is done by the character family.  `ang` is
still debug-only and does not open the gate. A single `chang` or `chun` is
logged but does not gate; `长春` or `chang + chun` opens the gate.

## Run

```sh
cd /root/JLU_LEDLAB
./run_voice.sh                 # microphone -> SenseVoice -> STM32 SPI
./run_voice.sh --no-spi        # voice only, no board
./run_voice.sh --wav /tmp/changchun.wav --no-spi
./run_voice.sh --local-pwm       # temporary local A30/PWM6 performance
./run_voice.sh --local-pwm --wav /root/JLU_LEDLAB/bench/audio/slogan13_slow.wav
./run_voice.sh --local-pwm --usb-mic   # after usb_audio/enable_usb_mic.sh
./run_voice.sh --local-pwm --usb-mic --voice-rms 0.003  # low-level USB mic
./run_voice.sh --list-keywords
```

Background:

```sh
./start.sh
./stop.sh
tail -f logs/voice.log
```

## STM32 link

MaixCAM2 uses:

- SPI2
- SCK B20
- MISO B19
- CS B21
- MOSI B18
- `/dev/spidev2.1`

The STM32 receives `HELLO`, `TEMP`, `PERFORM`, and `HEARTBEAT` according to
`docs/SPI_PROTOCOL.md` in the STM32 project.

On a recognized `长春` phrase the app sends:

```text
PERFORM GATE, glyph_mask=0x3
```

and schedules a `RELEASE` after the configured demo hold time.

## Local A30 / PWM6 fallback

`--local-pwm` temporarily configures A30 as PWM6 (2 kHz) and runs the same
standby breathing / GATE / HOLD / RELEASE / EGG state machine used by the STM32.
The pin is restored to UART1_TX by the test scripts after shutdown; starting
the app again reconfigures it.

External USB microphone status and the installed USB Audio Class modules are
documented in `bench/USB_MIC_TEST.md` and `usb_audio/README.md`.

To use the USB microphone with this app:

```sh
cd /root/JLU_LEDLAB/usb_audio
./enable_usb_mic.sh
cd /root/JLU_LEDLAB
./run_voice.sh --local-pwm --usb-mic
# when finished:
/root/JLU_LEDLAB/usb_audio/disable_usb_mic.sh
```

## USB microphone visualizer

`audio_ui/` contains a standalone 640 × 480 UI for the external USB
microphone. It shows the input level in dBFS, a peak-hold meter, a 140 ms
waveform, and a 24-band spectrum (60 Hz–8 kHz).

```sh
cd /root/JLU_LEDLAB/audio_ui
./run_mic_ui.sh
```

The launcher is stopped while the UI owns the display and restarted on exit.
If the USB port was in device mode, it is restored to device/gadget mode after
the UI exits. See `audio_ui/README.md` for options and troubleshooting.


## 临时“长春”语音 + A30/PWM6 灯效

当前临时联调业务使用：

```text
USB 外接麦克风
  -> SenseVoice 中文非流式识别
  -> 匹配“长春”/“长”+“春”
  -> A30 / PWM6 本地灯效
```

启动：

```sh
cd /root/JLU_LEDLAB
./start_usb_local.sh
```

`start_usb_local.sh` 会检查 USB Audio；如果不存在，会先调用
`usb_audio/enable_usb_mic.sh` 将 USB-C 切到 host 并加载 `snd-usb-audio`，
然后执行：

```sh
./start.sh --usb-mic --local-pwm \
  --pwm-pin A30 --pwm-id 6 --pwm-freq 2000
```

停止：

```sh
cd /root/JLU_LEDLAB
./stop.sh
```

日志：

```text
/root/JLU_LEDLAB/logs/voice.log
```

当前本地灯效只使用 **A30 / PWM6，2 kHz** 这一路；STM32 板上的 15 路
PWM 灯牌尚未接回联调。因此识别到“长春”时，逻辑上的
`glyph_mask=0x3` 会同时代表“长”和“春”，但本地物理上只有 A30 这一路
在表演。

### 当前语音识别范围

SenseVoice 使用 `/root/models/sensevoice-maixcam2/` 下的外部模型，配置
中的 hot words 为：

```text
长, 春, 昂, 长春
```

注册的触发词：

| 类型 | 内容 | 是否触发灯效 |
|---|---|---|
| 整词 | 长春、长 春 | 是，GATE `mask=0x3` |
| 字族 chang | 长、常、场、厂、唱、昌、畅、尝、肠、偿、敞、倡 | 单个字只记录，不触发 |
| 字族 chun | 春、纯、唇、醇、淳、蠢、椿、鹑 | 单个字只记录，不触发 |
| 字族 ang | 昂、肮、盎 | 仅调试记录，不触发 |
| 组合 | 同一次 ASR 同时出现 chang 和 chun | 是，GATE `mask=0x3` |

音调标签 `chang1/chang2/chang4`、`chun1/chun2/chun3`、`ang1/ang2`
仍保留在配置中作为兼容元数据，但 SenseVoice 返回的是无音调中文文本，
实际匹配按汉字别名进行。

### 当前灯效状态机

| 状态 | 效果 |
|---|---|
| `STANDBY` | 待机呼吸，占空比 1%–8%，4 秒一个周期 |
| `INTRO` | 触发后 30 ms 平滑升到 100% |
| `HOLD` | 保持 100%，当前 `hold_seconds=1.2` |
| `RELEASE` | 2.5 秒渐弱：0.5 s 到 50%，1.3 s 到 35%，2.5 s 到 8%，然后回待机 |
| `EGG` | 1.6 秒 5 Hz 亮灭，再熄灭 2.0 秒；状态机已实现，当前语音配置未触发 |
| `OFF` | 占空比 0%，应用退出时会发送 OFF |

PWM 频率为 2 kHz，周期 500,000 ns；待机时占空比约 5,000–40,000 ns。
`stop.sh` 会停止识别、关闭 PWM，并把 A30 恢复为 `UART1_TX`。

USB 麦克风语音模式和 `audio_ui` 的可视化 UI 不能同时运行，因为二者都要
独占 USB capture 设备。先停止 UI，再启动语音业务：

```sh
kill -TERM $(pgrep -f 'python3 -u app/mic_ui.py' | head -1)
cd /root/JLU_LEDLAB
./start_usb_local.sh
```

语音业务停止后，如果需要恢复 USB device/gadget：

```sh
/root/JLU_LEDLAB/usb_audio/disable_usb_mic.sh
```
