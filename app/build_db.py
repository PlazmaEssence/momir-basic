"""
Parses data/AtomicCards.json.gz into data/momir.sqlite3.

AtomicCards.json dedupes MTGJSON by card name; multi-faced cards (MDFC,
transform, split, adventure) store one array entry per face, each carrying
its own `side` ("a"/"b"), `faceName`, and mana value. We only keep the
front/primary face (`side` is None or "a") so a card is represented by the
face you'd actually cast, and skip "A-" prefixed names, which are
Alchemy/Arena-only rebalances with no paper printing.
"""
import gzip
import json
import sqlite3
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SOURCE_PATH = DATA_DIR / "AtomicCards.json.gz"
DB_PATH = DATA_DIR / "momir.sqlite3"
ATOMIC_CARDS_URL = "https://mtgjson.com/api/v5/AtomicCards.json.gz"

SCHEMA = """
CREATE TABLE cards (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    mana_cost TEXT,
    cmc REAL NOT NULL,
    cmc_int INTEGER NOT NULL,
    type_line TEXT,
    power TEXT,
    toughness TEXT,
    text TEXT,
    color_identity TEXT,
    set_code TEXT,
    scryfall_oracle_id TEXT
);
CREATE INDEX idx_cards_cmc_int ON cards(cmc_int);

CREATE VIRTUAL TABLE cards_fts USING fts5(name, content='cards', content_rowid='id');

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _source_fingerprint(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def needs_rebuild(source_path: Path = SOURCE_PATH, db_path: Path = DB_PATH) -> bool:
    if not db_path.exists():
        return True
    if not source_path.exists():
        # nothing we can do about it here; let the caller surface the error
        return False
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        row = con.execute("SELECT value FROM meta WHERE key = 'source_fingerprint'").fetchone()
        con.close()
    except sqlite3.Error:
        return True
    if row is None:
        return True
    return row[0] != _source_fingerprint(source_path)


def _iter_creature_faces(cards_data: dict):
    for name, entries in cards_data.items():
        if name.startswith("A-"):
            continue
        for entry in entries:
            if entry.get("side") not in (None, "a"):
                continue
            types = entry.get("types") or []
            if "Creature" not in types and "Summon" not in types:
                continue
            yield entry


def download_atomic_cards(source_path: Path = SOURCE_PATH, progress=print) -> None:
    """Downloads the latest AtomicCards.json.gz from MTGJSON, replacing
    whatever's already at source_path."""
    progress(f"Downloading {ATOMIC_CARDS_URL} ...")
    tmp_path = source_path.with_suffix(".json.gz.tmp")
    with requests.get(ATOMIC_CARDS_URL, stream=True, timeout=(10, 300)) as resp:
        resp.raise_for_status()
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp_path.replace(source_path)
    progress(f"Downloaded {source_path.name} ({source_path.stat().st_size / 1e6:.1f} MB)")


def build_database(source_path: Path = SOURCE_PATH, db_path: Path = DB_PATH, progress=print) -> dict:
    if not source_path.exists():
        raise FileNotFoundError(
            f"Source file not found: {source_path}. Place AtomicCards.json.gz in the data/ directory."
        )

    progress(f"Reading {source_path.name} ...")
    with gzip.open(source_path, "rt", encoding="utf-8") as f:
        payload = json.load(f)

    meta = payload.get("meta", {})
    cards_data = payload["data"]

    tmp_db_path = db_path.with_suffix(".sqlite3.tmp")
    tmp_db_path.unlink(missing_ok=True)

    con = sqlite3.connect(tmp_db_path)
    con.executescript(SCHEMA)

    start = time.monotonic()
    count = 0
    rows = []
    for entry in _iter_creature_faces(cards_data):
        display_name = entry.get("faceName") or entry.get("name")
        cmc = entry.get("manaValue")
        if cmc is None:
            cmc = entry.get("convertedManaCost", 0.0)
        cmc = float(cmc or 0.0)
        printings = entry.get("printings") or []
        rows.append((
            display_name,
            entry.get("manaCost"),
            cmc,
            int(cmc),
            entry.get("type"),
            entry.get("power"),
            entry.get("toughness"),
            entry.get("text"),
            ",".join(entry.get("colorIdentity") or []),
            printings[0] if printings else None,
            (entry.get("identifiers") or {}).get("scryfallOracleId"),
        ))
        count += 1

    con.executemany(
        """INSERT INTO cards
           (name, mana_cost, cmc, cmc_int, type_line, power, toughness, text,
            color_identity, set_code, scryfall_oracle_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    con.execute("INSERT INTO cards_fts(rowid, name) SELECT id, name FROM cards")

    fingerprint = _source_fingerprint(source_path)
    con.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [
            ("source_fingerprint", fingerprint),
            ("source_date", meta.get("date", "")),
            ("source_version", meta.get("version", "")),
            ("card_count", str(count)),
            ("built_at", str(int(time.time()))),
        ],
    )
    con.commit()
    con.close()

    tmp_db_path.replace(db_path)

    elapsed = time.monotonic() - start
    progress(f"Built {count} creature cards into {db_path.name} in {elapsed:.1f}s")
    return {"card_count": count, "elapsed_seconds": elapsed}


def ensure_database(source_path: Path = SOURCE_PATH, db_path: Path = DB_PATH, progress=print) -> None:
    if needs_rebuild(source_path, db_path):
        build_database(source_path, db_path, progress=progress)
    else:
        progress(f"{db_path.name} is up to date, skipping rebuild")


if __name__ == "__main__":
    build_database()
