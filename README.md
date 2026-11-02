# maxicam-breathing-light

MaixCAM 语音门控呼吸灯项目，以及相关的参考代码、协议笔记和日志工具。

> 仓库名保留 `maxicam`；正文中的硬件名称是 **MaixCAM**。

## 交接：MaixCAM 作为 STM32 上位机

> **先看这一节。** 当前是 `main` / v0.3.0 + SG2002 只读温度读取的基线。
> **SPI 通信、温度上报、15 路 PWM 控制尚未实现**；现有 `voice_pwm.py` 仍然直接
> 驱动 MaixCAM 本地的 A18/A19 两路 PWM。不要把本仓库当成已经完成的 STM32
> 集成工程。

### 目标架构

```text
麦克风 ──> MaixCAM（KWS / 语音判断 / 智能决策） ──SPI──> STM32（15 路 PWM / 功率级）
                    │
                    └── SG2002 片上温度读取 ───────────────┘
```

- **MaixCAM = 上位/主控**：负责音频、语音识别、语音门控与决策、SoC 温度读取和
  对外状态上报；建议作为 SPI 主机。
- **STM32 = 从机/执行器**（建议；SPI 主从以实际硬件为准）：负责 15 路 PWM 的
  时序、频率、占空比、输出使能、故障安全和功率级；不运行语音识别。
- MaixCAM **不直接产生 15 路 PWM**。现有 A18/A19 是旧的两路本地灯控；接入
  STM32 后应停止或旁路，避免两边同时驱动灯/负载。
- “15 路 PWM”的通道映射、频率、极性、死区、电流驱动和故障状态**没有在本仓库
  定义**，需要和 STM32 侧共同确定。

### MaixCAM 的职责边界

| 职责 | 交接内容 | 当前状态 |
| --- | --- | --- |
| 音频采集 | ALSA 麦克风 `hw:0,0`，经 FIFO 分发给 KWS 和音量 DSP | 已实现 |
| 语音 KWS | Maix-Speech，模型 `/root/models/am_3332_192_int8.mud`；单字 + 整词 `chang2 chun1` | 已实现；模型不在仓库 |
| 语音判断 | 单字/整词/长前导门控，默认门限 `0.35/0.30/0.10`，序列窗口默认 `0` | 已实现 |
| 本地灯效 | 呼吸、业务斜坡、10s 肺活量彩蛋；当前驱动 A18/PWM6、A19/PWM7 | 已实现，属旧执行路径 |
| 温度读取 | 只读 `/sys/class/thermal/thermal_zone0/temp`；`sg2002_temp.py` 提供 `sample()`/`read_sysfs_mc()` | 已实现，尚未接入 `voice_pwm.py` |
| 温度上报 | 通过 SPI 定期上报 MaixCAM/SG2002 结温，建议整数 `temp_mc`、≤1 Hz | **未实现** |
| 语音结果下发 | 把门控/亮度/模式/彩蛋等决策编码成 SPI 命令发给 STM32 | **未实现** |
| SPI 主机 | 建议 MaixCAM 作 SPI 主机；负责帧同步、序号、CRC、重试和链路健康 | **未实现** |
| 失效安全 | SPI 断链、STM32 无响应时停止/回到安全灯效，并上报错误 | **未实现** |
| 15 路 PWM | 由 STM32 执行；MaixCAM 只发高层命令，不生成 15 路波形 | STM32 侧，未在本仓库 |

### 现有代码的关键集成点

`surplife/app/voice_pwm.py` 当前是多进程结构：

```text
KWS 主进程 ──Pipe──> 判断进程 ──gate_seq/egg_seq/egg_active──> _pwm_worker
                                                               └─> A18/A19 sysfs
```

- 判断进程已经算出“是否开门、彩蛋是否触发”等结果，但结果只写入共享的
  `gate_seq` / `egg_seq` / `egg_active`，**没有对外 API，也没有 SPI 发送层**。
- 接 STM32 时，推荐在这个边界增加 SPI 发布进程，或在 `_pwm_worker` 中把本地
  PWM 写入替换为 SPI 命令发送；不要在 KWS 回调里直接做阻塞式 SPI 事务。
- 当前 `_pwm_worker` 在导入 `maix` 之前 fork，目的是节省 128 MB 板子的内存；
  新的 SPI 进程也应保持轻量，不要继承多媒体状态。
- 温度读取应放在独立线程/进程或轻量周期任务中，直接 `import sg2002_temp`，
  按 ≤1 Hz 调用 `sample("sysfs")`；不要每秒启动一次 CLI 进程。

### 建议的最小 SPI 契约（待冻结）

以下只是交接建议，**代码中尚未实现，也不是已冻结协议**：

