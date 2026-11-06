# STM32：15 路 PWM + 保温板执行器

本目录是 `/home/jlu/桌面/CubeMX/C8T6/PWM-Heater` 的完整代码副本，目标 MCU 为 STM32F103C8T6，72 MHz。

STM32 不跑语音模型；它接收 MaixCAM 的 `PERFORM` 事件，执行 15 路 PWM，并接收温度用于状态回显和后续温控。

## 硬件接口

- SPI1 从机：Mode 0，PA4/PA5/PA6/PA7，固定 64 字节帧；
- USART3：PB10/PB11，115200 8N1，仅本地调试；
- TIM1/TIM2/TIM3：2 kHz，PWM1–PWM10、PWM12、PWM13；
- TIM4：20 kHz，PWM11、HEAT1、HEAT2；
- 字牌映射：“长”→PWM1/PA0，“春”→PWM2/PA1；
- 加热：2 路 PWM，6 个 10Ω 功率电阻，3 并/路。

完整引脚和功率计算见 `docs/HARDWARE.md`。

## 构建

```sh
cd stm32
cmake --preset Release
cmake --build --preset Release
```

输出：

```text
build/Release/PWM-Heater.elf
build/Release/PWM-Heater.hex
build/Release/PWM-Heater.bin
```

仓库另存一次已验证固件：

```text
firmware/PWM-Heater.hex
firmware/PWM-Heater.bin
```

烧录：

```sh
st-flash --reset write stm32/firmware/PWM-Heater.bin 0x08000000
```

## 当前固件业务

| 业务 | 说明 |
|---|---|
| 15 路 PWM | `Core/Src/board_pwm.c` |
| 字牌映射 | `Core/Inc/glyph_map.h` |
| 待机呼吸 | 1%–8%，4 s 周期 |
| GATE/HOLD/RELEASE | 30 ms 上升；保持；2.5 s 渐弱 |
| EGG | 1.6 s 5 Hz 亮灭，再熄灭 2 s |
| SPI v1 | HELLO/TEMP/PERFORM/HEARTBEAT/ALL_OFF/THERMAL_CONFIG |
| 状态 | STATUS + CAPS，温度、链路、故障、字牌状态 |
| 安全 | 500 ms 无合法控制帧，全部输出关闭 |
| 加热 | v1 固定 0%，无 PID |

上电、未握手、`ALL_OFF`、链路超时都会让 15 路 PWM 为 0；收到 `HELLO` 后还要显式 `STANDBY` 或 `GATE` 才点灯。

## 6 个功率电阻

```text
HEAT1: R7/R8/R9 10Ω 并联（3.33Ω），PB8/TIM4_CH3
HEAT2: R12/R13/R14 10Ω 并联（3.33Ω），PB7/TIM4_CH2
```

Q1/Q2 为 AO3400A N-MOS 低边开关，HEAT 高电平导通。默认 `HEAT1=HEAT2=0%`，6 个电阻全部关闭，0 W。

5 V 满占空比时每组约 1.5 A / 7.5 W，两组约 3 A / 15 W；每只 10Ω 电阻约 2.5 W。测试前确认电源、电阻额定功率、MOSFET 和走线。


## 测试扩展

当前测试分支在 v1 上增加了：

- `GLYPH_ALL_LAMPS`（glyph bit 2，mask `0x4`）：驱动 PWM1–PWM13，排除 HEAT1/HEAT2；
- `TEMP` TLV 到达时通过 USART3 打印 `[temp] ... mC ...`，便于 1 Hz 温度观测；
- 每路灯 PWM 取所有活跃 glyph 的最大占空比，避免 `GLYPH_ALL_LAMPS` 归零时
  覆盖 `长`/`春` 等单字 PWM，保持原业务可叠加。

测试固件文件：

```text
firmware/PWM-Heater-test.hex
firmware/PWM-Heater-test.bin
```

2026-11-06 已用 ST-Link V2 烧录测试扩展固件并校验通过；v1 基线仍保留为
`firmware/PWM-Heater-v1-base.hex/bin`，可随时回退。

## 已验证状态

2026-11-04 已用 ST-Link V2 烧录并读回校验：

```text
PWM-Heater.bin
SHA256 4dd2531314719912d362bdd68c30d4070f1af02e951cdb218111c1f67ebab609
```

读到的寄存器：

```text
TIM2 CR1=0x00000001 PSC=35 ARR=999  CCR1..4=0
TIM4 CR1=0x00000081 PSC=8  ARR=399  CCR1..3=0
```

说明新固件运行、15 路输出和 HEAT 全关。SPI/整机 15 路灯牌尚未系统级联调，ST-Link NRST 尚未接。

### 2026-11-06 测试扩展固件

```text
PWM-Heater-test.bin / PWM-Heater.bin
SHA256 5fcb600380c41cd2619e35c9e5158ee10e6a86e7c56c53df17ff6707ff81ca78
```

ST-Link V2（`0483:3748`）识别目标为 `STM32F1xx_MD`，Chip ID `0x0410`，
SRAM 20 KiB，st-link 报告 Flash 128 KiB；写入 16,784 B 到 `0x08000000`，
`st-flash 1.8.0` 返回 `Flash written and verified!`，随后通过 AIRCR 软件复位。
本次未重新读取 TIM 寄存器；MaixCAM Pro 尚未接入，SPI、13 路灯牌动作和
USART3 `[temp]` 输出仍需整机联调。
