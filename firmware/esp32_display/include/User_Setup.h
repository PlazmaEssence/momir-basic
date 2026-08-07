// TFT_eSPI pin/driver config for the Sunton/JC ESP32-2432S028R
// ("Cheap Yellow Display", CYD) — ILI9341 2.8" SPI TFT.
//
// Touch (XPT2046) is NOT on this bus on this board — it's wired to a
// separate set of GPIOs (CLK 25 / MOSI 32 / MISO 39 / CS 33 / IRQ 36) driven
// directly via the XPT2046_Touchscreen library on its own SPI instance in
// main.cpp. TFT_eSPI's built-in TOUCH_CS support assumes touch shares the
// display's SPI bus, which is wrong for this board and silently reads
// nothing — deliberately left undefined here.

#define USER_SETUP_LOADED 1

#define ILI9341_DRIVER

#define TFT_WIDTH  240
#define TFT_HEIGHT 320

#define TFT_MISO 12
#define TFT_MOSI 13
#define TFT_SCLK 14
#define TFT_CS   15
#define TFT_DC    2
#define TFT_RST  -1   // tied to EN, no dedicated reset pin
#define TFT_BL   21
#define TFT_BACKLIGHT_ON HIGH

#define LOAD_GLCD
#define LOAD_FONT2
#define LOAD_FONT4
#define LOAD_FONT6
#define LOAD_FONT7
#define LOAD_FONT8
#define LOAD_GFXFF
#define SMOOTH_FONT

#define SPI_FREQUENCY       55000000
#define SPI_READ_FREQUENCY  20000000

#define SUPPORT_TRANSACTIONS
