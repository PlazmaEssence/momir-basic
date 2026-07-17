"""Read-only query helpers against data/momir.sqlite3."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "momir.sqlite3"

MAX_CMC_WALK = 6  # how far Momir Vig-style "walk outward" search goes if a cmc has zero cards


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def card_count(db_path: Path = DB_PATH) -> int:
    con = get_connection(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    finally:
        con.close()


def _row_to_card(row: sqlite3.Row) -> dict:
    card = dict(row)
    card["colors"] = [c for c in (card.get("color_identity") or "").split(",") if c]
    return card


def _random_creature_at_cmc(con: sqlite3.Connection, cmc: int) -> dict | None:
    row = con.execute(
        "SELECT * FROM cards WHERE cmc_int = ? ORDER BY RANDOM() LIMIT 1",
        (cmc,),
    ).fetchone()
    return _row_to_card(row) if row else None


def random_creature_by_cmc(cmc: int, db_path: Path = DB_PATH) -> dict | None:
    """Random creature at the given mana value. If none exist at that exact
    value, walks outward (+1, -1, +2, -2, ...) like real Momir Vig does when
    a card's mana value has no match in the deck."""
    if cmc < 0:
        raise ValueError("cmc must be >= 0")

    con = get_connection(db_path)
    try:
        card = _random_creature_at_cmc(con, cmc)
        if card is not None:
            card["requested_cmc"] = cmc
            card["actual_cmc"] = cmc
            return card

        for delta in range(1, MAX_CMC_WALK + 1):
            for candidate in (cmc + delta, cmc - delta):
                if candidate < 0:
                    continue
                card = _random_creature_at_cmc(con, candidate)
                if card is not None:
                    card["requested_cmc"] = cmc
                    card["actual_cmc"] = candidate
                    return card
        return None
    finally:
        con.close()


def get_card_by_id(card_id: int, db_path: Path = DB_PATH) -> dict | None:
    con = get_connection(db_path)
    try:
        row = con.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return _row_to_card(row) if row else None
    finally:
        con.close()


def search_cards(query: str, limit: int = 20, db_path: Path = DB_PATH) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    con = get_connection(db_path)
    try:
        try:
            rows = con.execute(
                """SELECT cards.* FROM cards_fts
                   JOIN cards ON cards.id = cards_fts.rowid
                   WHERE cards_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (f'"{query}"*', limit),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = con.execute(
                "SELECT * FROM cards WHERE name LIKE ? ORDER BY name LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
        return [_row_to_card(r) for r in rows]
    finally:
        con.close()


def cmc_counts(db_path: Path = DB_PATH) -> dict[int, int]:
    con = get_connection(db_path)
    try:
        rows = con.execute(
            "SELECT cmc_int, COUNT(*) AS n FROM cards GROUP BY cmc_int ORDER BY cmc_int"
        ).fetchall()
        return {row["cmc_int"]: row["n"] for row in rows}
    finally:
        con.close()
