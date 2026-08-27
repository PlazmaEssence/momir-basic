"""
Print-from-upload app: lets anyone on the network print an arbitrary image or
block of text on the same thermal printer the momir card app uses. Renders
locally (resize/dither for images, word-wrap for text) then hands the
finished image to printsvc, which owns the actual printer connection.

Dev (Mac):  uvicorn upload.main:app --reload --port 8001
Pi:         started by scripts/momir-upload.service on boot
"""
import base64
import hashlib
import io
import os
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel

from .render import render_image, render_qr, render_text

STATIC_DIR = Path(__file__).resolve().parent / "static"
PRINTSVC_URL = os.environ.get("MOMIR_PRINTSVC_URL", "http://127.0.0.1:8002")

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp"}
MAX_TEXT_CHARS = 5000
FONT_SIZE_CHOICES = ("small", "medium", "large")
MAX_QR_CHARS = 800

app = FastAPI(title="Momir Vig Print Upload")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class TextPrintRequest(BaseModel):
    text: str
    font_size: str = "medium"
    bold_title: bool = False


class QrRequest(BaseModel):
    data: str


def _asset_version(filename: str) -> str:
    return hashlib.md5((STATIC_DIR / filename).read_bytes()).hexdigest()[:8]


@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text()
    for asset in ("style.css", "app.js"):
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={_asset_version(asset)}")
    return HTMLResponse(html)


def _printsvc_status() -> dict | None:
    try:
        resp = requests.get(f"{PRINTSVC_URL}/api/status", timeout=3)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        return None


def _paper_width_mm() -> float:
    status = _printsvc_status()
    if status is None:
        raise HTTPException(503, "print service unreachable")
    return status["paper_width_mm"]


def _send_to_printsvc(image: Image.Image) -> dict:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    try:
        resp = requests.post(f"{PRINTSVC_URL}/api/print", json={"image": encoded}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        return {"ok": False, "detail": f"print service unreachable: {e}"}


@app.get("/api/health")
def health():
    status = _printsvc_status()
    printer_status = status["printer"] if status else {
        "driver": "unknown",
        "connected": False,
        "detail": "print service unreachable",
    }
    return {"printer": printer_status}


@app.post("/api/print/image")
async def print_image(file: UploadFile):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(400, f"unsupported file type: {file.content_type}")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"file too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
    try:
        source = Image.open(io.BytesIO(data))
        source.load()
    except Exception as e:
        raise HTTPException(400, f"could not read image: {e}")
    image = render_image(source, _paper_width_mm())
    return _send_to_printsvc(image)


@app.post("/api/print/text")
def print_text(req: TextPrintRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "text is required")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(400, f"text too long (max {MAX_TEXT_CHARS} characters)")
    if req.font_size not in FONT_SIZE_CHOICES:
        raise HTTPException(400, f"font_size must be one of {FONT_SIZE_CHOICES}")
    image = render_text(text, _paper_width_mm(), font_size=req.font_size, bold_title=req.bold_title)
    return _send_to_printsvc(image)


def _qr_image(data: str) -> Image.Image:
    data = data.strip()
    if not data:
        raise HTTPException(400, "data is required")
    if len(data) > MAX_QR_CHARS:
        raise HTTPException(400, f"data too long (max {MAX_QR_CHARS} characters)")
    return render_qr(data, _paper_width_mm())


@app.post("/api/qr/preview")
def qr_preview(req: QrRequest):
    image = _qr_image(req.data)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return {"image": base64.b64encode(buf.getvalue()).decode("ascii")}


@app.post("/api/print/qr")
def print_qr(req: QrRequest):
    return _send_to_printsvc(_qr_image(req.data))