- 物理层：3.3 V 逻辑、共地；SPI 模式、时钟、CS、总线号和 MaixCAM/STM32 引脚映射待定。
- 帧结构建议包含：帧头、协议版本、长度、序号、命令、负载、CRC。
- 最小命令集建议：
  - `TEMP`：`temp_mc`（int32，m°C）+ 采样时间/序号；建议 1 Hz。
  - `VOICE/CTRL`：语音决策结果、亮度/模式/彩蛋状态或等效高层命令。
  - `HEARTBEAT`：MaixCAM 存活与链路状态。
  - `ACK/STATUS`：STM32 确认、故障、PWM 输出状态。
- 必须定义：断链超时、上电默认状态、急停/全灭、CRC 错误处理、序号回绕和重试策略。
- 温度值优先上报 `temp_mc` 整数，避免浮点端序问题。

### 关键文件

| 文件 | 作用 |
| --- | --- |
| `surplife/app/voice_pwm.py` | 当前语音 KWS、门控、彩蛋和本地 A18/A19 PWM 主程序 |
| `surplife/app/README_pwm.md` | 语音门限、状态机、彩蛋、PWM 接线的详细说明 |
| `surplife/app/sg2002_temp.py` | SG2002 只读温度读取；生产 SPI 上报应复用此模块 |
| `surplife/app/README_TEMP_SENSOR.md` | 温度寄存器、低温注意事项、SPI 职责边界 |
| `surplife/app/tests/` | 语音、PWM、温度和协议测试 |
| `surplife/app/lamp_ui.py` | 触摸 UI/调试界面；不要和生产语音进程同时长期运行 |
| `config/voice_keyword_logger.py` | 主机端语音日志调试工具，不是板端生产链路 |
| `config/cpu_temperature_logger.py` | **仅在 `feature/sg2002-temp-sensor`**；主机端无线调试记录器，不属于 main/SPI 生产链路 |

### 运行与验证

```sh
cd /root/surplife/app

# 生产语音 + 本地旧灯控
./start_voice_pwm.sh

# 只读温度
./sg2002_temp.py --json
./sg2002_temp.py --json --count 0 --interval 1

# 单元测试（主机端可跑，不依赖 maix）
python3 -m unittest discover -s tests -v
```

- 仓库没有提供 systemd/autostart；生产启动以脚本为准。
- 模型文件、`lib/`、`wheels/` 不在仓库内，板端运行环境需单独准备。
- 生产语音和触摸 UI 不要同时长期运行，128 MB 内存下会争抢资源。

### 交给下一个 Agent 的待办

1. 先确认 STM32 的 SPI 角色、引脚、模式、时钟和 15 路 PWM 映射。
2. 冻结 `TEMP`/`VOICE-CTRL`/`HEARTBEAT`/`ACK` 帧格式和失效安全策略。
3. 在 `voice_pwm.py` 的判断输出处增加 SPI 发布层，保留现有语音逻辑不变。
4. 把 `sg2002_temp.sample()` 接入 1 Hz 温度上报，验证与 sysfs 数值一致。
5. 在 STM32 侧实现 15 路 PWM、看门狗和断链安全状态。
6. 用示波器/逻辑分析仪验证 SPI 时序、温度帧和 PWM 输出，再做整机联调。

## 目录

| 目录 | 内容 |
| --- | --- |
| `surplife/` | MaixCAM 上的完整项目快照：语音 KWS、PWM 呼吸灯、触摸 UI、BLE/HTTP、测试、历史版本、截图和文本日志 |
| `maixcam/` | MaixCAM-Pro YOLO11 姿态识别参考示例 |
| `config/` | 主机端“语音关键词记录器”：通过 SSH 读取板子 `pwm.log` |
| `light-dots/` | Surplife 20x20 LED 窗帘 BLE 协议笔记、俄罗斯方块、相机参考 |

## 说明

- `surplife/` 主体是 2026-10-25 主机端快照；其中 `app/voice_pwm.py` 已在 2026-10-28 同步到板端 **v0.3.0**（PWM 载波改为 1 kHz；语音、灯效和 10s 肺活量彩蛋沿用 v0.2.7）。v0.2.7 原文件放在 `surplife/archive/voice_pwm.py.v027`，v0.2.5 原文件放在 `surplife/archive/voice_pwm.py.v025`。
- `surplife/app/sg2002_temp.py`（SG2002 只读温度读取）已合入 `main`，供后续 STM32 SPI 温度上报与温控决策使用；主机端无线 1 Hz 温度记录器保留在 `feature/sg2002-temp-sensor`，仅作调试工具。
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
- [`surplife/app/README_TEMP_SENSOR.md`](surplife/app/README_TEMP_SENSOR.md)
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
