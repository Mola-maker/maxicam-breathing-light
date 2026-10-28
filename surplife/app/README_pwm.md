# voice_pwm — 语音门控 1 kHz PWM 灯控

版本：**0.3.0**（在 v0.2.7 基础上仅将 PWM 载波从 18 kHz 改为 1 kHz；语音、灯效、10s 彩蛋逻辑不变）

## v0.3.0 变更

- A18/A19 载波频率：**18 kHz → 1 kHz**（`period` 由 55555 ns 改为 1000000 ns）。
- 语音门控阈值、呼吸/业务/衰减曲线、10s 肺活量彩蛋的时序与阈值全部沿用 v0.2.7。
- `PWM_FREQ` 环境变量仍可覆盖默认值，便于测试其他载波频率。

## 接线 / 输出

| MaixCAM 引脚 | PWM 通道 | sysfs | 用途 |
|---|---|---|---|
| A18 | PWM6 | `/sys/class/pwm/pwmchip4/pwm2` | 亮度 |
| A19 | PWM7 | `/sys/class/pwm/pwmchip4/pwm3` | 闪烁频率给定（默认） |

两路都是 **1 kHz 载波**，占空比 0–100%。

> **电气安全：** A18/A19 是 3.3 V 逻辑 PWM 输出，不能直接接灯珠或大电流
> 负载。必须经过 MOSFET、三极管或恒流驱动级，并与板子共地；否则会损坏
> SoC 引脚。

## 运行

```sh
cd /root/surplife/app
./run_voice_pwm.sh
```

默认使用 Maix-Speech KWS 识别八个单字：
`chang1/chang2/chang4`、`chun1/chun2/chun3`、`ang1/ang2`，
并额外注册一个整词 `chang2 chun1`。Maix-Speech 的 `kws` 支持用空格分隔的
多音节拼音，整词识别可以解决连续说“长春”时单字 KWS 只上报其中一个字的问题：
- 正常说“长春”：优先由整词 `chang2 chun1` 开门；
- 拉长说“长～～～春”：整词可能失配，继续由单字 `chang` + `chun` 拼装；
- 如果拖长时只识别到 `chun`，但本次连续人声在 `chun` 之前已持续
  `VOICE_LONG_PREFIX_SECONDS`（默认 0.80s，RMS ≥ 0.030），则把长前导
  当作拖长的“长”，`chun >= 0.10` 即开门。拖得越长，KWS 给出的 `chun`
  概率会下降（实测 3.77s 前导时只有 0.193），所以长前导路径使用低置信门限。
  短促的单独“春”不会达到该时长。

`ang1/ang2` 仍保留在 KWS 词表里方便调试，但**不参与开门判断**。
模型词表不含 `chun4`（实测 `parse kws chun4 error!`），因此用可用的
`chun3` 代替；其余声调均按原要求注册。SenseVoice 在这个 MaixCAM-Pro /
128 MB 板子上不可用。

## 识别 / 判断两段

`nn.Speech.run()` 在推理期间会持续持有 Python GIL，同进程的 Python 线程
拿不到第二个核。因此逻辑上分成两段，但为了真正并行，判断段放在独立子进程：

1. **识别段**（主进程）
   - 注册八个单字关键词 + 一个整词关键词 `chang2 chun1`；
   - 每个字族 `chang/ang/chun` 取当前帧概率最高的声调；
   - 单字概率达到 `VOICE_CHAR_THRESHOLD` 后输出：
     `CHAR chang2 p=0.612 t=03:... mono=... dt=+0.000 pre=0.85s`；
   - 整词达到 `VOICE_PHRASE_THRESHOLD` 后输出：
     `PHRASE chang2 chun1 p=0.612 ...`；
   - `pre=` 是 DSP 子进程按 RMS 实时累计的本次连续人声时长；
   - 通过 `Pipe` 把 `(时间戳, 关键词, 字族, 置信度, 连续人声时长)`
     立即送给判断段；不做任何开门判断。

