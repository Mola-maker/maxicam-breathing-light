# LUMEN / 1k — MaixCAM Pro 灯效测试 UI

640×480 触摸测试台。它不跑 KWS，也不改变已部署的 `voice_pwm.py` 逻辑；
它用于手动注入“长春”门控、模拟人声、观察衰减/呼吸/时间线，并在需要时
独占 A18/PWM6、A19/PWM7 输出 1 kHz 灯效。

## 启动

```sh
cd /root/surplife/app
./run_lamp_ui.sh
```

`run_lamp_ui.sh` 会先暂停后台语音，测试结束后自动恢复；如果直接运行
`python3 lamp_ui.py`，UI 也会在检测到后台语音时询问是否暂停，并在退出时
自动恢复。

只生成三张预览图：

```sh
python3 lamp_ui.py --preview
```

自动演示 + 截图（用于回归检查）：

```sh
python3 lamp_ui.py --seconds 8 --auto-demo --snapshot /root/surplife/artifacts/lamp_ui_live.png
```

## 操作

- **灯效页**：按住“长春”= 持续人声；点按 ≈ 1 秒语音后自动释放。
- **自动演示**：16 秒循环，两次门控，覆盖待机/唤醒/释放。
- **强制待机**：立即停止业务并回到呼吸。
- **调参页**：阈值、有人声衰减、释放衰减、tick 均可调；
  `柔和 / 灵敏 / 默认` 一键套用。
- **硬件输出**：默认 SIM（只模拟）。点击“开启输出”后由本 UI 独占
  A18/A19；若后台语音仍在运行会先询问是否停止接管。
- 右上角 `SIM/HW` 显示当前输出模式；状态灯显示
  待机 / 已唤醒 / 语音中 / 释放。

## 与后台语音的关系

MaixCAM 只有 128 MB 内存。后台 `voice_pwm.py` 运行时会占掉大部分内存，
UI 的字体和缓存渲染会严重变慢，所以正常启动请使用 `run_lamp_ui.sh`，
或接受启动时的暂停提示。退出 UI 时会自动重启后台语音。

真实 KWS、ALSA 麦克风与生产衰减仍然由 `voice_pwm.py` 负责；本 UI 中的
“长春”按钮是门控模拟，不是语音识别结果。

## 触摸方向

先运行坐标检查：

```sh
python3 lamp_ui.py --touch-test
```

点按屏幕，琥珀色圆点应落在手指下；同时会打印 `read` 与 `raw0` 坐标。
默认按 MaixCAM 的 640×480 横屏坐标读取触摸。如果实际设备触摸方向不一致，
可在启动前设置：

```sh
LAMP_UI_TOUCH_SWAP=1
LAMP_UI_TOUCH_FLIP_X=1
LAMP_UI_TOUCH_FLIP_Y=1
```

## 部署路径

- 业务代码：`/root/surplife/app/`
- 运行时 FIFO/PID：`/root/surplife/run/`
- 日志：`/root/surplife/logs/`
- 预览图：`/root/surplife/artifacts/`
- 预览图文件：`lamp_ui_bench.png`、`lamp_ui_tune.png`、`lamp_ui_modal.png`

## 资源优先级

UI 会主动降低自己的优先级，避免和后台语音模型争抢资源：

- `lamp_ui.py`：`nice 5`，`oom_score_adj 500`；
- `live_kws.py` 子进程：重新提升为 `nice -10`、`oom_score_adj -800`；
- 可调环境变量：`LAMP_UI_NICE`、`LAMP_UI_OOM_SCORE_ADJ`。

注意：128 MB 板子上 UI 和后台 `voice_pwm.py` 仍不建议长期同时运行；
UI 启动脚本会先暂停后台语音，退出后再恢复。
