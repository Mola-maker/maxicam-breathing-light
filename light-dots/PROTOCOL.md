# Surplife 20x20 LED 窗帘 BLE 协议逆向笔记

来源:
- ge0rg/surplife-curtain (抓包日志): https://codeberg.org/ge0rg/surplife-curtain
- marcelrv gist (Android 源码分析): https://gist.github.com/marcelrv/36f9d2c66a273289211cc5fa73b00018
- MaixCAM (10.78.72.1) 上现有实现 `/root/surplife/app`, 副本在 `reference/camera_app/app`

## 设备

- 型号 0x00C2 (Zengge/Surplife), 2x2 m, 400 LED = 20 x 20, 5V 9W
- 广播名 `IOTBTxxx`, 本机设备 MAC `08:65:F0:23:9C:FD`
- GATT: 服务 `0000ffff-...`, 写 `0000ff01-...` (handle 0x0003), 通知 `0000ff02-...` (handle 0x0005, CCCD 0x0006)
- 官方 App MTU = 186

## 传输层 (V0, 大端)

单段 (8 字节头):

| 偏移 | 字段 | 说明 |
|---|---|---|
| 0 | control | bit6 多段, bit5 protect, bit4 ack, bit1-0 版本 (0=V0) |
| 1 | seq | 递增序号 |
| 2-3 | line id | 单段固定 `80 00` |
| 4-5 | total len | payload 长度 (不含 cmd_id) |
| 6 | chunk len | payload + 1 (含 cmd_id) |
| 7 | cmd_id | App 下发固定 `0x0A` |
| 8.. | payload | 应用层命令 |

例: `00 04 80 00 00 04 05 0a e2 0b 29 bf`

多段: 首段 control=0x40, line id=0000; 续段 5 字节头 `40 seq [seg_id u16] [len]`, 末段 seg_id 最高位置 1。

设备通知 cmd_id: `0x0C` JSON, `0x15` 查询回复, `0x16` 状态变化。

## 状态 (通知 payload, `EA 81` 开头)

`ea 81 01 00 c2 06 23 66 01 38 f0 ...`

| 字节 | 含义 |
|---|---|
| 3-4 | 型号 `00C2` |
| 5 | 硬件版本 |
| 6 | 电源 `23` 开 / `24` 关 |
| 7 | 模式 `62` 音乐, `66` 单色, `67` 效果, `72` 动画, `73` 文本, `74` 图片 |
| 8-9 | 效果 ID / 速度 / 亮度 (随模式) |

## 颜色: 16-bit HSV (745)

`HHHHHHH SSSS VVVVV`: 色相 7 bit (3°/步, 0-119), 饱和度 4 bit (0-15), 亮度 5 bit (0-31)。

| 值 | 颜色 |
|---|---|
| `01FF` | 红 |
| `29FF` | 黄 |
| `51FF` | 绿 |
| `A1FF` | 蓝 |
| `C9FF` | 粉 |
| `001F` | 白 |
| `0012` | 灰 |
| `0000` | 黑 / 擦除 |

## 应用层命令 (cmd_id 0x0A 后的 payload)

| payload | 功能 |
|---|---|
| `10 [世纪][年][月][日][时][分][秒][星期] 00 0F [和校验]` | 时间同步 (连接后第一条) |
| `EA 81 8A 8B 59` | 握手 / 查询状态 / 保活 |
| `71 23` / `71 24` | 开 / 关 |
| `E2 0B [hsv16]` | 整屏单色 |
| `E0 02 00 [效果 00-11] [速度] [亮度]` | 内置效果 |
| `E2 09 01 [速度 0-75] [亮度 0-100] [00 循环/02 单次]` | 动画/图片播放参数 |
| `E1 05 ...` | 设备麦克风音乐模式 |
| `E2 0A [20 列振幅 0-100]` | 手机音乐频谱帧 |
| `E2 04 00 00 [每字 0C + 7 列 u16]` | 文本位图 |
| `E2 05 [11 字节样式][速度][亮度][方向]` | 文本参数, 方向 00 固定/01 闪/02 左/03 右/04 上/05 下 |
| `EA 01..04` | 图片/动画帧上传 (帧压缩格式未解析) |
| `E0 15 / E0 13 / E0 0E 01` | 引脚校准 / RGB 顺序映射 / 保存 |

## 像素绘制 (俄罗斯方块用到的命令)

```
E2 0C 90 [hsv16 hi] [hsv16 lo] [50 字节掩码]
```

- 掩码 400 bit, 置 1 的像素被设成该颜色; hsv16 = 0000 即擦除
- 每种颜色一条命令, 每条 55 字节 payload, 单个 BLE 包即可
- 清屏: 颜色 0000 + 掩码全 FF
- 位序: MSB 优先, 列优先 (bit = x*20 + y, (0,0) 左上, 下一位是正下方像素)。
  2026-10-19 用校准图案在硬件上确认, 与 marcelrv 文档一致。
- 摄像头上的 `pixel_mask` 默认按行优先, 因此 `/pixels`、`/frame` 的 x/y 在灯面上是互换的。
  游戏默认在客户端交换 x/y 来抵消 (`--no-transpose` 关闭)。

## MaixCAM 上的现有项目

- `/root/surplife/app/main.py`: FastAPI, 端口 8000, 无鉴权 (未设置 SURPLIFE_TOKEN), 持有 BLE 连接
- `/root/surplife/app/voice_kws.py`: 关键词识别, 听到“长春”后 POST `/color` 切换色相
- 绘图相关接口:
  - `POST /pixels {"pixels":[{"x","y","color":"#RRGGBB"}], "clear": bool}`: 按颜色分组发 E2 0C
  - `POST /frame {"frame": 20x20 "#RRGGBB"}`: 整幅画面
  - `POST /clear`
- 注意: `/color` 会让设备离开绘图模式, 游戏运行时若语音触发, 画面会被单色覆盖
  (游戏会轮询 `/status` 检测并整屏重绘)。
