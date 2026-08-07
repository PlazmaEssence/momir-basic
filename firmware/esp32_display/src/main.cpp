// Momir Vig ESP32 display/control panel.
//
// UI: a big mana-value number with +/- targets to adjust it locally (no
// round trip needed just to step it), and a "hold to summon" button — a
// press-and-hold of ~700ms (shown as a filling arc) sends a summon_print
// command to the Pi and shows the result. See esp32svc/serial_bridge.py in
// the main repo for the Pi side and the authoritative protocol doc.
//
// Talks to the Pi over the same USB cable used to power/flash the board:
// newline-delimited JSON on Serial, 115200 8N1.
//   -> {"id": <int>, "cmd": "summon_print", "cmc": <int>}
//   -> {"cmd": "ping"}
//   <- {"id": <int>, "ok": true, "name": <str>, "cmc": <int>}
//   <- {"id": <int>, "ok": false, "detail": <str>}
//   <- {"cmd": "pong"}
//
// Display/touch driver setup (TFT_eSPI's User_Setup.h, lv_conf.h, and the
// touch chip shim below) is board-specific and deliberately left as TODOs —
// see README.md.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include <TFT_eSPI.h>

// ---- Tunables --------------------------------------------------------

static const int CMC_MIN = 0;
static const int CMC_MAX = 16;
static const uint32_t HOLD_TO_SUMMON_MS = 700;
static const uint32_t RESULT_DISPLAY_MS = 2000;
static const uint32_t REQUEST_TIMEOUT_MS = 15000;  // summon+print involves a real print job
static const uint32_t PING_INTERVAL_MS = 4000;
static const uint32_t PONG_TIMEOUT_MS = 9000;  // >2 missed pings before showing "disconnected"

// ---- Display/LVGL plumbing --------------------------------------------

static const uint16_t SCREEN_W = 320;
static const uint16_t SCREEN_H = 240;

TFT_eSPI tft = TFT_eSPI();
static lv_disp_draw_buf_t draw_buf;
static lv_color_t buf1[SCREEN_W * 40];

static void disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p) {
  uint32_t w = area->x2 - area->x1 + 1;
  uint32_t h = area->y2 - area->y1 + 1;
  tft.startWrite();
  tft.setAddrWindow(area->x1, area->y1, w, h);
  tft.pushColors((uint16_t *)&color_p->full, w * h, true);
  tft.endWrite();
  lv_disp_flush_ready(disp);
}

// TODO: fill in for the board's actual touch chip (XPT2046 resistive or
// GT911 capacitive are the common options on these 2.8" panels) — see
// README.md. Returning false/not pressed keeps the build compiling with the
// touch axis effectively disabled until this is wired up.
static bool touch_read_raw(int16_t *x, int16_t *y) {
  (void)x;
  (void)y;
  return false;
}

static void touch_read(lv_indev_drv_t *indev, lv_indev_data_t *data) {
  int16_t x, y;
  if (touch_read_raw(&x, &y)) {
    data->state = LV_INDEV_STATE_PRESSED;
    data->point.x = x;
    data->point.y = y;
  } else {
    data->state = LV_INDEV_STATE_RELEASED;
  }
}

// ---- Serial protocol ---------------------------------------------------

static int next_req_id = 1;
static int pending_req_id = -1;
static uint32_t pending_since_ms = 0;
static uint32_t last_ping_ms = 0;
static uint32_t last_pong_ms = 0;

