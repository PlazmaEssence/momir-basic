"""
Builds data/tokens.json — every distinct paper token/emblem MTGJSON knows
about — for the Tokens panel's search.

MTGJSON has no standalone token file: tokens only appear in each set's own
file (`<CODE>.json.gz`, in a `tokens` array) and inside the huge AllPrintings
file (~180MB, far too much to parse on a Pi). So we use SetList.json.gz (also
used by build_db.py) to find the sets that have tokens, fetch those set files
one at a time (~1MB each), keep only their tokens, and dedupe across sets.
Run on demand — via the Tokens panel button or `python3 -m app.build_tokens` —
not on every startup, since it's a few hundred MB of downloads.

A set that fails to download is skipped and counted rather than failing the
whole build, same "swallow and degrade" idea as card_art.py.
"""
import gzip
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import build_db

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TOKENS_PATH = DATA_DIR / "tokens.json"
SET_URL = "https://mtgjson.com/api/v5/{code}.json.gz"
SCHEMA_VERSION = 2
WORKERS = 4

# Shared progress for the UI to poll while a background build runs.
STATUS = {"running": False, "done": 0, "total": 0, "skipped": 0, "count": None, "error": None}
_lock = threading.Lock()


def _fetch_set_tokens(code: str) -> list | None:
    for attempt in range(2):
        try:
            resp = requests.get(SET_URL.format(code=code), timeout=(10, 120))
            resp.raise_for_status()
            return json.loads(gzip.decompress(resp.content))["data"].get("tokens") or []
        except Exception:
            time.sleep(1 + attempt)
    return None


# Token sets also hold art cards, substitute cards, checklists, ads, bosses,
# etc. — all typed "Card" or something else non-token. Keep real tokens and
# emblems, plus these tracker cards that players actually print at the table.
MARKER_NAMES = {
    "The Monarch", "City's Blessing", "Energy Reserve", "Radiation",
    "On an Adventure", "Foretell", "Plot",
}


def _normalize(raw: dict) -> dict | None:
    name = raw.get("faceName") or raw.get("name")
    type_line = raw.get("type") or ""
    types = raw.get("types") or []
    if not name or not type_line:
        return None
    if "Token" not in types and "Emblem" not in types and name not in MARKER_NAMES:
        return None
    return {
        "name": name,
        "type_line": type_line,
        "power": raw.get("power") or "",
        "toughness": raw.get("toughness") or "",
        "text": (raw.get("text") or "").strip(),
        "colors": raw.get("colors") or [],
        # Scryfall id of this printing, for fetching art (see card_art.fetch_token_art).
        # Double-faced tokens share one Scryfall card, so remember which face this is.
        "scryfall_id": (raw.get("identifiers") or {}).get("scryfallId") or "",
        "face": "back" if raw.get("side") == "b" else "front",
    }


def _key(t: dict) -> tuple:
    return (t["name"], t["type_line"], t["power"], t["toughness"], tuple(sorted(t["colors"])), t["text"])


def _token_set_codes(progress) -> list[str]:
    if not build_db.SETLIST_PATH.exists():
        build_db.download_set_list(progress=progress)
    with gzip.open(build_db.SETLIST_PATH, "rt", encoding="utf-8") as f:
        sets = json.load(f)["data"]
    # tokenSetCode marks sets that have tokens; skip Arena/MTGO-only sets.
    # Newest first: the first printing we see for a token supplies its art, so
    # this picks the most recent illustration.
    wanted = [s for s in sets if s.get("tokenSetCode") and not s.get("isOnlineOnly")]
    wanted.sort(key=lambda s: s.get("releaseDate") or "", reverse=True)
    return [s["code"] for s in wanted]


def build_tokens(path: Path = TOKENS_PATH, progress=print) -> dict:
    codes = _token_set_codes(progress)
    with _lock:
        STATUS.update(done=0, total=len(codes), skipped=0)
    progress(f"Fetching tokens from {len(codes)} sets...")

    merged: dict[tuple, dict] = {}
    skipped = 0

    def work(code):
        return code, _fetch_set_tokens(code)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for code, raw_tokens in pool.map(work, codes):
            if raw_tokens is None:
                skipped += 1
            for raw in raw_tokens or []:
                t = _normalize(raw)
                if t is None:
                    continue
                entry = merged.setdefault(_key(t), {**t, "printings": 0})
                entry["printings"] += 1
                if not entry["scryfall_id"] and t["scryfall_id"]:
                    entry["scryfall_id"], entry["face"] = t["scryfall_id"], t["face"]
            with _lock:
                STATUS["done"] += 1
                STATUS["skipped"] = skipped

    tokens = sorted(merged.values(), key=lambda t: (-t["printings"], t["name"]))
    for t in tokens:
        t["id"] = "t" + hashlib.sha1(repr(_key(t)).encode()).hexdigest()[:10]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA_VERSION, "built_at": int(time.time()), "tokens": tokens}))
    tmp.replace(path)
    progress(f"Saved {len(tokens)} tokens ({skipped} sets skipped)")
    return {"count": len(tokens), "skipped": skipped}


def start_background(progress=print) -> bool:
    """Starts a build on a thread unless one is already running."""
    with _lock:
        if STATUS["running"]:
            return False
        STATUS.update(running=True, error=None, count=None)

    def run():
        try:
            result = build_tokens(progress=progress)
            with _lock:
                STATUS["count"] = result["count"]
        except Exception as e:
            with _lock:
                STATUS["error"] = str(e)
        finally:
            with _lock:
                STATUS["running"] = False

    threading.Thread(target=run, daemon=True).start()
    return True


if __name__ == "__main__":
    build_tokens()
