"""
Owns the wired serial link to the ESP32 physical display/control panel — the
single process that talks to the port so nothing else races for it, the same
role printsvc plays for the thermal printer. Drives a summon+print by
calling app/main.py's existing HTTP API (see serial_bridge.py) rather than
touching the card database or print pipeline directly.

Dev (Mac):  uvicorn esp32svc.main:app --reload --port 8003
Pi:         started by scripts/momir-esp32svc.service on boot, bound to
            127.0.0.1 only — same as printsvc, an internal dependency, not
            something phones/laptops on the LAN talk to.
"""
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .serial_bridge import SERIAL_PORT, SerialBridge


class AppState:
    def __init__(self):
        self.bridge = SerialBridge()
        self.stop_event = threading.Event()
        self.thread: "threading.Thread | None" = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.thread = threading.Thread(
        target=state.bridge.run_forever, args=(state.stop_event,), daemon=True
    )
    state.thread.start()
    yield
    state.stop_event.set()
    state.thread.join(timeout=5)


app = FastAPI(title="Momir ESP32 Display Service", lifespan=lifespan)


@app.get("/api/status")
def status():
    return {
        "serial_port": SERIAL_PORT,
        "connected": state.bridge.connected,
        "last_error": state.bridge.last_error,
        "last_command_at": state.bridge.last_command_at,
    }
