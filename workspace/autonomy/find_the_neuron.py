import sqlite3
import zlib
import json

db = 'L:/LocalCoder/workspace/autonomy/learning/neural_runs/language-routes-20261107T222340465626Z/neuron_graph.sqlite3'
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute('SELECT token_id, neuron_id, payload FROM neurons LIMIT 2000')
matches = []
for token_id, neuron_id, payload in cur.fetchall():
    try:
        raw = zlib.decompress(payload).decode('utf-8')
        if '"the"' in raw:
            data = json.loads(raw)
            comb = data.get('center_attractor', {}).get('learned_combination')
            matches.append((token_id, neuron_id, comb))
    except Exception:
        pass

print(f"Total matches in first 2000 neurons: {len(matches)}")
print("Sample matches:", matches[:10])
