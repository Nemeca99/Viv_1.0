import math
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, r"L:\LocalCoder\workspace")
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import latest_run, memory_clone
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
from nn_local.neuronizer import Neuronizer
from nn_local.cuda_backend import CudaLibrary, CudaRouteHold
from autonomy.conceptual_resonance_engine import ConceptualResonanceEngine

SEEDS = tuple(1000 + 97 * index for index in range(20))

def distinct_permutations_count(words):
    counts = Counter(words)
    denom = 1
    for c in counts.values():
        denom *= math.factorial(c)
    return math.factorial(len(words)) // denom

def evaluate_shape(sentence_engine, words):
    visible = [f"WORD:{word}" for word in words]
    expected = " ".join(visible)
    try:
        distribution = sentence_engine.sample_state_distribution(visible, seeds=SEEDS)
    except CudaRouteHold as e:
        return None, str(e)
    
    total = sum(int(count) for count in distribution.values())
    hits = int(distribution.get(expected, 0))
    sorted_dist = sorted(distribution.items(), key=lambda x: x[1], reverse=True)
    rank = None
    for idx, (seq, cnt) in enumerate(sorted_dist, 1):
        if seq == expected:
            rank = idx
            break
    return (hits, total, rank, len(sorted_dist), sorted_dist[:3]), None

def inject_category_slot_inheritance(graph, entity: str, category: str, det: str = "a"):
    """Category Prototype Slot Inheritance:
    Allows an entity to inherit the syntactic subject slot of its category manifold.
    Wires:
      det -> entity (weight: 850_000, dir: OUT)
      entity -> is (weight: 850_000, dir: OUT)
      entity <-> category (weight: 600_000, dir: OUT)
    """
    manifest = graph.manifest()
    w_idx = manifest["word_index"]
    conn = graph.connection

    ent_id = w_idx.get(entity)
    cat_id = w_idx.get(category)
    det_id = w_idx.get(det)
    is_id = w_idx.get("is")

    if not ent_id or not cat_id or not det_id or not is_id:
        return False

    def _link(src, dst, weight):
        conn.execute("""
            INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256)
            VALUES (?, 0, (SELECT COALESCE(MAX(ordinal), -1) + 1 FROM links WHERE source_id = ? AND reflector = 0), ?, 1, ?, 1, 1, 0, 1, 1, '')
        """, (src, src, dst, weight))

    _link(det_id, ent_id, 850_000)
    _link(ent_id, is_id, 850_000)
    _link(ent_id, cat_id, 600_000)
    _link(cat_id, ent_id, 600_000)
    conn.commit()
    return True

def main():
    run = Path(latest_run())
    raw_store = SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True)
    cuda_lib = CudaLibrary()

    test_cases = [
        {"entity": "beaver", "category": "mammal", "det": "a", "sent": "a beaver is a mammal"},
        {"entity": "dhole", "category": "mammal", "det": "a", "sent": "a dhole is a mammal"},
        {"entity": "aldebaran", "category": "star", "det": "an", "sent": "an aldebaran is a star"},
        {"entity": "alioth", "category": "star", "det": "an", "sent": "an alioth is a star"},
        {"entity": "hammer", "category": "tool", "det": "a", "sent": "a hammer is a tool"},
        {"entity": "lethe", "category": "river", "det": "a", "sent": "a lethe is a river"},
        {"entity": "chaparral", "category": "plant", "det": "a", "sent": "a chaparral is a plant"},
    ]

    print("--- EVALUATING WITH CATEGORY PROTOTYPE SLOT INHERITANCE ---")
    graph = memory_clone(raw_store)
    for tc in test_cases:
        inject_category_slot_inheritance(graph, tc["entity"], tc["category"], tc["det"])

    eng = Neuronizer(graph, cuda_lib)
    total_hits = 0
    total_samples = 0
    total_chance = 0.0

    for tc in test_cases:
        words = tc["sent"].split()
        perms = distinct_permutations_count(words)
        ch_rate = 1.0 / perms
        res, err = evaluate_shape(eng, words)
        if err:
            print(f"  '{tc['sent']}' -> HOLD / ERROR: {err}")
        else:
            hits, total, rank, num_d, top3 = res
            total_hits += hits
            total_samples += total
            total_chance += ch_rate * total
            rate = hits / total if total else 0
            top_str = " | ".join(f"{s.replace('WORD:', '')}: {c}" for s, c in top3)
            print(f"  '{tc['sent']}' -> hits: {hits}/{total} ({rate:.1%}) | rank: {rank}/{num_d} (chance: {ch_rate:.2%})")
            print(f"      top sampled: {top_str}")

    overall_rate = total_hits / total_samples if total_samples else 0
    overall_chance = total_chance / total_samples if total_samples else 0
    print(f"\nTOTAL: {total_hits}/{total_samples} = {overall_rate:.1%} (chance: {overall_chance:.2%})")

if __name__ == "__main__":
    main()
