# SG2002 片上温度传感器（TEMPSEN）读取说明

本文记录 SG2002 结温的读取方式，供低温温控板/上位机使用。目标场景是
**-40 °C 以上**的低温环境：SG2002 跑语音识别，外部温控板根据 SoC 结温决定
加热、风扇或降频策略。

## 结论

板端 Linux 已经通过 `cv181x-thermal` 驱动启用了 TEMPSEN，直接读：

```sh
cat /sys/class/thermal/thermal_zone0/temp     # 单位 m°C
```

某次实测示例：

```text
/sys/class/thermal/thermal_zone0/type = soc_thermal_0
/sys/class/thermal/thermal_zone0/temp = 43046   # 43.046 °C
```

推荐生产环境只读这个 sysfs 节点，不要自己重新配置 TEMPSEN 寄存器。

## 硬件/驱动信息

| 项目 | 值 |
| --- | --- |
| 温度传感器基地址 | `0x030E0000` |
| 平台设备 | `30e0000.thermal` |
| 内核驱动 | `cv181x-thermal`（`drivers/thermal/cv181x_thermal.c`） |
| compatible | `cvitek,cv181x-thermal` |
| 当前使能通道 | ch0（`reg_tempsen_sel=1`） |
| 自动测量周期 | `auto_cycle=0x100000`，prediv=24，约 **1.048 s** 更新一次 |

> TRM 21.8.3 的表格写作 `0x030A0000`，但 SG2002 实际板级 DT、平台设备和
> 驱动使用的是 `0x030E0000`；在 `0x030E0000` 读到 `version=0x00000101`，
> 且 ch0 结果与 sysfs 温度一致，因此以 `0x030E0000` 为准。

### 关键寄存器

| 偏移 | 名称 | 说明 |
| --- | --- | --- |
| `0x000` | `tempsen_version` | IP 版本，实测 `0x00000101` |
| `0x004` | `tempsen_ctrl` | bit0 `en`，bit7:4 `sel` |
| `0x008` | `tempsen_status` | bit0 busy |
| `0x00c` | `tempsen_set` | 模拟前端/斩波/累加/时钟分频 |
| `0x020` | `tempsen_ch0_result` | bit12:0 当前结果；bit28:16 历史最大值 |
| `0x024` | `tempsen_ch1_result` | 第二路；当前驱动未使能，读数为 0 |
| `0x064` | `tempsen_auto_period` | bit23:0 周期，bit31:24 预分频 |

### 温度换算

驱动 `cv181x_thermal.c` 使用的整数公式：

```text
temp_mC = raw * 1000 * 716 // 2048 - 273000
```

其中 `raw` 是 ch0 结果的低 13 位（`0x1FFF`）。等价于：

```text
temp_C = raw * 716 / 2048 - 273
       = raw * 0.349609375 - 273
```

实测对应关系：

| raw | 温度 |
| ---: | ---: |
| `0` | `-273.000 °C` |
| `666` | `-40.161 °C` |
| `904` | `43.046 °C` |
| `8191` | `2590.650 °C`（理论上限） |

`raw=666/667` 正好覆盖 -40 °C 附近，因此该传感器在目标低温范围内有足够
的码值分辨率；公式本身不截断负温，sysfs 也可以输出负的 m°C。

## 读取工具

新增 `app/sg2002_temp.py`，默认优先读 sysfs，失败时可退回直接读寄存器：

```sh
cd /root/surplife/app

./sg2002_temp.py                     # 单次，文本
./sg2002_temp.py --json              # 单次，JSON
./sg2002_temp.py --json --count 0 --interval 1   # 1 Hz 持续输出
./sg2002_temp.py --source reg --json # 强制走 devmem 读 TEMPSEN
```

JSON 示例：

```json
{"ts": 1793166105.15, "temp_c": 43.396, "temp_mc": 43396, "source": "reg", "raw": 905}
```

说明：

- `source=sysfs` 时没有 `raw` 字段；`source=reg` 时附带原始码值。
- 寄存器读取通过 busybox `devmem` 单次 32-bit 读完成，只读，不写配置。
- 在这块板子上用 Python `mmap` 直接映射 `/dev/mem` 做多字节读会触发
  SIGSEGV/SIGBUS，因此工具不使用 Python mmap；`devmem` 读取稳定。
- 工具不会启用/关闭传感器，也不会改阈值；内核驱动仍然拥有 TEMPSEN。

## 低温使用建议

1. **以 sysfs 为准。** 它经过内核驱动和 thermal framework，单位统一为 m°C，
   负温可直接表示。
2. **采样率不要高于传感器更新率。** 当前自动周期约 1.048 s，建议 1 Hz 或更慢；
   更快读取只会拿到重复值。
3. **区分结温和环境温度。** TEMPSEN 测的是芯片结温，不是温控板/环境温度。
   低温启动时 SoC 可能因自身功耗高于环境温度，温控策略应以结温为准。
4. **做实际低温标定。** 片上传感器存在工艺偏移；建议在气候箱中用外部参考
   传感器对比 -40/ -20/ 0/ 25/ 60 °C 几个点，必要时在温控板侧加偏移校准。
5. **不要在驱动运行时写 TEMPSEN 寄存器。** 需要第二路或改周期时，应改内核
   DT/驱动，而不是在用户态和驱动争用寄存器。
6. **对外发布温度。** 可让温控板读取串口/文件，或在 SG2002 上运行一个
   1 Hz 采样的小服务；建议输出 `temp_mc` 或保留 3 位小数的 `temp_c`，并带
   时间戳和来源字段。

## 验证记录

- `thermal_zone0` 类型 `soc_thermal_0`，sysfs 与寄存器换算一致。
- 实测 `devmem 0x030E0020` = `0x03950388`，低 13 位 `0x388=904`，
  换算 `43046 m°C`，与 sysfs `43046` 完全一致。
- `raw=666` 的单元测试结果为 `-40161 m°C`，覆盖 -40 °C 低温。
- `python3 -m unittest discover -s tests`：41 项通过。
