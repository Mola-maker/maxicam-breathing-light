# voice_pwm — 语音门控 18 kHz PWM 灯控

## 接线 / 输出

| MaixCAM 引脚 | PWM 通道 | sysfs | 用途 |
|---|---|---|---|
| A18 | PWM6 | `/sys/class/pwm/pwmchip4/pwm2` | 亮度 |
| A19 | PWM7 | `/sys/class/pwm/pwmchip4/pwm3` | 闪烁频率给定（默认） |

两路都是 **18 kHz 载波**，占空比 0–100%。

## 运行

```sh
cd /root/surplife/app
./run_voice_pwm.sh
```

默认使用 Maix-Speech KWS（`chang2 chun1`）做“长春”门控；SenseVoice 在这个
MaixCAM-Pro / 128 MB 板子上不可用。

## 状态机

```text
待机: A18 慢速呼吸 5% ~ 35%, A19 = 0
  │
  │ KWS 概率 >= 0.5 (上升沿, 无时间不应期)
  ▼
业务: 参考声量 ref = 门控词 "chang--chun--" 的 1.5 s 峰值
      level = 当前干净人声包络 / ref
      voice_active = env >= max(VOICE_ACTIVE_MIN, VOICE_ACTIVE_RATIO * ref)
      target = 40% + 60% * level    (voice_active)
      target = 0                    (voice inactive)

      每个 tick:
          light_level -= decay_per_tick * (dt / tick)
          if target > light_level:
              light_level = target      # 快攻
          A18 亮度 = light_level
          A19 占空 = level_slow * 100%   (PWM7_MODE=freq)
          闪烁频率 = 1 Hz + 7 Hz * level_slow

      有人声: decay_per_tick = 1
      人声结束: decay_per_tick = 3
  │
  │ light_level < LIGHT_THRESHOLD (默认 35%)
  ▼
待机
```

## A19 / 闪烁模式

通过环境变量选择，默认 `freq`：

```sh
# A19 占空比 = 音量相对值, 作为外部驱动的闪烁频率给定 (默认)
PWM7_MODE=freq ./run_voice_pwm.sh

# A19 完全跟随 A18, 适合两路并联 LED
PWM7_MODE=mirror ./run_voice_pwm.sh

# A19 按闪烁频率做 0/100% 翻转, 适合 A19 直接驱动第二路灯
PWM7_MODE=square ./run_voice_pwm.sh

# A19 关闭
PWM7_MODE=off ./run_voice_pwm.sh
```

如果希望 **A18 主灯自己** 也做亮-灭翻转：

```sh
A18_BLINK=1 ./run_voice_pwm.sh
```

## 无语音演示 / 干跑

```sh
# 不写 PWM, 只打印状态; 自动 2 s 待机 + 5 s 业务 + 衰减回待机
PWM_DRY_RUN=1 PWM_DEMO=1 ./run_voice_pwm.sh

# 真正输出 PWM, 自动演示待机/业务/衰减
PWM_DEMO=1 ./run_voice_pwm.sh

# 端到端诊断: 3 秒后注入一次“长春”门控事件, 之后仍按真实音量包络走
PWM_TEST_GATE_AFTER=3 ./run_voice_pwm.sh
```

演示结束后进程继续监听语音；按 Ctrl+C 退出，PWM 会被关闭。

## 常用调节

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_GATE_THRESHOLD` | 0.5 | “长春”门限 |
| `VOICE_GATE_REARM` | 0.28 | 概率回落多少后允许下一次触发（无时间不应期） |
| `STANDBY_MIN/MAX` | 5 / 35 | 待机呼吸占空比范围 |
| `STANDBY_PERIOD` | 4.0 | 呼吸周期（秒） |
| `BUSINESS_MIN/MAX` | 40 / 100 | 业务亮度映射范围 |
| `LIGHT_THRESHOLD` | 35 | 亮度衰减到该值以下回待机 |
| `DECAY_TICK_MS` | 20 | “每 tick”的时间长度（毫秒） |
| `WORK_DECAY_PER_TICK` | 1 | 有人声时每 tick 衰减量 |
| `RELEASE_DECAY_PER_TICK` | 3 | 人声结束后每 tick 衰减量 |
| `VOICE_ACTIVE_MIN` | 0.0015 | 判为人声的最小线性 RMS |
| `VOICE_ACTIVE_RATIO` | 0.02 | 判为人声的相对门限（× ref） |
| `BLINK_HZ_MIN/MAX` | 1 / 8 | 闪烁频率范围 |
| `BLINK_INVERT` | 0 | 设为 1 则声量越大闪得越慢 |
| `PWM_UPDATE_HZ` | 100 | PWM 更新率 |
| `PWM_FREQ` | 18000 | 载波频率 |

> `EXIT_RATIO` / `EXIT_HOLD` 已移除；退出完全由 `LIGHT_THRESHOLD` +
> `RELEASE_DECAY_PER_TICK` 决定。门控仍只认完整的 `chang2 chun1`。

## 降噪 / 音量链

`pwm_mic`（`/root/.asoundrc`）把麦克风 PCM 复制到 FIFO：

```text
hw:0,0 -> ALSA file 插件 -> /tmp/surplife_pwm_mic.pcm -> DSP 子进程
```

DSP 子进程做：

1. 频域高通，削弱 80 Hz 以下风噪/轰鸣；
2. 慢速噪声谱估计 + 谱减，压环境白噪声；
3. 150–1200 Hz（含 ang/en/un 鼻韵）人声加权；
4. 低频能量占比高时判定风噪并进一步压低；
5. KWS 概率高或处于业务态时降低门限、增强人声并冻结噪声估计；
6. 20 ms/150 ms 快包络给亮度，100 ms/500 ms 慢包络给闪烁频率。

## 注意

- 旧的 BLE 语音应用 `voice_kws.py` 和本应用不能同时运行：两者都要独占
  `hw:0,0`，同时启动会有一个打不开麦克风。
- A18/A19 的 PWM 复用由 MaixPy `pinmap` 设置；如果手动改过引脚复用，重启
  本应用即可重新设置。
- 退出时会把两路 duty 置 0 并 `enable=0`，避免灯常亮。
