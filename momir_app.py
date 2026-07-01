"""
momir_app.py — Momir Vig Web App

A Flask web app that powers a paper Momir Vig game.
Select a mana value → get a random creature with its Scryfall art.

Run locally:
    python momir_app.py

On Raspberry Pi:
    python momir_app.py --host 0.0.0.0 --port 5000

Then open http://<raspberry-pi-ip>:5000
"""

import json
import sqlite3
from pathlib import Path
import urllib.request, urllib.parse

from flask import Flask, jsonify, render_template

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "momir.db"
app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# Simple in-memory image URL cache (keyed by card name)
_image_cache = {}

# ── Scryfall helpers ──────────────────────────────────────────────────────────

def make_headers():
    """Return headers required by Scryfall API (User-Agent + Accept)."""
    return {
        "User-Agent": "MomirVigApp/1.0",
        "Accept": "*/*"
    }

def extract_image_url(data):
    """
    Extract the "large" image URL from Scryfall card JSON.
    Handles double‑faced cards (DFCs) where image_uris is inside card_faces.
    """
    image_url = data.get("image_uris", {}).get("large")
    if not image_url:
        faces = data.get("card_faces", [])
        if faces:
            image_url = faces[0].get("image_uris", {}).get("large")
    return image_url

def resolve_scryfall_image(card):
    """
    Resolve the large image URL for a card using Scryfall's /cards/named endpoint.
    First tries exact match, then fuzzy match if needed.
    """
    name = card["name"].strip()
    if name in _image_cache:
        card["image_url"] = _image_cache[name]
        return card

    headers = make_headers()

    # ── Attempt exact match ──
    url = f'https://api.scryfall.com/cards/named?exact={urllib.parse.quote(name)}'
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            card["image_url"] = extract_image_url(data)
            _image_cache[name] = card["image_url"]
            if card["image_url"]:
                print(f"  ✓ Resolved {name}")
            else:
                print(f"  ⚠ No image for {name}")
            return card

    except urllib.error.HTTPError as e:
        error_body = e.read().decode(errors='replace')
        print(f"  ✗ Exact lookup failed for '{name}': HTTP {e.code}")
        print(f"    Response: {error_body}")

        # ── Fuzzy fallback ──
        fuzzy_url = f'https://api.scryfall.com/cards/named?fuzzy={urllib.parse.quote(name)}'
        req_fuzzy = urllib.request.Request(fuzzy_url, headers=headers)
        try:
            with urllib.request.urlopen(req_fuzzy, timeout=8) as resp:
                data = json.loads(resp.read())
                card["image_url"] = extract_image_url(data)
                _image_cache[name] = card["image_url"]
                print(f"  ✓ Fuzzy fallback resolved {name}")
                return card
        except urllib.error.HTTPError as e2:
            error_body2 = e2.read().decode(errors='replace')
            print(f"  ✗ Fuzzy also failed: HTTP {e2.code} – {error_body2}")
            card["image_url"] = None
            _image_cache[name] = None
            return card
        except Exception as ex:
            print(f"  ✗ Fuzzy exception: {ex}")
            card["image_url"] = None
            _image_cache[name] = None
            return card

    except Exception as e:
        print(f"  ✗ Network/other error for {name}: {e}")
        card["image_url"] = None
        _image_cache[name] = None
        return card

# ── DB Helpers ────────────────────────────────────────────────────────────────

def get_db():
    """Return a read-only SQLite connection with row factory."""
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con

def get_random_creature(cmc: int):
    """
    Fetch one random creature at the given mana value (CMC).
    Returns a dict or None.
    """
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT name, mana_value, type_line, subtypes, oracle_text,
               power, toughness, scryfall_id
        FROM creatures
        WHERE CAST(mana_value AS INTEGER) = ?
        ORDER BY RANDOM()
        LIMIT 1
    """, (cmc,))
    row = cur.fetchone()
    con.close()

    if row is None:
        return None

    card = dict(row)
    return card

def get_cmc_counts():
    """Get creature counts per CMC for the UI."""
    con = get_db()
    cur = con.cursor()
    cur.execute("""
        SELECT CAST(mana_value AS INTEGER) AS cmc, COUNT(*) AS count
        FROM creatures
        GROUP BY cmc
        ORDER BY cmc
    """)
    counts = {row[0]: row[1] for row in cur.fetchall()}
    con.close()
    return counts

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the main page with CMC counts."""
    counts = get_cmc_counts()
    max_count = max(counts.values()) if counts else 1
    return render_template("index.html", counts=counts, max_count=max_count)

@app.route("/api/random/<int:cmc>")
def api_random(cmc):
    """
    Return a random creature at the given CMC as JSON.
    If none found at exact CMC, walks outward ±1, ±2, etc. (like Momir Vig).
    """
    if cmc < 0:
        return jsonify({"error": "CMC must be >= 0"}), 400

    card = get_random_creature(cmc)

    # Retry nearby CMCs (like real Momir Vig when you have no card at exact CMC)
    if card is None:
        for delta in range(1, 6):
            for offset in (delta, -delta):
                trial = cmc + offset
                if trial >= 0:
                    card = get_random_creature(trial)
                    if card:
                        card["_original_cmc"] = cmc
                        card["_actual_cmc"] = trial
                        break
            if card:
                break

    if card is None:
        return jsonify({"error": f"No creatures found near CMC {cmc}"}), 404

    # Resolve art via Scryfall
    card = resolve_scryfall_image(card)

    return jsonify(card)

@app.route("/api/counts")
def api_counts():
    """Return CMC counts as JSON."""
    return jsonify(get_cmc_counts())

# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Momir Vig Web App")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    print(f"  ╔══════════════════════════════════╗")
    print(f"  ║     Momir Vig Paper Simulator    ║")
    print(f"  ╠══════════════════════════════════╣")
    print(f"  ║  DB: {str(DB_PATH.name):<28} ║")
    print(f"  ║  URL: http://{args.host}:{args.port:<4}           ║")
    print(f"  ╚══════════════════════════════════╝")

    app.run(host=args.host, port=args.port, debug=args.debug)