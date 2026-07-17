"""
Scryfall art lookup with an on-disk cache. Any network failure (including
"no internet" — expected when the Pi is only reachable over its isolated
control AP) is swallowed here; callers just get None and render a text-only
card.
"""
import re
import time
from pathlib import Path

import requests

ART_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "art_cache"
HEADERS = {"User-Agent": "MomirVigApp/1.0", "Accept": "*/*"}
REQUEST_TIMEOUT = 6
IMAGE_SIZE = "art_crop"  # just the illustration, no card frame/text baked in

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _cache_key(name: str, scryfall_oracle_id: str | None) -> str:
    if scryfall_oracle_id:
        return scryfall_oracle_id
    return _SAFE_NAME_RE.sub("_", name).strip("_").lower() or "card"


def _extract_image_url(card_json: dict) -> str | None:
    image_uris = card_json.get("image_uris") or {}
    if image_uris.get(IMAGE_SIZE):
        return image_uris[IMAGE_SIZE]
    for face in card_json.get("card_faces", []):
        face_uris = face.get("image_uris") or {}
        if face_uris.get(IMAGE_SIZE):
            return face_uris[IMAGE_SIZE]
    return None


def _lookup_by_oracle_id(oracle_id: str) -> str | None:
    resp = requests.get(
        "https://api.scryfall.com/cards/search",
        params={"q": f"oracleid:{oracle_id}", "unique": "prints", "order": "released"},
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    if not data:
        return None
    return _extract_image_url(data[0])


def _lookup_by_name(name: str) -> str | None:
    resp = requests.get(
        "https://api.scryfall.com/cards/named",
        params={"exact": name},
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 404:
        # Try fuzzy as a last resort (handles minor punctuation drift)
        resp = requests.get(
            "https://api.scryfall.com/cards/named",
            params={"fuzzy": name},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
    resp.raise_for_status()
    return _extract_image_url(resp.json())


def fetch_art(name: str, scryfall_oracle_id: str | None = None) -> Path | None:
    """Returns a local path to the card's art (PNG/JPG), fetching + caching
    it from Scryfall on first use. Returns None if unavailable (offline,
    not found, disabled, etc.) — never raises."""
    ART_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = _cache_key(name, scryfall_oracle_id)

    for ext in (".jpg", ".png"):
        cached = ART_CACHE_DIR / f"{key}{ext}"
        if cached.exists():
            return cached

    try:
        image_url = None
        if scryfall_oracle_id:
            image_url = _lookup_by_oracle_id(scryfall_oracle_id)
        if not image_url:
            image_url = _lookup_by_name(name)
        if not image_url:
            return None

        time.sleep(0.05)  # be polite to Scryfall's rate limit
        img_resp = requests.get(image_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        img_resp.raise_for_status()

        ext = ".png" if image_url.lower().endswith(".png") else ".jpg"
        dest = ART_CACHE_DIR / f"{key}{ext}"
        dest.write_bytes(img_resp.content)
        return dest
    except requests.RequestException as e:
        print(f"  [card_art] couldn't fetch art for '{name}': {e}")
        return None