2. **判断段**（独立进程，第二个核）
   - 收到整词 `phrase`：`score >= VOICE_PHRASE_THRESHOLD` 直接开门；
   - 否则记录最近一个 `chang`，收到 `chun` 时检查是否超过
     `VOICE_SEQ_WINDOW`：默认 `0`（完全不限时），正数才启用超时；
   - 单字拼装分 = `max(chang.conf, chun.conf)`，避免拖长后某一个字概率偏低；
   - 如果只有 `chun` 且没有 `chang`，但 `pre >= VOICE_LONG_PREFIX_SECONDS`
     且 `chun.conf >= VOICE_LONG_PREFIX_MIN_CONF`（默认 0.10），按“拖长的长”
     兜底开门；
   - `score >= VOICE_GATE_THRESHOLD` 才开门，否则只记录 `SEQ HOLD`；
   - 单独的短促 chang / chun / ang、顺序反了、超时或分数不够都保持关灯。

正常连读靠整词；拉长语音靠单字或长前导兜底。实测拖长时两字概率可能只剩
一个较高，因此单字路径使用两字的最大值。`VOICE_SEQ_WINDOW` 只负责可选超时，
不限制“长～～春”的拖音长度。长前导兜底只看“本次连续人声”时长，不依赖
`chang` 是否被 KWS 正确识别。

## 状态机

```text
待机: A18 慢速呼吸 1% ~ 8%, A19 = 0
  │
  │ 整词 chang2 chun1 >= 0.30，或 chang 后的 chun 两字 max >= 0.35，
  │ 或只有 chun 但连续人声 >= 0.80s（chun 低至 0.10 也可，拖长“长”前导）
  ▼
业务: 门控后从当前 PWM 亮度经 0.03 秒贝塞尔直接升到 100%；
      然后保持 100%，直到实时声强低于“本次最大声强”的 15%
      并持续 0.05 秒；拖音 un----- 期间只要声强不低于本次峰值的 15%，
      就继续保持 100%，不启用 en1 评分门控。
      释放后再走 2.5 秒分段斜坡:
          0–0.5 s: 100% → 50%
          0.5–1.3 s: 50% → 35%
          （以上是同一条三次贝塞尔，先快后慢；1.3 秒段内按 0.5/0.8 分配）
          1.3–2.5 s: 35% → 8%，线性
          到达 8% 后从呼吸最大值（8%）进入待机呼吸，不再跳变
          A18 亮度 = light_level
          A19 占空 = (light_level - 8%) / 92% * 100%  (PWM7_MODE=freq)
          闪烁频率 = 1 Hz + 7 Hz * level_slow

      一旦开始衰减，整个 2.5 s 斜坡连续走完，不再被包络打断。
  │
  │ 2.5 s 斜坡走完，到达 8%
  ▼
待机
```

## 10s 肺活量彩蛋（v0.2.7 起）

在“长～～春～～～”的连续拖音中，DSP 用独立的 `egg_voice_duration`
计时：只要 RMS ≥ `VOICE_LONG_PREFIX_RMS`（默认 0.030）就累计，
连续静音 **0.30 s** 后清零。它与 v0.2.5 原来的 0.6 s 长前导计时完全独立。

触发条件：
- 当前连续人声累计达到 **10.0 s**；
- 并且本次连续人声内已经出现过任一有效事件：
  `phrase`、`chang + chun`，或 `changchun-long`（长前导 chun）；
- 10 s 时没有有效事件不会触发；10 s 之后才出现第一个有效事件，则立即触发。

触发后的效果（A18 单独输出，A19 固定 0）：

```text
0.0–1.6 s   8 个硬翻转周期，每个周期 0.1 s 100% + 0.1 s 0%
            顺序：亮、灭、亮、灭……亮、灭（最后以灭结束）
1.6–3.6 s   A18 全灭
3.6 s 之后  回到待机慢速呼吸（从 1% 低点接上）
```

