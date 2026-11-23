import sys
import json
from pathlib import Path
from collections import Counter

sys.path.insert(0, r"L:\LocalCoder\workspace")
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import latest_run, verify_run
from nn_local.steel_brain_store import SQLiteNeuronGraphStore

run = Path(latest_run())
record = verify_run(run)
taught = {k.lower().rstrip('.'): v for k, v in record["lessons"].items() if v.get("state") == "PASS"}

shapes = [json.loads(line) for line in open("L:/LocalCoder/workspace/autonomy/data/wikipedia_emergent_shapes.jsonl")]
graph = SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True)
manifest = graph.manifest()
known = set(manifest["word_index"])

untaught_by_cat = {}

for s in shapes:
    words = s["target_sentence"].lower().rstrip(".").split()
    if all(w in known for w in words):
        sent = s["target_sentence"].lower().rstrip(".")
        if sent not in taught:
            cat = s["category"]
            if cat not in untaught_by_cat:
                untaught_by_cat[cat] = []
            untaught_by_cat[cat].append(s)

print("--- Sample Untaught Shapes in Vocab by Category ---")
for cat, items in untaught_by_cat.items():
    print(f"Category: {cat} ({len(items)} available):")
    for it in items[:3]:
        print(f"   {it['target_sentence']} | focus: {it['focus_words']}")
