# MaixCAM Pro（一代）生产代码

本目录是原 `/root/surplife/app` 中与语音灯牌 PWM 相关的清理版；BLE/HTTP 窗帘、archive、日志、截图和运行备份未迁入。原版本仍在一代 Pro 和远端 Git 历史中。

## 部署

```text
仓库 maixcam/pro/app/  →  设备 /root/surplife/app/
```

```sh
cp -a maixcam/pro/app/. /root/surplife/app/
mkdir -p /root/surplife/run /root/surplife/logs /root/surplife/artifacts
```

模型：

```text
/root/models/am_3332_192_int8.mud
```

## 业务文件

| 文件 | 作用 |
|---|---|
| `app/voice_pwm.py` | KWS、单字/整词门控、A18/PWM6 + A19/PWM7 1 kHz 灯效 |
| `app/live_kws.py` | UI 专用 KWS/音量事件发布 |
| `app/lamp_ui.py` | 640×480 触摸灯效测试 UI |
| `app/sg2002_temp.py` | SG2002 温度读取 |
| `app/asoundrc.surplife` | 麦克风分流 ALSA 配置 |
| `app/run_voice_pwm.sh` | 前台入口 |
| `app/start_voice_pwm.sh` / `stop_voice_pwm.sh` / `status_voice_pwm.sh` | 后台管理 |
| `app/run_lamp_ui.sh` | UI 启动，暂停/恢复后台语音 |
| `app/README_pwm.md` | KWS、门限、灯效曲线、接线 |
| `app/README_lamp_ui.md` | UI 操作和触摸方向 |
| `app/README_TEMP_SENSOR.md` | 温度寄存器和换算 |
| `app/tests/test_voice_pwm.py` | 门控/评分测试 |
| `app/tests/test_sg2002_temp.py` | 温度换算测试 |

## 运行

```sh
cd /root/surplife/app
./run_voice_pwm.sh
```

后台：

```sh
./start_voice_pwm.sh
./status_voice_pwm.sh
./stop_voice_pwm.sh
```

触摸 UI：

```sh
./run_lamp_ui.sh
```

128 MB 板子上 UI 和后台语音不要同时长期运行。

## 一代 KWS 词表

```text
chang1 chang2 chang4
chun1 chun2 chun3
ang1 ang2
chang2 chun1
```

`ang` 仅调试；单字拼装和整词规则见 `app/README_pwm.md`。

## 测试

```sh
cd maixcam/pro/app
python3 -m unittest -v tests/test_voice_pwm.py tests/test_sg2002_temp.py
```

真机 KWS/PWM 仍需在 Pro 上验证。
