# surplife 项目目录

本目录是 MaixCAM 上的完整项目根目录，业务代码、基础依赖和运行时文件都放在这里。

| 路径 | 用途 |
| --- | --- |
| `app/` | 业务代码：语音 KWS、PWM 灯控、触摸 UI、BLE/HTTP、测试 |
| `lib/` | 基础 Python 依赖（FastAPI、uvicorn、bleak、dbus 等） |
| `wheels/` | 离线安装包 |
| `run/` | 运行时 FIFO、PID（麦克风分流、UI KWS） |
| `logs/` | 运行日志（UI KWS、归档日志） |
| `artifacts/` | 预览图、KWS 测试数据 |
| `archive/` | 迁移前备份和历史代码，不参与运行 |

> 生产进程的 `pwm.pid` / `pwm.log` 保留在项目根目录，兼容现有
> `start_voice_pwm.sh` / `stop_voice_pwm.sh` / `status_voice_pwm.sh`；
> UI 的 KWS FIFO、PID 和日志分别使用 `run/`、`logs/`。

## 语音链路

```text
麦克风 hw:0,0
  └─ ALSA file 插件 pwm_mic
       └─ /root/surplife/run/surplife_pwm_mic.pcm
            ├─ Maix-Speech KWS（voice_pwm.py）
            └─ 音量 DSP 子进程
```

- 生产入口：`app/start_voice_pwm.sh` → `app/run_voice_pwm.sh` → `app/voice_pwm.py`
- 停止：`app/stop_voice_pwm.sh`
- 状态：`app/status_voice_pwm.sh`
- UI 入口：`app/run_lamp_ui.sh` → `app/lamp_ui.py`，UI 的 KWS 为 `app/live_kws.py`
- ASR 模型：`/root/models/am_3332_192_int8.mud`（模型文件不放在项目内）
- ALSA 配置：`/root/.asoundrc`，项目内保留完整副本 `app/asoundrc.surplife`

生产语音和 UI 不要同时长期运行；128 MB 内存下两者会争抢资源。

## 资源优先级

- 生产语音 `voice_pwm.py`：`nice -10`，`oom_score_adj -800`
- UI `lamp_ui.py`：`nice 5`，`oom_score_adj 500`
- UI 的 `live_kws.py` 子进程会重新提升为语音优先级，避免 UI 内存压力大时先杀掉 KWS
- 可调环境变量：`VOICE_NICE`、`VOICE_OOM_SCORE_ADJ`、`LAMP_UI_NICE`、`LAMP_UI_OOM_SCORE_ADJ`