static void send_json(JsonDocument &doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

static void send_summon_print(int cmc) {
  StaticJsonDocument<128> doc;
  pending_req_id = next_req_id++;
  doc["id"] = pending_req_id;
  doc["cmd"] = "summon_print";
  doc["cmc"] = cmc;
  pending_since_ms = millis();
  send_json(doc);
}

static void send_ping() {
  StaticJsonDocument<32> doc;
  doc["cmd"] = "ping";
  send_json(doc);
  last_ping_ms = millis();
}

// ---- App state -----------------------------------------------------

enum class UiState { IDLE, HOLDING, AWAITING_RESPONSE, RESULT };

static UiState ui_state = UiState::IDLE;
static int cmc_value = 4;
static uint32_t hold_started_ms = 0;
static uint32_t result_shown_ms = 0;
static String result_text;
static bool result_ok = false;

static lv_obj_t *cmc_label;
static lv_obj_t *hold_arc;
static lv_obj_t *hold_btn;
static lv_obj_t *status_label;
static lv_obj_t *conn_dot;

static void refresh_cmc_label() {
  lv_label_set_text_fmt(cmc_label, "%d", cmc_value);
}

static void set_ui_state(UiState next) {
  ui_state = next;
  switch (next) {
    case UiState::IDLE:
      lv_label_set_text(status_label, "Hold to summon + print");
      lv_arc_set_value(hold_arc, 0);
      break;
    case UiState::AWAITING_RESPONSE:
      lv_label_set_text(status_label, "Summoning...");
      break;
    default:
      break;
  }
}

static void on_minus_clicked(lv_event_t *e) {
  if (ui_state != UiState::IDLE) return;
  if (cmc_value > CMC_MIN) {
    cmc_value--;
    refresh_cmc_label();
  }
}

static void on_plus_clicked(lv_event_t *e) {
  if (ui_state != UiState::IDLE) return;
  if (cmc_value < CMC_MAX) {
    cmc_value++;
    refresh_cmc_label();
  }
}

static void on_hold_btn_event(lv_event_t *e) {
  lv_event_code_t code = lv_event_get_code(e);
  if (code == LV_EVENT_PRESSED) {
    if (ui_state != UiState::IDLE) return;
    hold_started_ms = millis();
    set_ui_state(UiState::HOLDING);
  } else if (code == LV_EVENT_PRESSING) {
    if (ui_state != UiState::HOLDING) return;
    uint32_t held = millis() - hold_started_ms;
    int pct = (int)((held * 100) / HOLD_TO_SUMMON_MS);
    if (pct > 100) pct = 100;
    lv_arc_set_value(hold_arc, pct);
    if (held >= HOLD_TO_SUMMON_MS) {
      set_ui_state(UiState::AWAITING_RESPONSE);
      send_summon_print(cmc_value);
    }
  } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
    if (ui_state == UiState::HOLDING) {
      // released early — cancel back to idle
      set_ui_state(UiState::IDLE);
    }
  }
}

