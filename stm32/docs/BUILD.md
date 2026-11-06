# Build and flash

Requirements:

- CMake >= 3.22
- Ninja (for the checked-in presets) or Make
- `arm-none-eabi-gcc` with newlib
- ST-Link/OpenOCD or another SWD flashing tool

With the checked-in presets:

```sh
cmake --preset Debug
cmake --build --preset Debug
```

The post-build step generates:

- `build/Debug/PWM-Heater.elf`
- `build/Debug/PWM-Heater.hex`
- `build/Debug/PWM-Heater.bin`

If Ninja is not available:

```sh
cmake -S . -B build/Debug -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_TOOLCHAIN_FILE=cmake/gcc-arm-none-eabi.cmake
cmake --build build/Debug -j
```

Flashing is intentionally not hard-coded to a particular probe. Use the normal
SWD header H1 and the project’s generated ELF/HEX/BIN.

USART3 is the local debug console: 115200 8N1 on PB10/PB11 (H1).
