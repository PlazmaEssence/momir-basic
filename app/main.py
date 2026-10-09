"""
FastAPI app: builds/loads the card database on startup, serves the control
UI, and exposes the summon/search/print/settings API.

Dev (Mac):  uvicorn app.main:app --reload
Pi:         started by scripts/momir.service on boot
"""
import base64
import hashlib
import io
import os
import subprocess
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import build_db, build_tokens, card_art, config as config_module, db, tokens
from .printer.render import render_card, render_card_full, render_card_full_preview

STATIC_DIR = Path(__file__).resolve().parent / "static"
REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_PENDING = 50

# The printsvc process owns the actual printer connection (see printsvc/main.py
# for why); this app never touches a PrinterDriver directly, it just calls
# printsvc over localhost HTTP. Fallback used only for rendering a preview
# when printsvc happens to be unreachable — printing itself will still report
# a clear error at that point rather than silently succeeding.
PRINTSVC_URL = os.environ.get("MOMIR_PRINTSVC_URL", "http://127.0.0.1:8002")
FALLBACK_RENDER_CONFIG = {"paper_width_mm": 80, "card_layout": "custom"}


def _detect_version() -> str:
    """Short git commit hash of the running checkout, or "unknown" if this
    isn't a git repo / git isn't installed / anything else goes wrong."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"


class AppState:
    def __init__(self):
        self.art_config: dict = {}
        self.version: str = "unknown"
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
    state.art_config = config_module.load_config()["art"]
    state.version = _detect_version()
    print(f"Loaded {db.card_count()} creature cards")
    print(f"Version: {state.version}")
    yield


app = FastAPI(title="Momir Vig", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class SummonRequest(BaseModel):
    cmc: int


class PreviewCardRequest(BaseModel):
    card_id: int


class PrintRequest(BaseModel):
    token: str


class RegenerateRequest(BaseModel):
    token: str


class TokenPreviewRequest(BaseModel):
    # Either a curated token's id, or the fields of a one-off custom token.
    token_id: str | None = None
    name: str | None = None
    type_line: str | None = None
    power: str | None = None
    toughness: str | None = None
    text: str | None = None


class SettingsUpdate(BaseModel):
    printer: dict | None = None
    art: dict | None = None


def _encode_png_base64(image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _image_to_data_url(image) -> str:
    return f"data:image/png;base64,{_encode_png_base64(image)}"


def _printsvc_status() -> dict | None:
    try:
        resp = requests.get(f"{PRINTSVC_URL}/api/status", timeout=3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def _printer_render_config() -> dict:
    """paper_width_mm/card_layout needed to render a preview. Falls back to
    defaults if printsvc is unreachable so summon/preview still work — the
    print itself will report a clear error at that point instead."""
    status = _printsvc_status()
    if status is None:
        return FALLBACK_RENDER_CONFIG
    return {"paper_width_mm": status["paper_width_mm"], "card_layout": status["card_layout"]}


def _printsvc_get_settings() -> dict:
    try:
        resp = requests.get(f"{PRINTSVC_URL}/api/settings", timeout=3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise HTTPException(503, f"print service unreachable: {e}")


def _printsvc_print(image) -> dict:
    try:
        resp = requests.post(f"{PRINTSVC_URL}/api/print", json={"image": _encode_png_base64(image)}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"ok": False, "detail": f"print service unreachable: {e}"}


def _build_preview(card: dict) -> dict:
    printer_render_config = _printer_render_config()
    paper_width_mm = printer_render_config["paper_width_mm"]
    art_enabled = state.art_config.get("enabled", True)
    layout = printer_render_config["card_layout"]

    if layout == "full_card" and art_enabled:
        full_path = card_art.fetch_art(card["name"], card.get("scryfall_oracle_id"), image_size="large")
        if full_path is not None:
            # The printer always gets the dithered B&W render; the web
            # preview shows the original color art instead.
            image = render_card_full(full_path, paper_width_mm=paper_width_mm)
            preview_image = render_card_full_preview(full_path)
            token = state.remember(card, image)
            return {
                "token": token,
                "card": card,
                "image": _image_to_data_url(preview_image),
                "art_used": True,
            }
        # full card image unavailable (offline/not found) — fall back to custom render below

    art_path = card_art.fetch_art(card["name"], card.get("scryfall_oracle_id")) if art_enabled else None
    image = render_card(card, art_path, paper_width_mm=paper_width_mm)
    token = state.remember(card, image)
    return {
        "token": token,
        "card": card,
        "image": _image_to_data_url(image),
        "art_used": art_path is not None,
    }


def _asset_version(filename: str) -> str:
    return hashlib.md5((STATIC_DIR / filename).read_bytes()).hexdigest()[:8]


@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text()
    for asset in ("style.css", "app.js"):
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={_asset_version(asset)}")
    return HTMLResponse(html)


@app.get("/api/health")
def health():
    status = _printsvc_status()
    printer_status = status["printer"] if status else {
        "driver": "unknown",
        "connected": False,
        "detail": "print service unreachable",
    }
    return {
        "card_count": db.card_count(),
        "printer": printer_status,
        "art_enabled": state.art_config.get("enabled", True),
        "version": state.version,
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
        build_db.download_set_list()
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


@app.post("/api/regenerate")
def regenerate(req: RegenerateRequest):
    pending = state.pending.get(req.token)
    if pending is None:
        raise HTTPException(404, "nothing pending for that token (summon/preview first)")
    return _build_preview(pending["card"])


@app.get("/api/tokens")
def list_tokens():
    full = tokens.full_tokens()
    return {"common": tokens.TOKENS, "full_count": len(full)}


@app.get("/api/tokens/search")
def search_tokens(q: str = ""):
    return {"results": tokens.search(q)}


@app.get("/api/tokens/build_status")
def token_build_status():
    return {**build_tokens.STATUS, "full_count": len(tokens.full_tokens())}


@app.post("/api/tokens/rebuild")
def rebuild_tokens():
    # A few hundred MB of downloads, so run it in the background and let the
    # UI poll /api/tokens/build_status instead of holding a request open.
    started = build_tokens.start_background()
    return {"ok": True, "started": started}


@app.post("/api/tokens/preview")
def preview_token(req: TokenPreviewRequest):
    if req.token_id:
        token = tokens.get_token(req.token_id)
        if token is None:
            raise HTTPException(404, "token not found")
    else:
        name = (req.name or "").strip()
        if not name:
            raise HTTPException(400, "token needs a name")
        token = {
            "name": name[:40],
            "type_line": (req.type_line or "Token").strip()[:60],
            "power": (req.power or "").strip()[:3],
            "toughness": (req.toughness or "").strip()[:3],
            "text": (req.text or "").strip()[:300],
        }
    art_path = None
    source = tokens.art_source(token) if state.art_config.get("enabled", True) else None
    if source:
        art_path = card_art.fetch_token_art(*source)
    image = tokens.render_token(token, paper_width_mm=_printer_render_config()["paper_width_mm"], art_path=art_path)
    # Same pending-token bookkeeping as cards, so the existing /api/print works as-is.
    return {
        "token": state.remember(token, image),
        "card": token,
        "image": _image_to_data_url(image),
        "is_token": True,
        "art_used": art_path is not None,
        "art_wanted": source is not None,
    }


@app.post("/api/print")
def print_card(req: PrintRequest):
    pending = state.pending.get(req.token)
    if pending is None:
        raise HTTPException(404, "nothing pending for that token (summon/preview first)")
    return _printsvc_print(pending["image"])


@app.get("/api/settings")
def get_settings():
    return {"printer": _printsvc_get_settings(), "art": state.art_config}


@app.post("/api/settings")
def update_settings(update: SettingsUpdate):
    if update.printer:
        try:
            resp = requests.post(f"{PRINTSVC_URL}/api/settings", json=update.printer, timeout=10)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise HTTPException(503, f"print service unreachable: {e}")
    if update.art:
        # Re-load from disk right before merging so we don't clobber a change
        # printsvc made to the "printer" section of the same file in between.
        cfg = config_module.load_config()
        cfg["art"].update(update.art)
        config_module.save_config(cfg)
        state.art_config = cfg["art"]
    return {"printer": _printsvc_get_settings(), "art": state.art_config}
