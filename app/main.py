"""
FastAPI app: builds/loads the card database on startup, serves the control
UI, and exposes the summon/search/print/settings API.

Dev (Mac):  uvicorn app.main:app --reload
Pi:         started by scripts/momir.service on boot
"""
import base64
import io
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import build_db, card_art, config as config_module, db
from .printer import get_driver
from .printer.render import render_card

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_PENDING = 50


class AppState:
    def __init__(self):
        self.config: dict = {}
        self.printer_driver = None
        self.pending: "OrderedDict[str, dict]" = OrderedDict()

    def remember(self, card: dict, image) -> str:
        token = uuid.uuid4().hex
        self.pending[token] = {"card": card, "image": image}
        while len(self.pending) > MAX_PENDING:
            self.pending.popitem(last=False)
        return token


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    build_db.ensure_database(progress=print)
    state.config = config_module.load_config()
    state.printer_driver = get_driver(state.config["printer"])
    print(f"Loaded {db.card_count()} creature cards")
    print(f"Printer: {state.printer_driver.status()}")
    yield


app = FastAPI(title="Momir Vig", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class SummonRequest(BaseModel):
    cmc: int


class PreviewCardRequest(BaseModel):
    card_id: int


class PrintRequest(BaseModel):
    token: str


class SettingsUpdate(BaseModel):
    printer: dict | None = None
    art: dict | None = None


def _image_to_data_url(image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _build_preview(card: dict) -> dict:
    art_path = None
    if state.config.get("art", {}).get("enabled", True):
        art_path = card_art.fetch_art(card["name"], card.get("scryfall_oracle_id"))
    image = render_card(card, art_path, paper_width_mm=state.config["printer"]["paper_width_mm"])
    token = state.remember(card, image)
    return {
        "token": token,
        "card": card,
        "image": _image_to_data_url(image),
        "art_used": art_path is not None,
    }


@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/health")
def health():
    return {
        "card_count": db.card_count(),
        "printer": state.printer_driver.status(),
        "art_enabled": state.config.get("art", {}).get("enabled", True),
    }


@app.post("/api/summon")
def summon(req: SummonRequest):
    if req.cmc < 0:
        raise HTTPException(400, "cmc must be >= 0")
    card = db.random_creature_by_cmc(req.cmc)
    if card is None:
        raise HTTPException(404, f"No creatures found near mana value {req.cmc}")
    return _build_preview(card)


@app.get("/api/search")
def search(q: str = ""):
    return {"results": db.search_cards(q, limit=25)}


@app.get("/api/cmc_counts")
def cmc_counts():
    return db.cmc_counts()


@app.post("/api/rebuild_db")
def rebuild_db():
    try:
        build_db.download_atomic_cards()
        result = build_db.build_database()
    except requests.RequestException as e:
        raise HTTPException(502, f"download failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"rebuild failed: {e}")
    return {"ok": True, "card_count": result["card_count"]}


@app.post("/api/preview_card")
def preview_card(req: PreviewCardRequest):
    card = db.get_card_by_id(req.card_id)
    if card is None:
        raise HTTPException(404, "card not found")
    return _build_preview(card)


@app.post("/api/print")
def print_card(req: PrintRequest):
    pending = state.pending.get(req.token)
    if pending is None:
        raise HTTPException(404, "nothing pending for that token (summon/preview first)")
    result = state.printer_driver.print_image(pending["image"])
    return result


@app.get("/api/settings")
def get_settings():
    return state.config


@app.post("/api/settings")
def update_settings(update: SettingsUpdate):
    if update.printer:
        state.config["printer"].update(update.printer)
        state.printer_driver = get_driver(state.config["printer"])
    if update.art:
        state.config["art"].update(update.art)
    config_module.save_config(state.config)
    return state.config
