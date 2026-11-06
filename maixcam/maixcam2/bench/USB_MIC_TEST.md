# MaixCAM2 external USB microphone test

Test date: 2026-11-04

## Initial finding

The stock kernel did not include `snd-usb-audio`:

```text
CONFIG_SND_USB=y
# CONFIG_SND_USB_AUDIO is not set
```

The USB codec was visible in host mode as `08bb:2902 PCM2902 Audio Codec`, but
no ALSA card was created.

## Fix applied

Exact MaixCAM2 kernel source and the matching ARM GCC 9.2-2019.12 toolchain were
used to build:

```text
snd-hwdep.ko
snd-rawmidi.ko
snd-usbmidi-lib.ko
snd-usb-audio.ko
```

They are installed under `/lib/modules/4.19.125/kernel/sound/`, and
`depmod -a 4.19.125` has been run.

## Working state

After:

```sh
modprobe snd-usb-audio
systemctl stop usb-gadget.service
echo host > /sys/class/usb_role/8000000.dwc3-role-switch/role
```

the external microphone appears:

```text
card 1: Device [USB PnP Sound Device], device 0: USB Audio [USB Audio]
```

Capture test:

```text
arecord -D plughw:1,0 -f S16_LE -r 16000 -c 1 -d 3 /tmp/usbmic_test.wav
```

produced a valid 3-second 16 kHz mono WAV with non-zero PCM data. A 2-second
test through `record_usb_mic.sh` gave RMS 0.0096 and peak 0.0669. The ALSA
capture path therefore works.

The microphone's default capture gain was 0 dB; setting
`amixer -c 1 cset numid=3 16` raises it to 23.81 dB.

The application path was also checked:

```text
./run_voice.sh --local-pwm --usb-mic
```

Its child `arecord` opened `/dev/snd/pcmC1D0c`, i.e. the USB card rather than
the built-in card 0. A30/PWM6 was active during that test, and shutdown
restored A30 to UART1_TX.

## Remaining caveat

A TTS playback test through the built-in speaker produced only low-level
acoustic pickup, and SenseVoice did not recognize useful text from that
recording. This is an acoustic/placement/input-gain issue, not an ALSA opening
failure. A real person speaking close to the microphone should be used for the
final intelligibility test.

## Usage files

See `/root/JLU_LEDLAB/usb_audio/`:

- `enable_usb_mic.sh`
- `disable_usb_mic.sh`
- `record_usb_mic.sh`
- `README.md` (full build/install recipe)

Current state has been restored to USB device mode:

```text
role=device
usb-gadget.service=active
```