彩蛋从触发到 3.6 s 结束是**不可打断**的：主进程不再向判断进程发送
KWS 事件，判断进程也丢弃所有锁定期事件，不排队；PWM 进程忽略新的门控。
3.6 s 结束后：

- 判断进程清掉旧的 `chang`、门控冷却和蛋武装状态；
- 主进程在下一个识别回调中清掉去抖时间；
- 旧的拖音“春～～”后续事件继续丢弃；必须重新说完整的“长春”
  （新的 `chang` 或整词 `phrase`）才会回到正常业务，也才会重新武装彩蛋；
- 如果 0.3 s 静音已经发生，视为新的连续人声，也会解除旧拖音保护。

测试时可以缩短或注入彩蛋；生产默认值就是定稿值：

```sh
# 仅测试：启动 4 秒后注入一次彩蛋，不需要真人拖 10 秒
VOICE_EGG_TEST_AFTER=4 ./run_voice_pwm.sh

# 可选：缩短连续人声阈值做台架测试
VOICE_EGG_HOLD_SECONDS=2 VOICE_EGG_TEST_AFTER=0 ./run_voice_pwm.sh
```

`VOICE_EGG_TEST_AFTER` 默认 0（关闭），不会在正常启动时触发。

## A19 / 闪烁模式

通过环境变量选择，默认 `freq`：

```sh
# A19 占空比 = 业务斜坡归一化值 (100%→0), 作为外部驱动的闪烁频率给定 (默认)
PWM7_MODE=freq ./run_voice_pwm.sh

# A19 完全跟随 A18, 适合两路并联 LED
PWM7_MODE=mirror ./run_voice_pwm.sh

# A19 按闪烁频率做 0/100% 翻转, 适合经驱动级控制第二路灯
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

# 端到端诊断: 3 秒后注入一次门控, 观察 0.03s 升到 100 → 包络释放 → 2.5s 衰减
PWM_TEST_GATE_AFTER=3 ./run_voice_pwm.sh
```

演示结束后进程继续监听语音；按 Ctrl+C 退出，PWM 会被关闭。

离线验证识别/判断链时可以绕过麦克风。先验证低分保持关灯：

```sh
VOICE_INPUT_WAV=/root/surplife/run/chang_chun_sep.wav \
VOICE_GATE_THRESHOLD=0.35 \
VOICE_CHAR_THRESHOLD=0.10 \
VOICE_KWS_DEBUG=1 ./run_voice_pwm.sh
```

再验证高分序列开门（`prefix_x3.wav` 是链路测试用的合成片段）：

```sh
VOICE_INPUT_WAV=/root/surplife/run/prefix_x3.wav \
VOICE_GATE_THRESHOLD=0.35 \
VOICE_CHAR_THRESHOLD=0.10 \
VOICE_KWS_DEBUG=1 ./run_voice_pwm.sh
```

WAV 文件播完后主进程会退出。注意 WAV 模式按文件读取速度尽快处理，
事件时间戳用于验证链路，不等同于真实麦克风的实时时长。日志中的关键行：

```text
PHRASE chang2 chun1 p=0.527 ... pre=0.00s
SEQ GATE branch=changchun-phrase score=0.527 gate=0.30 keyword=chang2 chun1
GATE[changchun-phrase]: changchun=0.527
CHAR chun1 p=0.961 ... pre=1.25s
SEQ GATE branch=changchun-long score=0.193 gate=0.10 pre=3.77s keyword=chun1
GATE[changchun-long]: changchun=0.193
CHAR chang1 p=0.106 ...
SEQ HOLD score=0.244 < gate=0.35 ...
CHAR chun1 p=0.900 ... pre=0.35s
SEQ HOLD chun=chun1 p=0.900 reason=no-chang pre=0.35s  # 短促单独春
```

## 常用调节

