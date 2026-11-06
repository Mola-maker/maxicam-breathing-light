# 硬件与默认输出

## 15 路 PWM

| 输出 | 引脚 | 定时器/通道 | 频率 |
|---|---|---|---:|
| PWM1 | PA0 | TIM2_CH1 | 2 kHz |
| PWM2 | PA1 | TIM2_CH2 | 2 kHz |
| PWM3 | PA2 | TIM2_CH3 | 2 kHz |
| PWM4 | PA3 | TIM2_CH4 | 2 kHz |
| PWM5 | PB0 | TIM3_CH3 | 2 kHz |
| PWM6 | PB1 | TIM3_CH4 | 2 kHz |
| PWM7 | PA8 | TIM1_CH1 | 2 kHz |
| PWM8 | PA9 | TIM1_CH2 | 2 kHz |
| PWM9 | PA10 | TIM1_CH3 | 2 kHz |
| PWM10 | PA11 | TIM1_CH4 | 2 kHz |
| PWM11 | PB6 | TIM4_CH1 | 20 kHz |
| PWM12 | PB5 | TIM3_CH2 | 2 kHz |
| PWM13 | PB4 | TIM3_CH1 | 2 kHz |
| HEAT1 | PB8 | TIM4_CH3 | 20 kHz |
| HEAT2 | PB7 | TIM4_CH2 | 20 kHz |

PWM11 与 HEAT1/HEAT2 同属 TIM4，统一 20 kHz；其余灯牌 PWM 为 2 kHz。

## 字牌映射

```text
长 → GLYPH_CHANG → PWM1 → PA0/TIM2_CH1
春 → GLYPH_CHUN  → PWM2 → PA1/TIM2_CH2
```

协议只传 `glyph_mask`，不传 TIM/CH。

## 6 个功率电阻

```text
HEAT1: 5V → R7/R8/R9(10Ω 并联) → Q1(AO3400A) → GND
HEAT2: 5V → R12/R13/R14(10Ω 并联) → Q2(AO3400A) → GND
```

- 每路等效 3.33Ω；
- 5V/100%：每路 1.5A、7.5W；每只 10Ω 约 2.5W；
- 两组 100%：3A、15W；50% 平均约 7.5W；
- 栅极 10k 下拉，TIM4 PWM1 高极性；CCR=0 输出低，MOSFET 关断。

## 加热现状

v1 不实现 PID：

- HEAT1/HEAT2 固定 0%；
- `THERMAL_CONFIG` 只置 `HEATER_UNSUPPORTED`；
- `ALL_OFF`、500 ms 超时、HELLO 重置都会关闭输出；
- 温度只接收并回显，不参与控制。

后续需要显式 `HEATER_ENABLE`、目标温度/PID、最大占空比、温度过期/断链关闭、过流/过温保护和限流测试。

## 安全

- 电阻额定功率至少覆盖 2.5W/只并留余量；
- 5V 电源/连接器满足约 3A；
- AO3400A、走线、端子满足电流；
- HEAT 只能接功率级栅极；
- 首次测试用限流电源并加独立硬件保护。
