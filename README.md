# maxicam-breathing-light

MaixCAM 语音门控呼吸灯项目，以及相关的参考代码、协议笔记和日志工具。

> 仓库名保留 `maxicam`；正文中的硬件名称是 **MaixCAM**。

## 目录

| 目录 | 内容 |
| --- | --- |
| `surplife/` | MaixCAM 上的完整项目快照：语音 KWS、PWM 呼吸灯、触摸 UI、BLE/HTTP、测试、历史版本、截图和文本日志 |
| `maixcam/` | MaixCAM-Pro YOLO11 姿态识别参考示例 |
| `config/` | 主机端“语音关键词记录器”：通过 SSH 读取板子 `pwm.log` |
| `light-dots/` | Surplife 20x20 LED 窗帘 BLE 协议笔记、俄罗斯方块、相机参考 |

## 说明

- `surplife/` 主体是 2026-10-25 主机端快照；其中 `app/voice_pwm.py` 已在 2026-10-28 同步到板端 **v0.3.0**（PWM 载波改为 1 kHz；语音、灯效和 10s 肺活量彩蛋沿用 v0.2.7）。v0.2.7 原文件放在 `surplife/archive/voice_pwm.py.v027`，v0.2.5 原文件放在 `surplife/archive/voice_pwm.py.v025`。
- 板子上的模型文件不在仓库内；运行时从 `/root/models/am_3332_192_int8.mud` 加载 KWS 模型，对应的 `.cvimodel` 也未放入仓库。
- 为控制仓库体积和避免公开运行录音，已排除：
  - `lib/`、`wheels/` 依赖目录
  - `__pycache__/`、`*.pyc`
  - `*.pcm`、`*.pid`、`*.lock`
  - `run/` 下的 `*.wav`、`*.mp3` 测试音频
- 文本日志、截图、历史代码和协议笔记保留在仓库中。
- 公开仓库，不要提交 token、密码、私钥或包含个人语音的录音。

## 生产入口

```sh
cd surplife/app
./start_voice_pwm.sh
./status_voice_pwm.sh
./stop_voice_pwm.sh
```

关键说明见：

- [`surplife/README.md`](surplife/README.md)
- [`surplife/app/README_pwm.md`](surplife/app/README_pwm.md)
- [`surplife/app/README_lamp_ui.md`](surplife/app/README_lamp_ui.md)
- [`maixcam/README.md`](maixcam/README.md)
- [`light-dots/PROTOCOL.md`](light-dots/PROTOCOL.md)
- [`config/README_voice_keyword_logger.txt`](config/README_voice_keyword_logger.txt)

## 参考链接

- [Sipeed MaixPy](https://github.com/sipeed/MaixPy)
- [MaixCAM 人体关键点检测](https://wiki.sipeed.com/maixpy/doc/zh/vision/body_key_points.html)
- [MaixCAM 人体姿态分类器](https://wiki.sipeed.com/maixpy/doc/zh/vision/body_pose_classification.html)
- [ge0rg/surplife-curtain](https://codeberg.org/ge0rg/surplife-curtain)
- [marcelrv gist: Surplife 协议分析](https://gist.github.com/marcelrv/36f9d2c66a273289211cc5fa73b00018)

## 许可

本仓库是个人项目与参考资料集合。第三方代码、文档和示例遵循它们各自的许可证；使用前请核对原项目许可。
