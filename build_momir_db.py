"""
build_momir_db.py

Converts AtomicCards.json.gz (from mtgjson.com) into a trimmed SQLite database
containing only paper-legal creatures, for use in a Momir Vig paper format app.
"""

import gzip
import json
import sqlite3
import sys
from pathlib import Path


INPUT_FILE = Path("AtomicCards.json.gz")
OUTPUT_DB  = Path("momir.db")


print(f"Loading {INPUT_FILE} ...")

opener = gzip.open if INPUT_FILE.suffix == ".gz" else open
with opener(INPUT_FILE, "rt", encoding="utf-8") as f:
    raw = json.load(f)

all_cards = raw["data"]
print(f"  {len(all_cards):,} unique card names found")


def is_valid_creature(faces: list) -> bool:
    face = faces[0]
    if "Creature" not in face.get("types", []):
        return False
    if not face.get("printings"):
        return False
    return True


creatures = {name: faces for name, faces in all_cards.items() if is_valid_creature(faces)}
print(f"  {len(creatures):,} creatures after filtering")


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
        subtypes    TEXT,
        oracle_text TEXT,
        power       TEXT,
        toughness   TEXT,
        image_url   TEXT
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
    
    # Get image URL from Scryfall ID if available
    image_url = None
    identifiers = face.get("identifiers", {})
    scryfall_id = identifiers.get("scryfallId")
    if scryfall_id:
        image_url = f"https://cards.scryfall.io/large/front/{scryfall_id[0]}/{scryfall_id[1]}/{scryfall_id}.jpg"

    rows.append((
        name,
        float(mana_value),
        face.get("type"),
        subtypes_str,
        face.get("text"),
        face.get("power"),
        face.get("toughness"),
        image_url,
    ))

cur.executemany("""
    INSERT INTO creatures (name, mana_value, type_line, subtypes, oracle_text, power, toughness, image_url)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", rows)

con.commit()
con.close()

print(f"  {len(rows):,} creatures written to {OUTPUT_DB}")
if skipped:
    print(f"  {skipped} cards skipped (missing manaValue)")


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
print("\nDone!")
