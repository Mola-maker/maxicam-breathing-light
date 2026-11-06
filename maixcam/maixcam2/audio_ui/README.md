# MaixCAM2 外接麦克风实时可视化 UI

这是一个运行在 MaixCAM2 本机屏幕上的 USB 麦克风实时监测界面：

- 640 × 480 横屏 UI；
- USB Audio 外接麦克风，经 USB Hub 连接；
- 实时输入电平、峰值保持、dBFS 数值；
- 140 ms 波形；
- 24 段频谱（60 Hz – 8 kHz）；
- 估算主频；
- `LIVE/WAIT` 状态、设备名、采样率、FPS；
- 触摸底部“退出”按钮或按 `Ctrl-C` 退出。

目录：

```text
audio_ui/
├── app/mic_ui.py         主程序
├── run_mic_ui.sh         启动脚本（自动处理 USB host 和 launcher）
├── preview.png           UI 预览图
└── README.md
```

## 1. 运行

```sh
cd /root/JLU_LEDLAB/audio_ui
./run_mic_ui.sh
```

脚本会：

1. 如果当前没有 USB Audio capture card，调用
   `/root/JLU_LEDLAB/usb_audio/enable_usb_mic.sh`，切换 USB-C 为 host
   模式并加载 `snd-usb-audio`；
2. 停止 `launcher.service`，让 UI 独占屏幕；
3. 启动 `app/mic_ui.py`；
4. 退出时恢复 `launcher.service`；
5. 如果启动前 USB 角色是 `device`，退出时切回 `device` 并重启
   `usb-gadget.service`。

如果要让 USB 麦克风在 UI 退出后继续保持 host 模式：

```sh
MIC_UI_KEEP_USB_HOST=1 ./run_mic_ui.sh
```

如果要强制在退出时恢复 device 模式：

```sh
MIC_UI_RESTORE_USB=1 ./run_mic_ui.sh
```

## 2. 常用参数

```sh
# 指定 ALSA 设备，跳过自动检测
./run_mic_ui.sh --device plughw:1,0

# 16 kHz，20 ms 一帧，30 FPS
./run_mic_ui.sh --rate 16000 --chunk-ms 20 --fps 30

# 运行 10 秒后自动退出
./run_mic_ui.sh --duration 10

# 不开屏幕，只跑音频和渲染，用于测试
./run_mic_ui.sh --headless --duration 5

# 保存一帧 PNG（可用于检查布局）
./run_mic_ui.sh --headless --duration 5 \
  --screenshot /tmp/mic_ui.png --screenshot-after 3
```

参数说明：

| 参数 | 说明 |
|---|---|
| `--device plughw:N,M` | 指定 ALSA capture 设备；不填则自动找 USB Audio |
| `--rate` | 采样率，默认 16000 |
| `--chunk-ms` | 每次读取的音频块长度，默认 20 ms |
| `--fps` | UI 目标帧率，默认 30 |
| `--duration` | 运行秒数；0 表示一直运行 |
| `--headless` | 不打开 display，适合 SSH 测试 |
| `--screenshot` | 渲染帧保存路径 |
| `--screenshot-after` | 启动后多少秒保存截图，默认 2 秒 |

## 3. 音频链路

MaixPy 的 `maix.audio.Recorder` 默认使用板载声卡（card 0，
`Axera Audio`），不会自动选中 USB 麦克风。本程序因此使用：

```text
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -t raw
```

读取原始 PCM，再由 Python/NumPy 计算 RMS、峰值和 FFT。这样即使 USB
声卡的 card 编号变化，也能通过 `arecord -l` 自动重新定位。

当前实测设备：

```text
Bus 001 Device 003: ID 08bb:2902 Texas Instruments PCM2902 Audio Codec
Bus 001 Device 002: ID 05e3:0610 Genesys Logic, Inc. Hub
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
```

## 4. 显示与触摸

MaixCAM2 的屏幕由 `launcher.service` 占用。直接运行 MaixPy display
会出现：

```text
SAMPLE_COMM_VO_StartDev failed
```

所以不要绕过 `run_mic_ui.sh` 直接运行 `python3 app/mic_ui.py`（除非你
自己已经停止 launcher）。屏幕逻辑分辨率为 **640 × 480**；如果使用
480 × 640 的竖屏图像，会被缩放并出现黑边。

退出方式：

- 点击右下角“退出”；
- 触摸底部状态栏区域；
- SSH 终端按 `Ctrl-C`。

## 5. 已验证结果

2026-11 在 MaixCAM2 + Genesys USB Hub + PCM2902 上实测：

- `arecord -l` 正确出现 `card 1: USB PnP Sound Device`；
- 16 kHz 单声道采集正常；
- 640 × 480 UI 实际运行约 **29.9 FPS**；
- 电平、波形、频谱均随环境声音变化；
- 退出后 `launcher.service` 能恢复；
- 通过 `MIC_UI_RESTORE_USB=1` 或启动前为 device 模式时，可恢复
  `usb-gadget.service`。

预览图见 `preview.png`。

## 6. 故障排查

### 没有 USB 麦克风

```sh
lsusb
arecord -l
cat /sys/class/usb_role/8000000.dwc3-role-switch/role
lsmod | grep snd_usb
```

应为：

```text
host
snd_usb_audio
card 1: ... USB Audio ...
```

如果没有：

```sh
cd /root/JLU_LEDLAB/usb_audio
./enable_usb_mic.sh
```

### 录音电平很低

PCM2902/CM108 类设备默认 capture volume 可能为 0：

```sh
amixer -c 1 cset numid=3 16
amixer -c 1 cset numid=4 on
```

### 屏幕没有图像或报 VO 错误

确认是通过 `run_mic_ui.sh` 启动，并且 `launcher.service` 已停止：

```sh
systemctl status launcher.service
```

### 退出后 USB 网络/设备模式不可用

```sh
cd /root/JLU_LEDLAB/usb_audio
./disable_usb_mic.sh
```

或者启动 UI 时使用：

```sh
MIC_UI_RESTORE_USB=1 ./run_mic_ui.sh
```
