import sqlite3
import zlib
import json

db = 'L:/LocalCoder/workspace/autonomy/learning/neural_runs/language-routes-20261107T222340465626Z/neuron_graph.sqlite3'
conn = sqlite3.connect(db)
cur = conn.cursor()

cur.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE payload LIKE '%\"the\"%' AND kind = 'WORD' LIMIT 20")
rows = cur.fetchall()
print(f"Candidates with 'the' in payload: {len(rows)}")
for token_id, neuron_id, payload in rows:
    try:
        data = json.loads(zlib.decompress(payload).decode('utf-8'))
        surface = data.get('center_attractor', {}).get('learned_surface')
        if surface == 'the':
            print(f"--> FOUND EXACT 'the' NEURON! Token ID: {token_id}, Neuron ID: {neuron_id}")
            print(json.dumps(data, indent=2))
            break
        elif 'the' in str(surface):
            print(f"Related surface: {surface} (Token: {token_id})")
    except Exception as e:
        pass
