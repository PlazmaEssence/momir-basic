"""Loads/creates data/config.json — the one place printer + art settings live."""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "printer": {
        # "mock" (renders a PNG to output/, no hardware) or "escpos" (real USB thermal printer)
        "driver": "mock",
        "connection": "usb",  # "usb" | "serial" | "network" (escpos only)
        "usb_vendor_id": "0x0000",
        "usb_product_id": "0x0000",
        "serial_device": "/dev/serial0",
        "serial_baudrate": 19200,
        "network_host": "",
        "network_port": 9100,
        "paper_width_mm": 80,
        # "custom" (name/cost/type/text + art crop) or "full_card" (raw Scryfall card image)
        "card_layout": "custom",
    },
    "art": {
        "enabled": True,
    },
}


def _merge_defaults(cfg: dict, defaults: dict) -> dict:
    for key, value in defaults.items():
        if key not in cfg:
            cfg[key] = value
        elif isinstance(value, dict) and isinstance(cfg[key], dict):
            _merge_defaults(cfg[key], value)
    return cfg


def load_config() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg = _merge_defaults(cfg, DEFAULT_CONFIG)
    return cfg


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
