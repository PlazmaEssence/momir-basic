"""Owns the wired serial link to the ESP32 display/control panel. Reads
newline-delimited JSON commands off the port and drives a summon+print by
calling app/main.py's existing HTTP API over localhost — the same two calls
the browser UI already makes (POST /api/summon, then POST /api/print) — so
no changes to app/main.py's summon/print/token logic are needed.

Protocol (115200 8N1 by default, one JSON object per line):
  ESP32 -> Pi: {"id": <int>, "cmd": "summon_print", "cmc": <int>}
  ESP32 -> Pi: {"cmd": "ping"}
  Pi -> ESP32 (success): {"id": <int>, "ok": true, "name": <str>, "cmc": <int>}
  Pi -> ESP32 (failure): {"id": <int>, "ok": false, "detail": <str>}
  Pi -> ESP32:            {"cmd": "pong"}

The port is opened lazily and reopened with backoff on any error, mirroring
the "swallow and degrade" pattern used elsewhere for optional hardware
(app/card_art.py's offline fallback, app/printer/escpos_driver.py's lazy
reconnect) — an unplugged or not-yet-flashed ESP32 shouldn't take the
service down. pyserial is synchronous, so this runs in a background thread
(see main.py) rather than as an asyncio task like panel's ReconcileLoop.
"""
import json
import os
import time

import requests
import serial

APP_URL = os.environ.get("MOMIR_ESP32_APP_URL", "http://127.0.0.1:8000")
SERIAL_PORT = os.environ.get("MOMIR_ESP32_SERIAL_PORT", "/dev/momir-esp32")
BAUD_RATE = int(os.environ.get("MOMIR_ESP32_BAUD", "115200"))
RECONNECT_DELAY_SEC = 5


class SerialBridge:
    def __init__(self):
        self._conn: "serial.Serial | None" = None
        self.last_error: str | None = None
        self.last_command_at: float | None = None

    @property
    def connected(self) -> bool:
        return self._conn is not None

    def _connect(self) -> None:
        try:
            self._conn = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
            self.last_error = None
            print(f"[esp32svc] connected to {SERIAL_PORT} @ {BAUD_RATE}")
        except Exception as e:
            self._conn = None
            self.last_error = str(e)

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _send(self, message: dict) -> None:
        if self._conn is None:
            return
        try:
            self._conn.write((json.dumps(message) + "\n").encode("utf-8"))
        except Exception as e:
            self.last_error = str(e)
            self._close()

    def _summon_and_print(self, msg: dict) -> dict:
        req_id = msg.get("id")
        cmc = msg.get("cmc")
        if not isinstance(cmc, int) or cmc < 0:
            return {"id": req_id, "ok": False, "detail": "cmc must be a non-negative integer"}

        try:
            resp = requests.post(f"{APP_URL}/api/summon", json={"cmc": cmc}, timeout=10)
            resp.raise_for_status()
            summoned = resp.json()
        except requests.RequestException as e:
            return {"id": req_id, "ok": False, "detail": f"summon failed: {e}"}

        try:
            resp = requests.post(f"{APP_URL}/api/print", json={"token": summoned["token"]}, timeout=30)
            resp.raise_for_status()
            printed = resp.json()
        except requests.RequestException as e:
            return {"id": req_id, "ok": False, "detail": f"print failed: {e}"}

        if not printed.get("ok"):
            return {"id": req_id, "ok": False, "detail": printed.get("detail", "print failed")}

        card = summoned["card"]
        return {"id": req_id, "ok": True, "name": card["name"], "cmc": card.get("cmc_int", cmc)}

    def _handle_command(self, msg: dict) -> None:
        cmd = msg.get("cmd")
        if cmd == "ping":
            self._send({"cmd": "pong"})
        elif cmd == "summon_print":
            self.last_command_at = time.time()
            self._send(self._summon_and_print(msg))
        else:
            self._send({"id": msg.get("id"), "ok": False, "detail": f"unknown cmd: {cmd}"})

    def run_forever(self, stop_event) -> None:
        """Blocking read loop — run in a background thread. `stop_event` is a
        threading.Event checked between reconnect attempts and read timeouts
        so the service can shut down promptly."""
        while not stop_event.is_set():
            if self._conn is None:
                self._connect()
                if self._conn is None:
                    stop_event.wait(RECONNECT_DELAY_SEC)
                    continue
            try:
                line = self._conn.readline()
            except Exception as e:
                self.last_error = str(e)
                self._close()
                continue
            if not line:
                continue  # read timeout with no data — loop back and re-check stop_event
            try:
                msg = json.loads(line.decode("utf-8").strip())
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self.last_error = f"malformed line: {e}"
                continue
            self._handle_command(msg)
        self._close()
