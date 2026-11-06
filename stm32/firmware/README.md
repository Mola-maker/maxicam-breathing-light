# STM32 固件

## 测试扩展固件（当前目录的 PWM-Heater.hex/bin）

在 v1 基线上增加：

- `GLYPH_ALL_LAMPS`（bit 2）：一次驱动 PWM1–PWM13，HEAT1/HEAT2 保持关闭；
- 收到 TEMP TLV 时通过 USART3 打印 `[temp] <mC> ...`。

| 文件 | SHA256 |
|---|---|
| `PWM-Heater.hex` | `72f1372f81f49463049e527f6e45dcd6625a7f9252671d62ac6ea15f4de5ccf8` |
| `PWM-Heater.bin` | `5fcb600380c41cd2619e35c9e5158ee10e6a86e7c56c53df17ff6707ff81ca78` |

2026-11-06 已用 ST-Link V2（`0483:3748`）通过 `st-flash 1.8.0` 烧录到目标板：
写入 16,784 B 到 `0x08000000`，日志为 `Flash written and verified!`，随后通过
AIRCR 软件复位（NRST 未连接）。MaixCAM Pro 尚未接入，因此 SPI、13 路灯牌和
USART3 温度打印仍需整机联调。

## 已验证 v1 基线

| 文件 | SHA256 |
|---|---|
| `PWM-Heater-v1-base.hex` | `4dce928e46e97023363e5d2e2e434276b8de960074f7d2a119dae60ab8bf07a5` |
| `PWM-Heater-v1-base.bin` | `4dd2531314719912d362bdd68c30d4070f1af02e951cdb218111c1f67ebab609` |

v1 基线已用 ST-Link V2 烧录并读回校验，烧录后 TIM2/TIM4 均已启动、CCR 全 0。

烧录：

```sh
st-flash --reset write PWM-Heater.bin 0x08000000
```

目标：

```text
STM32F103C8T6
Chip ID 0x0410
SRAM 20 KiB
Flash 128 KiB (st-link reported)
```
