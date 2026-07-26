"""
FastAPI control panel: toggles momir.service and manages wlan0 Wi-Fi
client/AP switching over nmcli.

Dev (Mac):  uvicorn panel.main:app --reload --port 8080
Pi:         started by scripts/momir-panel.service on boot, port 80
"""
import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import network, service_ctl

STATIC_DIR = Path(__file__).resolve().parent / "static"
RECONCILE_INTERVAL_SEC = 20
STARTUP_DELAY_SEC = 5


class ReconcileLoop:
    """Owns the background task that keeps wlan0 on the best available
    connection (highest-priority saved Wi-Fi in range, else idle if
    Ethernet is up, else the AP). Runs on a timer, and can be nudged to
    run sooner right after a saved-network mutation."""

    def __init__(self):
        self._hysteresis: dict = {}
        self._wake = asyncio.Event()

    async def run_forever(self):
        await asyncio.sleep(STARTUP_DELAY_SEC)  # let NetworkManager settle after boot
        while True:
            try:
                network.reconcile(self._hysteresis)
            except Exception as e:
                print(f"reconcile error: {e}")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=RECONCILE_INTERVAL_SEC)
            except asyncio.TimeoutError:
                pass

    def nudge(self):
        self._wake.set()


reconcile_loop = ReconcileLoop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(reconcile_loop.run_forever())
    yield
    task.cancel()


app = FastAPI(title="Momir Vig Control Panel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class AddNetworkRequest(BaseModel):
    ssid: str
    password: str


class ReorderRequest(BaseModel):
    order: list[str]


def _asset_version(filename: str) -> str:
    return hashlib.md5((STATIC_DIR / filename).read_bytes()).hexdigest()[:8]


@app.get("/")
def index():
    html = (STATIC_DIR / "index.html").read_text()
    for asset in ("style.css", "app.js"):
        html = html.replace(f"/static/{asset}", f"/static/{asset}?v={_asset_version(asset)}")
    return HTMLResponse(html)


@app.get("/api/momir/status")
def momir_status():
    return service_ctl.status()


@app.post("/api/momir/start")
def momir_start():
    try:
        service_ctl.start()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return service_ctl.status()


@app.post("/api/momir/stop")
def momir_stop():
    try:
        service_ctl.stop()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return service_ctl.status()


@app.post("/api/momir/enable")
def momir_enable():
    try:
        service_ctl.enable()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return service_ctl.status()


@app.post("/api/momir/disable")
def momir_disable():
    try:
        service_ctl.disable()
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    return service_ctl.status()


@app.get("/api/network/status")
def network_status():
    return network.get_status()


@app.get("/api/network/scan")
def network_scan():
    return {"ssids": network.scan_wifi()}


@app.get("/api/network/saved")
def network_saved():
    return {"networks": network.list_saved_wifi()}


@app.post("/api/network/saved")
def network_add(req: AddNetworkRequest):
    ssid = req.ssid.strip()
    if not ssid:
        raise HTTPException(400, "ssid is required")
    if len(req.password) < 8:
        raise HTTPException(400, "password must be at least 8 characters (WPA2 requirement)")
    try:
        conn_id = network.add_wifi(ssid, req.password)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    reconcile_loop.nudge()
    return {"id": conn_id}


@app.delete("/api/network/saved/{conn_id}")
def network_remove(conn_id: str):
    try:
        network.remove_wifi(conn_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    reconcile_loop.nudge()
    return {"ok": True}


@app.post("/api/network/saved/reorder")
def network_reorder(req: ReorderRequest):
    try:
        network.reorder_wifi(req.order)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    reconcile_loop.nudge()
    return {"networks": network.list_saved_wifi()}
