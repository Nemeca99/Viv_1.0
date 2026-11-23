import sqlite3
import zlib
import json

db = 'L:/LocalCoder/workspace/autonomy/learning/neural_runs/language-routes-20261107T222340465626Z/neuron_graph.sqlite3'
conn = sqlite3.connect(db)
cur = conn.cursor()

found = None
cur.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE kind = 'WORD'")
count = 0
while True:
    rows = cur.fetchmany(5000)
    if not rows:
        break
    count += len(rows)
    for token_id, neuron_id, payload in rows:
        try:
            data = json.loads(zlib.decompress(payload).decode('utf-8'))
            surface = data.get('center_attractor', {}).get('learned_surface')
            if surface == 'the':
                found = (token_id, neuron_id, data)
                break
        except Exception:
            pass
    if found:
        break

print(f"Scanned {count} WORD neurons.")
if found:
    token_id, neuron_id, data = found
    print(f"FOUND EXACT 'the' NEURON! Token ID: {token_id}, Neuron ID: {neuron_id}")
    print(json.dumps(data, indent=2))
else:
    print("Exact 'the' WORD neuron not found in this partition scan.")
