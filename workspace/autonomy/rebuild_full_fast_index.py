import sqlite3
import json
import zlib
from pathlib import Path

MASTER_DB = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")
FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")

print("=======================================================================")
print("      FIXING RED-TEAM INDEX: POPULATING FULL 103k LEXICAL LATTICE      ")
print("=======================================================================")

conn_master = sqlite3.connect(MASTER_DB)
cur_m = conn_master.cursor()

conn_fast = sqlite3.connect(FAST_INDEX_DB)
cur_f = conn_fast.cursor()

cur_f.execute("DROP TABLE IF EXISTS word_index")
cur_f.execute("""
CREATE TABLE word_index (
    word TEXT PRIMARY KEY,
    token_id INTEGER,
    neuron_id TEXT,
    spelling TEXT,
    observations INTEGER
)
""")
conn_fast.commit()

print("Scanning all WORD neurons in master database...")
cur_m.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE kind = 'WORD'")

batch = []
total = 0
while True:
    rows = cur_m.fetchmany(10000)
    if not rows:
        break
    for tid, nid, payload in rows:
        try:
            data = json.loads(zlib.decompress(payload).decode('utf-8'))
            surface = data.get('center_attractor', {}).get('learned_surface')
            if surface and isinstance(surface, str):
                letters = [c.replace('CHAR:', '') for c in data.get('center_attractor', {}).get('learned_character_construction', [])]
                obs = data.get('center_attractor', {}).get('opaque_position_profile_v1', {}).get('observations', 0)
                batch.append((surface.strip().lower(), tid, nid, "-".join(letters).upper(), obs))
        except Exception:
            pass

    if len(batch) >= 10000:
        cur_f.executemany("INSERT OR IGNORE INTO word_index VALUES (?, ?, ?, ?, ?)", batch)
        conn_fast.commit()
        total += len(batch)
        print(f"  * Indexed {total:,} words so far...")
        batch = []

if batch:
    cur_f.executemany("INSERT OR IGNORE INTO word_index VALUES (?, ?, ?, ?, ?)", batch)
    conn_fast.commit()
    total += len(batch)

# Create high-speed B-Tree index on word column
cur_f.execute("CREATE INDEX IF NOT EXISTS idx_word_fast ON word_index(word)")
conn_fast.commit()

cur_f.execute("SELECT count(*) FROM word_index")
final_count = cur_f.fetchone()[0]
print(f"\n[SUCCESS] Indexed complete vocabulary: {final_count:,} words in B-Tree table.")

# Test lookup for 'the'
cur_f.execute("SELECT * FROM word_index WHERE word = 'the'")
row_the = cur_f.fetchone()
print(f"[VERIFICATION] Found 'the': {row_the}")
print("=======================================================================")
