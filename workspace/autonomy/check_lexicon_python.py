import sqlite3
from pathlib import Path

db = Path('L:/LocalCoder/workspace/autonomy/data/lexicon_ontology.db')
if db.exists():
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(lexical_entities)")
    print("Schema lexical_entities:", cur.fetchall())
    cur.execute("SELECT * FROM lexical_entities WHERE lemma LIKE '%python%'")
    print("Matches for python:", cur.fetchall())
    conn.close()
else:
    print("lexicon_ontology.db not found at", db)
