# 已验证固件

| 文件 | SHA256 |
|---|---|
| `PWM-Heater.hex` | `4dce928e46e97023363e5d2e2e434276b8de960074f7d2a119dae60ab8bf07a5` |
| `PWM-Heater.bin` | `4dd2531314719912d362bdd68c30d4070f1af02e951cdb218111c1f67ebab609` |

烧录：

```sh
st-flash --reset write PWM-Heater.bin 0x08000000
```

已验证目标：

```text
STM32F103C8T6
Chip ID 0x0410
SRAM 20 KiB
Flash 128 KiB (st-link reported)
Firmware 16,576 B
```

烧录后 TIM2/TIM4 已启动，CCR 全 0；HEAT1/HEAT2 默认关闭。

从源码重新构建时，以 `stm32/build/Release/` 新产物为准，并同步更新 SHA256。
