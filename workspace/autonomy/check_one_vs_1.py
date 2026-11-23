import sqlite3
from pathlib import Path

FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
conn = sqlite3.connect(FAST_INDEX_DB)
cur = conn.cursor()

word_one = cur.execute("SELECT token_id, spelling FROM word_index WHERE word = 'one'").fetchone()
digit_1 = cur.execute("SELECT token_id, spelling FROM word_index WHERE word = '1'").fetchone()

print("Word  'one' :", word_one)
print("Digit '1'   :", digit_1)
conn.close()
