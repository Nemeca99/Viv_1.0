import json
import math
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, r"L:\LocalCoder\workspace")
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import latest_run, verify_run, memory_clone
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

def main():
    run = Path(latest_run())
    print("Latest run:", run.name)

    raw_store = SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True)
    cuda_lib = CudaLibrary()

    # 5 test pairs across categories
    test_cases = [
        {"entity": "beaver", "category": "mammal", "sent": "a beaver is a mammal"},
        {"entity": "dhole", "category": "mammal", "sent": "a dhole is a mammal"},
        {"entity": "aldebaran", "category": "star", "sent": "an aldebaran is a star"},
        {"entity": "alioth", "category": "star", "sent": "an alioth is a star"},
        {"entity": "hammer", "category": "tool", "sent": "a hammer is a tool"},
        {"entity": "lethe", "category": "river", "sent": "a lethe is a river"},
        {"entity": "chaparral", "category": "plant", "sent": "a chaparral is a plant"},
    ]

    print("\n--- TEST 1: Baseline (No Concept Grounding, Untaught Routes) ---")
    graph1 = memory_clone(raw_store)
    eng1 = Neuronizer(graph1, cuda_lib)
    for tc in test_cases:
        words = tc["sent"].split()
        res, err = evaluate_shape(eng1, words)
        if err:
            print(f"  '{tc['sent']}' -> HOLD / ERROR: {err}")
        else:
            hits, total, rank, num_d, top3 = res
            top_str = " | ".join(f"{s.replace('WORD:', '')}: {c}" for s, c in top3)
            print(f"  '{tc['sent']}' -> hits: {hits}/{total} | rank: {rank}/{num_d} | top: {top_str}")

    print("\n--- TEST 2: Concept Cluster Grounded Only (entity <-> category linked, NO sentence route) ---")
    graph2 = memory_clone(raw_store)
    c_engine = ConceptualResonanceEngine(graph2)
    # Ground each entity to its category anchor with standard conductance
    for tc in test_cases:
        c_engine.link_concept_cluster(tc["category"], [tc["entity"], tc["category"]], base_conductance=500_000)

    eng2 = Neuronizer(graph2, cuda_lib)
    for tc in test_cases:
        words = tc["sent"].split()
        res, err = evaluate_shape(eng2, words)
        if err:
            print(f"  '{tc['sent']}' -> HOLD / ERROR: {err}")
        else:
            hits, total, rank, num_d, top3 = res
            top_str = " | ".join(f"{s.replace('WORD:', '')}: {c}" for s, c in top3)
            print(f"  '{tc['sent']}' -> hits: {hits}/{total} | rank: {rank}/{num_d} | top: {top_str}")

if __name__ == "__main__":
    main()