| 变量 | 默认 | 说明 |
|---|---|---|
| `VOICE_GATE_THRESHOLD` | 0.35 | 单字两字置信度 max 的门限 |
| `VOICE_PHRASE_THRESHOLD` | 0.30 | 整词 `chang2 chun1` 的门限 |
| `VOICE_LONG_PREFIX_SECONDS` | 0.80 | 只报 chun 时，判为拖长“长”前导的最小连续人声时长（秒） |
| `VOICE_LONG_PREFIX_RMS` | 0.030 | 累计长前导使用的线性 RMS 门限 |
| `VOICE_LONG_PREFIX_MIN_CONF` | 0.10 | 长前导成立时 chun 的最低置信度 |
| `VOICE_CHAR_THRESHOLD` | 0.10 | 单字进入判断段的概率门限 |
| `VOICE_CHAR_DEBOUNCE` | 0.18 | 同字族重复上报的最小间隔（秒） |
| `VOICE_PHRASE_DEBOUNCE` | 2.0 | 整词重复上报的最小间隔（秒） |
| `VOICE_SEQ_WINDOW` | 0.0 | `chang`→`chun` 可选最大间隔（秒）；`0` 表示不限时 |
| `VOICE_GATE_COOLDOWN` | 1.0 | 开门后抑制重复序列的冷却时间（秒） |
| `VOICE_EGG_HOLD_SECONDS` | 10.0 | 连续人声达到该秒数触发肺活量彩蛋 |
| `VOICE_EGG_FLASH_SECONDS` | 1.6 | 彩蛋亮灭段总时长（秒） |
| `VOICE_EGG_CYCLE_SECONDS` | 0.2 | 彩蛋单周期；默认亮 0.1 s + 灭 0.1 s |
| `VOICE_EGG_OFF_SECONDS` | 2.0 | 彩蛋亮灭后全灭时长（秒） |
| `VOICE_EGG_BRIGHT` | 100 | 彩蛋亮起占空比（%） |
| `VOICE_EGG_TEST_AFTER` | 0 | 仅测试：启动 N 秒后注入一次彩蛋；0 为关闭 |
| `VOICE_INPUT_WAV` | 空 | 可选离线调试 WAV；设置后不用麦克风 |
| `STANDBY_MIN/MAX` | 1 / 8 | 待机呼吸占空比范围 |
| `STANDBY_PERIOD` | 4.0 | 呼吸周期（秒） |
| `BUSINESS_MIN/MAX` | 40 / 100 | 业务映射范围（实机斜坡从 MAX 到阈值） |
| `BUSINESS_INTRO_SECONDS` | 0.03 | 门控后从当前亮度升到 100% 的贝塞尔时长（秒） |
| `BUSINESS_INTRO_TARGET` | 100 | 门控后贝塞尔上升目标亮度（%） |
| `BUSINESS_BEZIER_SECONDS` | 1.3 | 100%→35% 贝塞尔段时长；100→50 占 0.5 s，50→35 占 0.8 s |
| `BUSINESS_LINEAR_SECONDS` | 1.2 | 35%→8% 线性段时长（秒） |
| `BUSINESS_HOLD_RATIO` | 0.15 | 拖音保持释放阈值（×本次峰值声强） |
| `BUSINESS_HOLD_RELEASE_SECONDS` | 0.05 | 低于阈值持续多久后释放（秒） |
| `LIGHT_THRESHOLD` | 35 | 业务第一段终点（35%） |
| `DECAY_TICK_MS` | 20 | 演示模式“每 tick”的时间长度（毫秒） |
| `WORK_DECAY_PER_TICK` | 1 | 仅 `PWM_DEMO` 使用 |
| `RELEASE_DECAY_PER_TICK` | 3 | 仅 `PWM_DEMO` 使用 |
| `VOICE_ACTIVE_MIN` | 0.01 | 判为人声的最小线性 RMS |
| `VOICE_ACTIVE_RATIO` | 0.04 | 判为人声的相对门限（× ref） |
| `BLINK_HZ_MIN/MAX` | 1 / 8 | 闪烁频率范围 |
| `BLINK_INVERT` | 0 | 设为 1 则声量越大闪得越慢 |
| `PWM_UPDATE_HZ` | 100 | PWM 更新率 |
| `PWM_FREQ` | 1000 | 载波频率（Hz） |

