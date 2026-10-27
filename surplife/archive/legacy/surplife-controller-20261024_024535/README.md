# Surplife 400 LED 窗帘灯控制器

基于 BLE 的 REST API 控制器，用于控制 Surplife 智能 LED 窗帘灯 (2x2m, 400 LEDs)。

## 功能

- BLE 扫描与连接
- 电源开关
- 单色控制 (色相 + 亮度)
- 内置效果模式 (18 种效果)
- 全局亮度/速度调节
- 音乐模式 (设备麦克风)
- 手机音乐可视化
- 滚动文本显示
- 单像素控制
- 动画上传
- Web UI 控制界面

## 安装

```bash
cd surplife-controller
pip install -r requirements.txt
```

## 运行

```bash
# 方式 1: 直接运行
python main.py

# 方式 2: 使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

启动后:
- API 文档: http://localhost:8000/docs
- Web UI: http://localhost:8000/

## API 端点

| 方法 | 路径 | 描述 |
|------|------|------|
| POST | `/connect` | 连接设备 |
| POST | `/disconnect` | 断开连接 |
| GET | `/scan` | 扫描附近设备 |
| GET | `/status` | 获取设备状态 |
| POST | `/power` | 电源开关 `{on: bool}` |
| POST | `/color` | 设置颜色 `{hue: 0-255, brightness: 0-255}` |
| POST | `/effect` | 效果模式 `{effect_id, speed, brightness}` |
| POST | `/brightness` | 全局亮度 `{brightness: 0-100}` |
| POST | `/speed` | 全局速度 `{speed: 0-100}` |
| POST | `/music` | 音乐模式 `{active, brightness, effect_id, sensitivity}` |
| POST | `/phone-music` | 手机音乐 `{bands: [0-100, ...]}` |
| POST | `/text` | 文本显示 `{text, speed, brightness}` |
| POST | `/pixels` | 单像素控制 `{pixels: [{index, color}]}` |
| POST | `/animation` | 动画上传 `{frames: [base64], frame_delay}` |

## 使用示例

```bash
# 扫描设备
curl http://localhost:8000/scan

# 连接 (自动扫描)
curl -X POST http://localhost:8000/connect -H "Content-Type: application/json" -d '{}'

# 连接 (指定地址)
curl -X POST http://localhost:8000/connect -H "Content-Type: application/json" -d '{"address": "AA:BB:CC:DD:EE:FF"}'

# 开机
curl -X POST http://localhost:8000/power -H "Content-Type: application/json" -d '{"on": true}'

# 设置红色
curl -X POST http://localhost:8000/color -H "Content-Type: application/json" -d '{"hue": 0, "brightness": 255}'

# 设置效果
curl -X POST http://localhost:8000/effect -H "Content-Type: application/json" -d '{"effect_id": 5, "speed": 50, "brightness": 80}'

# 关机
curl -X POST http://localhost:8000/power -H "Content-Type: application/json" -d '{"on": false}'
```

## 协议说明

本控制器基于以下逆向工程文档实现:

- [ge0rg/surplife-curtain](https://codeberg.org/ge0rg/surplife-curtain) - 硬件和协议分析
- [marcelrv/controllights.md](https://gist.github.com/marcelrv/36f9d2c66a273289211cc5fa73b00018) - 协议详解

### BLE 连接参数

- Service UUID: `0000ffff-0000-1000-8000-00805f9b34fb`
- Write Characteristic: `0000ff01-0000-1000-8000-00805f9b34fb`
- Notify Characteristic: `0000ff02-0000-1000-8000-00805f9b34fb`
- MTU: 186 bytes
- 设备名称: `IOTBTxxx`

## 系统要求

- Python 3.10+
- 支持 BLE 的适配器 (推荐 Raspberry Pi 4 / 5, 或带 BLE 的 Linux/Mac/Windows)
- Linux 推荐 (bleak 在 Linux 上最稳定)

## 许可证

MIT
