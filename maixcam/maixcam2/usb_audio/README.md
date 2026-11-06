# MaixCAM2 USB Audio Class 模块安装与使用

MaixCAM2 出厂内核是 `4.19.125`，配置里有：

```text
CONFIG_MODULES=y
CONFIG_SND_USB=y
# CONFIG_SND_USB_AUDIO is not set
```

因此 USB Audio 设备能被 USB 主机枚举，但没有 ALSA/USB Audio Card 驱动。

## 1. 编译结果

本目录对应安装包已经编译并安装到：

```text
/lib/modules/4.19.125/kernel/sound/core/snd-hwdep.ko
/lib/modules/4.19.125/kernel/sound/core/snd-rawmidi.ko
/lib/modules/4.19.125/kernel/sound/usb/snd-usbmidi-lib.ko
/lib/modules/4.19.125/kernel/sound/usb/snd-usb-audio.ko
```

`depmod -a 4.19.125` 已执行，`modprobe snd-usb-audio` 可以自动加载依赖。

## 2. 复现编译方法

源码：

```sh
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/sipeed/maix_ax620e_sdk_kernel.git
cd maix_ax620e_sdk_kernel
git sparse-checkout set linux/linux-4.19.125
```

工具链必须使用和内核构建一致的 ARM GNU Toolchain 9.2-2019.12：

```sh
wget https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu-a/9.2-2019.12/binrel/gcc-arm-9.2-2019.12-x86_64-aarch64-none-linux-gnu.tar.xz
tar -xf gcc-arm-9.2-2019.12-x86_64-aarch64-none-linux-gnu.tar.xz
export PATH=$PWD/gcc-arm-9.2-2019.12-x86_64-aarch64-none-linux-gnu/bin:$PATH
export CROSS_COMPILE=aarch64-none-linux-gnu-
```

配置：

```sh
cd linux/linux-4.19.125
make ARCH=arm64 O=/tmp/kbuild \
  axera_AX630C_emmc_arm64_k419_sipeed_maixcam2_defconfig
scripts/config --file /tmp/kbuild/.config \
  -m SND_USB_AUDIO -m SND_HWDEP -m SND_RAWMIDI
make ARCH=arm64 O=/tmp/kbuild olddefconfig
make ARCH=arm64 O=/tmp/kbuild modules_prepare -j4
make ARCH=arm64 O=/tmp/kbuild M=sound/core modules -j4
make ARCH=arm64 O=/tmp/kbuild M=sound/usb modules -j4
```

生成的模块：

```text
/tmp/kbuild/sound/core/snd-hwdep.ko
/tmp/kbuild/sound/core/snd-rawmidi.ko
/tmp/kbuild/sound/usb/snd-usbmidi-lib.ko
/tmp/kbuild/sound/usb/snd-usb-audio.ko
```

必须使用 GCC 9.2 工具链。用 Ubuntu 的 GCC 15 编译出的模块会出现：

```text
module snd_hwdep: unsupported RELA relocation: 311
```

即模块格式/重定位与 4.19.125 模块加载器不兼容。

## 3. 安装

```sh
mkdir -p /lib/modules/4.19.125/kernel/sound/core
mkdir -p /lib/modules/4.19.125/kernel/sound/usb
cp snd-hwdep.ko snd-rawmidi.ko /lib/modules/4.19.125/kernel/sound/core/
cp snd-usbmidi-lib.ko snd-usb-audio.ko /lib/modules/4.19.125/kernel/sound/usb/
depmod -a 4.19.125
```

如果出现 `modules.order/modules.builtin` 警告，不影响模块加载。

## 4. 启用 USB 麦克风

MaixCAM2 的 USB-C 默认是 device/gadget 模式，不能枚举 USB 麦克风。需要：

1. 停止 USB gadget；
2. 切换 USB role 为 host；
3. 加载 USB Audio 模块。

使用：

```sh
cd /root/JLU_LEDLAB/usb_audio
./enable_usb_mic.sh
```

或手动：

```sh
modprobe snd-usb-audio
systemctl stop usb-gadget.service
echo host > /sys/class/usb_role/8000000.dwc3-role-switch/role
arecord -l
```

预期出现：

```text
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
```

PCM2902/CM108 类设备的 `Mic Capture Volume` 默认常为 0，可调到最大：

```sh
amixer -c 1 cset numid=3 16
```

## 5. 录音测试

```sh
cd /root/JLU_LEDLAB/usb_audio
./record_usb_mic.sh /tmp/usbmic_test.wav 3
```

## 6. 恢复 device 模式

```sh
cd /root/JLU_LEDLAB/usb_audio
./disable_usb_mic.sh
```

该脚本会卸载模块、切回 device，并重启 `usb-gadget.service`。

## 7. 已验证结果

- `insmod`/`modprobe snd-usb-audio` 成功；
- ALSA 出现 `card 1: USB PnP Sound Device`；
- `arecord -D plughw:1,0` 能录出 3 秒 16kHz 单声道 PCM；
- 录音文件非全零，说明 USB 音频采集通路工作；
- 但本轮用扬声器回放 TTS 做声学测试时，USB 麦克风拾音电平很低，
  SenseVoice 未识别出有效内容。需要用真人贴近麦克风或检查麦克风输入
  接线/增益后再做语音识别验证。

## 8. 注意事项

- 当前 USB host 模式会关闭 gadget 网络功能；SSH 仍可走 WiFi。
- 不要同时用 USB device 模式和 USB 麦克风，二者角色冲突。
- 如果应用继续使用 `maix.audio.Recorder`，需要确认它默认选择的 ALSA
  card；USB 麦克风是 card 1，必要时通过 ALSA 配置或 `arecord` 管道选择
  card 1。