static void build_ui() {
  lv_obj_t *scr = lv_scr_act();

  status_label = lv_label_create(scr);
  lv_obj_align(status_label, LV_ALIGN_TOP_MID, 0, 8);
  lv_label_set_text(status_label, "Hold to summon + print");

  conn_dot = lv_obj_create(scr);
  lv_obj_set_size(conn_dot, 10, 10);
  lv_obj_set_style_radius(conn_dot, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_bg_color(conn_dot, lv_palette_main(LV_PALETTE_GREY), 0);
  lv_obj_align(conn_dot, LV_ALIGN_TOP_RIGHT, -8, 8);

  cmc_label = lv_label_create(scr);
  lv_obj_set_style_text_font(cmc_label, &lv_font_montserrat_48, 0);
  lv_obj_align(cmc_label, LV_ALIGN_CENTER, 0, -20);
  refresh_cmc_label();

  lv_obj_t *minus_btn = lv_btn_create(scr);
  lv_obj_set_size(minus_btn, 60, 60);
  lv_obj_align(minus_btn, LV_ALIGN_LEFT_MID, 20, -20);
  lv_obj_add_event_cb(minus_btn, on_minus_clicked, LV_EVENT_CLICKED, NULL);
  lv_obj_t *minus_label = lv_label_create(minus_btn);
  lv_label_set_text(minus_label, "-");
  lv_obj_center(minus_label);

  lv_obj_t *plus_btn = lv_btn_create(scr);
  lv_obj_set_size(plus_btn, 60, 60);
  lv_obj_align(plus_btn, LV_ALIGN_RIGHT_MID, -20, -20);
  lv_obj_add_event_cb(plus_btn, on_plus_clicked, LV_EVENT_CLICKED, NULL);
  lv_obj_t *plus_label = lv_label_create(plus_btn);
  lv_label_set_text(plus_label, "+");
  lv_obj_center(plus_label);

  hold_arc = lv_arc_create(scr);
  lv_obj_set_size(hold_arc, 90, 90);
  lv_arc_set_rotation(hold_arc, 270);
  lv_arc_set_bg_angles(hold_arc, 0, 360);
  lv_arc_set_range(hold_arc, 0, 100);
  lv_arc_set_value(hold_arc, 0);
  lv_obj_remove_style(hold_arc, NULL, LV_PART_KNOB);  // no draggable knob, this is a progress display
  lv_obj_clear_flag(hold_arc, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_align(hold_arc, LV_ALIGN_BOTTOM_MID, 0, -15);

  hold_btn = lv_btn_create(scr);
  lv_obj_set_size(hold_btn, 70, 70);
  lv_obj_align(hold_btn, LV_ALIGN_BOTTOM_MID, 0, -25);
  lv_obj_add_event_cb(hold_btn, on_hold_btn_event, LV_EVENT_ALL, NULL);
  lv_obj_t *hold_label = lv_label_create(hold_btn);
  lv_label_set_text(hold_label, "Summon");
  lv_obj_center(hold_label);
}

// ---- Serial line reading -------------------------------------------

static String rx_buffer;

static void handle_incoming_line(const String &line) {
  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, line) != DeserializationError::Ok) return;

  const char *cmd = doc["cmd"] | "";
  if (strcmp(cmd, "pong") == 0) {
    last_pong_ms = millis();
    return;
  }

  if (!doc.containsKey("id")) return;
  int id = doc["id"];
  if (id != pending_req_id || ui_state != UiState::AWAITING_RESPONSE) return;

  bool ok = doc["ok"] | false;
  result_ok = ok;
  if (ok) {
    const char *name = doc["name"] | "?";
    result_text = String("Printed: ") + name;
  } else {
    const char *detail = doc["detail"] | "error";
    result_text = String("Error: ") + detail;
  }
  lv_label_set_text(status_label, result_text.c_str());
  result_shown_ms = millis();
  ui_state = UiState::RESULT;
  pending_req_id = -1;
}

static void poll_serial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      if (rx_buffer.length() > 0) {
        handle_incoming_line(rx_buffer);
        rx_buffer = "";
      }
    } else if (c != '\r') {
      rx_buffer += c;
    }
  }
}

// ---- Arduino entry points -----------------------------------------

void setup() {
  Serial.begin(115200);

  tft.begin();
  tft.setRotation(1);

  lv_init();
  lv_disp_draw_buf_init(&draw_buf, buf1, NULL, SCREEN_W * 40);

  static lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = SCREEN_W;
  disp_drv.ver_res = SCREEN_H;
  disp_drv.flush_cb = disp_flush;
  disp_drv.draw_buf = &draw_buf;
  lv_disp_drv_register(&disp_drv);

  static lv_indev_drv_t indev_drv;
  lv_indev_drv_init(&indev_drv);
  indev_drv.type = LV_INDEV_TYPE_POINTER;
  indev_drv.read_cb = touch_read;
  lv_indev_drv_register(&indev_drv);

  build_ui();
}

void loop() {
  lv_timer_handler();
  poll_serial();

  uint32_t now = millis();

  if (now - last_ping_ms > PING_INTERVAL_MS) {
    send_ping();
  }
  bool connected = (now - last_pong_ms) < PONG_TIMEOUT_MS;
  lv_obj_set_style_bg_color(
      conn_dot,
      connected ? lv_palette_main(LV_PALETTE_GREEN) : lv_palette_main(LV_PALETTE_RED), 0);

  if (ui_state == UiState::AWAITING_RESPONSE && now - pending_since_ms > REQUEST_TIMEOUT_MS) {
    lv_label_set_text(status_label, "Error: no response from Pi");
    result_shown_ms = now;
    ui_state = UiState::RESULT;
    pending_req_id = -1;
  }

  if (ui_state == UiState::RESULT && now - result_shown_ms > RESULT_DISPLAY_MS) {
    set_ui_state(UiState::IDLE);
  }

  delay(5);
}
