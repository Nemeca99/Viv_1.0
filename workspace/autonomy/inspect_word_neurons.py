import sqlite3
import zlib
import json

db = 'L:/LocalCoder/workspace/autonomy/learning/neural_runs/language-routes-20261107T222340465626Z/neuron_graph.sqlite3'
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE kind = 'WORD' LIMIT 15")
rows = cur.fetchall()
print(f"Total WORD neurons fetched: {len(rows)}")
for token_id, neuron_id, payload in rows:
    try:
        data = json.loads(zlib.decompress(payload).decode('utf-8'))
        print(f"Token {token_id} | Attractor: {data.get('center_attractor')}")
    except Exception as e:
        print(f"Error decoding token {token_id}: {e}")
