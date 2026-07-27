"""
Shared printer service: the single process that owns the actual PrinterDriver
connection (USB/serial/network). Both the momir card app and the upload app
call this over HTTP to print, rather than each holding their own driver —
python-escpos claims the USB interface for as long as the driver instance is
alive and only releases it on an explicit .close(), so two processes each
opening their own connection to the same hardware would race for it.

Dev (Mac):  uvicorn printsvc.main:app --reload --port 8002
Pi:         started by scripts/momir-printsvc.service on boot, bound to
            127.0.0.1 only — this is an internal dependency for the other two
            apps, not something phones/laptops on the LAN talk to directly.
"""
import base64
import io
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException
from PIL import Image

from app import config as config_module
from app.printer import get_driver


class AppState:
    def __init__(self):
        self.config: dict = {}
        self.driver = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.config = config_module.load_config()
    state.driver = get_driver(state.config["printer"])
    print(f"Printer: {state.driver.status()}")
    yield


app = FastAPI(title="Momir Print Service", lifespan=lifespan)


@app.get("/api/status")
def status():
    printer_config = state.config["printer"]
    return {
        "printer": state.driver.status(),
        "paper_width_mm": printer_config["paper_width_mm"],
        "card_layout": printer_config.get("card_layout", "custom"),
    }


@app.get("/api/settings")
def get_settings():
    return state.config["printer"]


@app.post("/api/settings")
def update_settings(update: dict = Body(...)):
    # Re-load from disk right before merging so we don't clobber a change
    # app/main.py made to the "art" section of the same file in between.
    cfg = config_module.load_config()
    cfg["printer"].update(update)
    state.config = cfg
    state.driver.close()
    state.driver = get_driver(state.config["printer"])
    config_module.save_config(state.config)
    return state.config["printer"]


@app.post("/api/print")
def print_image(image: str = Body(..., embed=True)):
    try:
        decoded = base64.b64decode(image)
        pil_image = Image.open(io.BytesIO(decoded))
        pil_image.load()
    except Exception as e:
        raise HTTPException(400, f"invalid image: {e}")
    return state.driver.print_image(pil_image)
