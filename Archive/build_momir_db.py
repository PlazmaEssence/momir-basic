"""
build_momir_db.py

Converts AtomicCards.json.gz (from mtgjson.com) into a trimmed SQLite database
containing only paper-legal creatures, for use in a Momir Vig paper format app.

Usage:
    python build_momir_db.py                          # uses defaults
    python build_momir_db.py AtomicCards.json.gz momir.db

Downloads:
    https://mtgjson.com/api/v5/AtomicCards.json.gz
"""

import gzip
import json
import sqlite3
import sys
from pathlib import Path


# ── Config ────────────────────────────────────────────────────────────────────

INPUT_FILE = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("AtomicCards.json.gz")
OUTPUT_DB  = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("momir.db")


# ── Load JSON ─────────────────────────────────────────────────────────────────

print(f"Loading {INPUT_FILE} ...")

opener = gzip.open if INPUT_FILE.suffix == ".gz" else open
with opener(INPUT_FILE, "rt", encoding="utf-8") as f:
    raw = json.load(f)

# AtomicCards structure: { "data": { "Card Name": [ {face}, ... ], ... }, "meta": {...} }
all_cards = raw["data"]
print(f"  {len(all_cards):,} unique card names found")


# ── Filter ────────────────────────────────────────────────────────────────────

def is_valid_creature(faces: list) -> bool:
    """
    AtomicCards stores each card as a list of faces (usually one, two for DFCs).
    We use the first face for checks.

    A card qualifies if:
      - Its types list contains 'Creature'
      - It has at least one printing (i.e. it's a real card)
      - It is not a funny/un-set card (isFunny flag)
    
    Note: AtomicCards has no 'availability' field — that's printing-specific.
    We use 'isFunny' to exclude joke/un-set cards, and 'printings' to confirm
    the card has actually been printed.
    """
    face = faces[0]

    # Must be a creature
    if "Creature" not in face.get("types", []):
        return False

    # Must have at least one printing
    if not face.get("printings"):
        return False

    return True


creatures = {name: faces for name, faces in all_cards.items() if is_valid_creature(faces)}
print(f"  {len(creatures):,} creatures after filtering")


# ── Build SQLite DB ───────────────────────────────────────────────────────────

if OUTPUT_DB.exists():
    OUTPUT_DB.unlink()

con = sqlite3.connect(OUTPUT_DB)
cur = con.cursor()

cur.execute("""
    CREATE TABLE creatures (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        mana_value  REAL    NOT NULL,
        type_line   TEXT,
        subtypes    TEXT,               -- pipe-separated e.g. "Elf|Warrior"
        oracle_text TEXT,
        power       TEXT,               -- TEXT to handle */X values
        toughness   TEXT
    )
""")

cur.execute("""
    CREATE INDEX idx_mana_value ON creatures (mana_value)
""")

rows = []
skipped = 0

for name, faces in creatures.items():
    face = faces[0]

    mana_value = face.get("manaValue")
    if mana_value is None:
        skipped += 1
        continue

    subtypes_str = "|".join(face.get("subtypes", [])) or None

    rows.append((
        name,
        float(mana_value),
        face.get("type"),
        subtypes_str,
        face.get("text"),
        face.get("power"),
        face.get("toughness"),
    ))

cur.executemany("""
    INSERT INTO creatures (name, mana_value, type_line, subtypes, oracle_text, power, toughness)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", rows)

con.commit()
con.close()

print(f"  {len(rows):,} creatures written to {OUTPUT_DB}")
if skipped:
    print(f"  {skipped} cards skipped (missing manaValue)")


# ── Quick sanity check ────────────────────────────────────────────────────────

con = sqlite3.connect(OUTPUT_DB)
cur = con.cursor()

print("\nSanity check — creature counts by CMC:")
cur.execute("""
    SELECT mana_value, COUNT(*) as count
    FROM creatures
    GROUP BY mana_value
    ORDER BY mana_value
""")
for mana_value, count in cur.fetchall():
    bar = "█" * min(count // 10, 60)
    print(f"  CMC {int(mana_value):>2}: {count:>4}  {bar}")

print("\nSample random creature at CMC 5:")
cur.execute("""
    SELECT name, mana_value, type_line, power, toughness
    FROM creatures
    WHERE mana_value = 5
    ORDER BY RANDOM()
    LIMIT 1
""")
row = cur.fetchone()
if row:
    name, mv, tl, p, t = row
    print(f"  {name} (CMC {int(mv)}) — {tl} — {p}/{t}")

con.close()
print("\nDone! Use momir.db in your web app.")
