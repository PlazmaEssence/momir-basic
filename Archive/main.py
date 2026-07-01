import sqlite3, random
con = sqlite3.connect("/Users/justin/Documents/Python/Momir/momir.db")
card = con.execute(
    "SELECT * FROM creatures WHERE mana_value = ? ORDER BY RANDOM() LIMIT 1",
    (13,)).fetchone()

print(card)