# Momir Vig ESP32 display firmware

LVGL UI for the 2.8" touchscreen: a big mana-value number with +/- targets,
and a "hold to summon" button that sends `summon_print` to the Pi over the
USB cable and shows the result. See `src/main.cpp` for the UI/protocol logic
and `esp32svc/serial_bridge.py` (in the main repo) for the Pi side and the
full wire protocol.

## Before this builds

Three pieces are genuinely board-specific. `include/lv_conf.h` and
`include/User_Setup.h` are committed here already, tested against a real
**Sunton/JC ESP32-2432S028R ("Cheap Yellow Display", CYD)** — if that's your
board, this builds and flashes as-is. If it's a different 2.8" board, treat
these as a reference and adjust:

1. **`include/lv_conf.h`** — generated from LVGL's template
   (`lv_conf_template.h` in the `lvgl` library, under
   `.pio/libdeps/esp32dev/lvgl/` after the first `pio run`), with
   `LV_COLOR_DEPTH 16`, `LV_TICK_CUSTOM 1`, `LV_USE_LOG 1`, and
   `LV_FONT_MONTSERRAT_48 1` (the mana-value display uses the 48px font,
   which LVGL doesn't enable by default — omitting this fails the build with
   an undeclared-identifier error, not a silent visual bug).
2. **`include/User_Setup.h`** (TFT_eSPI) — pin mapping for the SPI display.
   On the CYD: ILI9341, MISO 12 / MOSI 13 / SCLK 14 / CS 15 / DC 2 / no RST /
   backlight 21. Other 2.8" boards vary by manufacturer even when they look
   identical — check the silkscreen/seller listing or probe continuity
   rather than assuming a pinout.
3. **Touch driver** — on the CYD, the XPT2046 touch chip is **not** on the
   display's SPI bus (TFT_eSPI's built-in `TOUCH_CS` support assumes it is,
   and silently reads nothing if you wire it that way). It's on a separate
   set of GPIOs — CLK 25 / CS 33 / MOSI 32 / MISO 39 — driven in `main.cpp`
   via the `XPT2046_Bitbang` library (bit-banged, so it can't conflict with
   TFT_eSPI's own use of the hardware SPI peripheral) with calibration
   constants (`TOUCH_RAW_*`) already measured against a real unit — no axis
   swap needed, raw X/Y map directly to screen X/Y. A different touch chip
   (e.g. capacitive GT911) needs a different library entirely.

## Build & flash

```
pio run                # after lv_conf.h / User_Setup.h are in place
pio run -t upload
pio device monitor
```

If `pio run -t upload` fails partway through with a lost-connection or
`Error -9`/serial exception on macOS (seen with the CYD's onboard CH340
chip under macOS's built-in driver — plenty of USB power available, so it's
not a brownout), fall back to esptool's ROM bootloader mode directly, which
is slower but far more tolerant of a flaky link:

```
esptool.py --chip esp32 --port <PORT> --baud 57600 \
  --before default_reset --after hard_reset --no-stub \
  write_flash -z --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x10000 .pio/build/esp32dev/firmware.bin
```

(Only needed after the first full upload — that one writes the bootloader
and partition table too; see `esptool.py`'s `--help` if starting fresh.)

## Wiring

Connect the board to the Pi with a single USB cable — it's both the power
supply and the data link `esp32svc` reads on the Pi side (`/dev/momir-esp32`
via the udev rule in `scripts/99-momir-esp32.rules`). No separate GPIO/UART
wiring needed.
