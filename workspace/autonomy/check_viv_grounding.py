import sqlite3
from pathlib import Path

db_lex = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
conn = sqlite3.connect(db_lex)
row = conn.cursor().execute("SELECT token_id, spelling, observations FROM word_index WHERE word = 'viv'").fetchone()
conn.close()

print("Word 'viv' in Lexical B-Tree:", row)
print("Physical territory 'L:\\Standalone\\Viv' exists:", Path(r"L:\Standalone\Viv").exists())
print("Physical territory 'L:\\Viv-CLI' exists:", Path(r"L:\Viv-CLI").exists())