> `EXIT_RATIO` / `EXIT_HOLD` 已移除；门控后从当前亮度经 0.03 s 贝塞尔直接升到 100%，
> 保持到声强低于本次峰值的 15% 并持续 0.05 s；然后
> 100%→50%（0.5 s）+ 50%→35%（0.8 s）的三次贝塞尔 +
> 35%→8%（1.2 s 线性），最后从 8% 接回呼吸。
> 模型门控优先认整词 `chang2 chun1`（门限 0.30），否则认“chang 后出现 chun”
> 且两字 max 达到 0.35；如果只有 chun，则连续人声 >= 0.80s 且 chun >= 0.10
> 时按拖长的“长”兜底。短促的单独 chang/chun/ang、顺序错误、超过可选超时或
> 置信度不足都保持关灯。
> `ang` 仍会出现在 CHAR 日志里，但已不参与门控。

### 拖音保持（仅声强包络）

拖音期间不再注册 `en1` 第二路 KWS，也不使用评分门控。保持逻辑只有一条：

- 门控后记录本次 `env_fast` 峰值；
- `env_fast >= 15% × 本次峰值` 时保持 100%；
- 低于该门限持续 0.05 s 后释放，开始 2.5 s 衰减。

`E_k` / `E_d` 仅作为影子数据记录，不影响亮度：

```text
UNMEASURE cand=en1 ek=... ed=... ratio=... dur=... frames=...
```

`en1` 评分相关环境变量已移除；如果要重新实验，需要单独加回第二路 KWS。

## 降噪 / 音量链

`surplife_mic`（`/root/.asoundrc`）把麦克风 PCM 复制到 FIFO：

```text
hw:0,0 -> ALSA file 插件 -> /root/surplife/run/surplife_mic.pcm -> DSP 子进程
```

当前实机使用轻量 RMS 包络子进程（`_tap_reader_simple`），不做 FFT/谱减：

1. 20 ms attack / 80 ms release 快包络给亮度与拖音保持；
2. 100 ms attack / 500 ms release 慢包络给闪烁频率；
3. 维护 1.5 s 峰值和 0.8 s 峰值，供门控后参考；
4. 旧 FFT/谱减增强器已从源码移除，避免和 KWS 抢 CPU、拖慢包络。

## 注意

- 旧的 BLE 语音应用 `voice_kws.py` 和本应用不能同时运行：两者都要独占
  `hw:0,0`，同时启动会有一个打不开麦克风。
- A18/A19 的 PWM 复用由 MaixPy `pinmap` 设置；如果手动改过引脚复用，重启
  本应用即可重新设置。
- 退出时会把两路 duty 置 0 并 `enable=0`，避免灯常亮。

## 进程优先级

`voice_pwm.py` 启动时会调用 `raise_voice_priority()`：

- `nice` 默认 `-10`（需要 root）；
- `/proc/self/oom_score_adj` 默认 `-800`，降低被 OOM killer 选中的概率；
- DSP/PWM/判断子进程通过 fork 继承这两个值；
- UI 暂停期间，判断进程只做轻量时序拼装，不占麦克风。

可通过 `VOICE_NICE`、`VOICE_OOM_SCORE_ADJ` 调整。UI 的 `live_kws.py`
也会调用同一函数，避免 UI 资源占用高时先杀掉语音识别子进程。

## PWM 初始化注意

刚 export 的 PWM 通道 `period=0` 时，部分内核会拒绝对 `enable` 写 `0`
并返回 `EINVAL`。`SysfsPwm` 会把这视为“通道本来就是关闭的”，继续写
`period/duty`，避免 A18 在重启后初始化失败。

A19/PWM7 是辅助通道；它初始化失败时只记录警告，A18/PWM6 仍会继续待机呼吸。
