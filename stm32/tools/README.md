# Host-side SPI references

- `stm32_protocol.py` — SPI v1 frame/TLV pack/unpack, CRC16, status parsing.
- `maixcam_spi_link.py` — minimal MaixCAM SPI master transport. It auto-selects
  MaixCAM2 SPI2 (B18/B19/B20/B21) or MaixCAM/MaixCAM-Pro SPI4 (A22-A25). It is
  a reference for the future lightweight link process; it is not wired into
  `voice_pwm.py` yet.
- `test_stm32_protocol.py` — host-only unit tests.

Run:

```sh
cd tools
python3 -m unittest -v test_stm32_protocol.py
```

The STM32 side implementation is in `Core/Src/app_spi_link.c`,
`Core/Src/app_perf.c`, `Core/Src/board_pwm.c`, and `Core/Src/glyph_map.c`.
