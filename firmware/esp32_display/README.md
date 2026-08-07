# Momir Vig ESP32 display firmware

LVGL UI for the 2.8" touchscreen: a big mana-value number with +/- targets,
and a "hold to summon" button that sends `summon_print` to the Pi over the
USB cable and shows the result. See `src/main.cpp` for the UI/protocol logic
and `esp32svc/serial_bridge.py` (in the main repo) for the Pi side and the
full wire protocol.

## Before this builds

Three pieces are genuinely board-specific and need the physical hardware in
hand to get right — this scaffold intentionally does not guess them:

1. **`include/lv_conf.h`** — not included here. Generate it from LVGL's
   template (`lv_conf_template.h` in the `lvgl` library, installed under
   `.pio/libdeps/esp32dev/lvgl/` after the first `pio run`), rename it
   `lv_conf.h`, drop it in `include/`, and set `LV_COLOR_DEPTH` to match the
   panel (16 for the common ILI9341/ST7789 modules) and enable `LV_USE_LOG`
   while bringing the board up.
2. **`include/User_Setup.h`** (TFT_eSPI) — pin mapping for the SPI display
   (CS/DC/RST/SCK/MOSI/MISO/backlight) and the driver chip select
   (`ILI9341_DRIVER` / `ST7789_DRIVER` / etc). These 2.8" boards vary by
   manufacturer even when they look identical — check the silkscreen/seller
   listing or probe continuity rather than assuming a pinout.
3. **Touch driver** — resistive (XPT2046, via TFT_eSPI's built-in support or
   the `XPT2046_Touchscreen` library) or capacitive (GT911, via
   `TAMCTec/gt911` or similar), plus calibration constants. `main.cpp` calls
   a small `touch_read()` shim (marked `TODO`) that needs to be filled in
   for whichever chip the board actually has.

## Build & flash

```
pio run                # after lv_conf.h / User_Setup.h are in place
pio run -t upload
pio device monitor
```

## Wiring

Connect the board to the Pi with a single USB cable — it's both the power
supply and the data link `esp32svc` reads on the Pi side (`/dev/momir-esp32`
via the udev rule in `scripts/99-momir-esp32.rules`). No separate GPIO/UART
wiring needed.
