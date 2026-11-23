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
from autonomy.category_prototype_engine import CategoryPrototypeEngine

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
    graph = memory_clone(raw_store)
    cuda_lib = CudaLibrary()
    proto_engine = CategoryPrototypeEngine(graph)

    held_out_cases = [
        {"entity": "beaver", "category": "mammal", "det": "a", "sent": "a beaver is a mammal"},
        {"entity": "cat", "category": "mammal", "det": "a", "sent": "a cat is a mammal"},
        {"entity": "dhole", "category": "mammal", "det": "a", "sent": "a dhole is a mammal"},
        {"entity": "aldebaran", "category": "star", "det": "an", "sent": "an aldebaran is a star"},
        {"entity": "alioth", "category": "star", "det": "an", "sent": "an alioth is a star"},
        {"entity": "nova", "category": "star", "det": "a", "sent": "a nova is a star"},
        {"entity": "hammer", "category": "tool", "det": "a", "sent": "a hammer is a tool"},
        {"entity": "microlith", "category": "tool", "det": "a", "sent": "a microlith is a tool"},
        {"entity": "lethe", "category": "river", "det": "a", "sent": "a lethe is a river"},
        {"entity": "chicken", "category": "bird", "det": "a", "sent": "a chicken is a bird"},
        {"entity": "eagle", "category": "bird", "det": "an", "sent": "an eagle is a bird"},
        {"entity": "duck", "category": "bird", "det": "a", "sent": "a duck is a bird"},
        {"entity": "salmon", "category": "fish", "det": "a", "sent": "a salmon is a fish"},
        {"entity": "chaparral", "category": "plant", "det": "a", "sent": "a chaparral is a plant"},
        {"entity": "fruit", "category": "plant", "det": "a", "sent": "a fruit is a plant"},
    ]

    print("\n=======================================================")
    print("1. BINDING 15 HELD-OUT NOVEL ENTITIES TO PROTOTYPE SLOTS")
    print("=======================================================")
    bound_count = 0
    for tc in held_out_cases:
        ok = proto_engine.bind_entity_to_prototype(tc["entity"], tc["category"], tc["det"])
        if ok:
            bound_count += 1
            # Check permutation reduction
            words = tc["sent"].split()
            raw_perms = distinct_permutations_count(words)
            reduced = proto_engine.reduce_permutations(words, tc["category"])
            print(f"  Bound '{tc['entity']}' -> [{tc['category']}] | Permutations: {raw_perms} -> {len(reduced)}")
        else:
            print(f"  FAILED to bind '{tc['entity']}' -> [{tc['category']}]")

    print(f"\nTotal bound: {bound_count}/{len(held_out_cases)}")

    print("\n=======================================================")
    print("2. SAMPLING ROUTE DISTRIBUTIONS UNDER PROTOTYPE INHERITANCE")
    print("=======================================================")
    sentence_engine = Neuronizer(graph, cuda_lib)

    total_hits = 0
    total_samples = 0
    total_chance = 0.0

    for tc in held_out_cases:
        words = tc["sent"].split()
        raw_perms = distinct_permutations_count(words)
        ch_rate = 1.0 / raw_perms

        res, err = evaluate_shape(sentence_engine, words)
        if err:
            print(f"  '{tc['sent']}' -> HOLD / ERROR: {err}")
        else:
            hits, total, rank, num_d, top3 = res
            total_hits += hits
            total_samples += total
            total_chance += ch_rate * total
            rate = hits / total if total else 0
            top_str = " | ".join(f"{s.replace('WORD:', '')}: {c}" for s, c in top3)
            print(f"  '{tc['sent']}' -> hits: {hits}/{total} ({rate:.1%}) | rank: {rank}/{num_d} | chance: {ch_rate:.2%}")
            print(f"      top sampled: {top_str}")

    overall_rate = total_hits / total_samples if total_samples else 0
    overall_chance = total_chance / total_samples if total_samples else 0
    print("\n=======================================================")
    print(f"HELD-OUT TRANSFER SUMMARY: {total_hits}/{total_samples} = {overall_rate:.1%} (chance baseline: {overall_chance:.2%})")
    print("=======================================================")

if __name__ == "__main__":
    main()
