import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"L:\LocalCoder\workspace")
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import (
    latest_run, verify_run, memory_clone
)
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
from nn_local.neuronizer import Neuronizer, UniversalCurriculumEngine
from nn_local.cuda_backend import CudaLibrary

SEEDS = tuple(1000 + 97 * index for index in range(20))

def in_order_rate(sentence_engine, words):
    # visible states for each token
    # Note: if there are duplicate tokens like ["a", "cat", "is", "a", "mammal"],
    # visible_state_ids will have duplicates or unique states?
    # Let's check how Neuronizer handles visible states.
    visible = [f"WORD:{word}" for word in words]
    expected = " ".join(visible)
    distribution = sentence_engine.sample_state_distribution(visible, seeds=SEEDS)
    total = sum(int(count) for count in distribution.values())
    hits = int(distribution.get(expected, 0))
    # Let's also find the rank of expected in the distribution
    sorted_dist = sorted(distribution.items(), key=lambda x: x[1], reverse=True)
    rank = None
    for idx, (seq, cnt) in enumerate(sorted_dist, 1):
        if seq == expected:
            rank = idx
            break
    return hits, total, rank, len(sorted_dist), sorted_dist[:3]

def distinct_permutations_count(words):
    from collections import Counter
    counts = Counter(words)
    denom = 1
    for c in counts.values():
        denom *= math.factorial(c)
    return math.factorial(len(words)) // denom

def main():
    run = Path(latest_run())
    record = verify_run(run)
    print("Latest run:", run.name)

    # Use memory clone for speed and immutability
    raw_store = SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True)
    graph = memory_clone(raw_store)
    cuda_lib = CudaLibrary()
    sentence_engine = Neuronizer(graph, cuda_lib)

    taught_keys = {k.lower().rstrip('.'): v for k, v in record["lessons"].items() if v.get("state") == "PASS"}
    manifest = graph.manifest()
    known = set(manifest["word_index"])

    # 13 Taught Wikipedia Shapes
    taught_samples = [
        "an abacus is a tool",
        "an aardwolf is a mammal",
        "an anthophyta is a plant",
        "an asteroid is a planet",
        "a zebrafish is a fish",
        "a corcovado is a mountain",
        "a dodo is a bird",
        "a kumquat is a tree",
        "a spica is a star",
        "a tiger is a cat",
        "a tigris is a river",
        "a vulture is a bird",
        "a whippet is a dog"
    ]

    # 15 Held-Out Shapes across diverse categories (Mammal, Star, Tool, River, Bird, Fish, Plant, Vehicle, Instrument)
    held_out_samples = [
        # Mammals (grounded anchor: mammal)
        "a beaver is a mammal",
        "a cat is a mammal",
        "a dhole is a mammal",
        # Stars (grounded anchor: star)
        "an aldebaran is a star",
        "an alioth is a star",
        "a nova is a star",
        # Tools (grounded anchor: tool)
        "a hammer is a tool",
        "a microlith is a tool",
        # Rivers (grounded anchor: river)
        "a lethe is a river",
        # Birds (grounded anchor: bird)
        "a chicken is a bird",
        "an eagle is a bird",
        "a duck is a bird",
        # Fish (grounded anchor: fish)
        "a salmon is a fish",
        # Plants (grounded anchor: plant)
        "a chaparral is a plant",
        "a fruit is a plant",
    ]

    print("\n=======================================================")
    print("EVALUATING TAUGHT SHAPES (Positive Control)")
    print("=======================================================")
    taught_hits_total = 0
    taught_samples_total = 0
    taught_chance_total = 0.0

    for sent in taught_samples:
        words = sent.split()
        if any(w not in known for w in words):
            print(f"Skipping unknown: {sent}")
            continue
        perms = distinct_permutations_count(words)
        ch_rate = 1.0 / perms
        hits, total, rank, num_distinct, top3 = in_order_rate(sentence_engine, words)
        taught_hits_total += hits
        taught_samples_total += total
        taught_chance_total += ch_rate * total
        rate = hits / total if total else 0
        print(f"  '{sent}' -> hits: {hits}/{total} ({rate:.1%}) | rank: {rank}/{num_distinct} | chance: {ch_rate:.2%}")

    overall_taught_rate = taught_hits_total / taught_samples_total if taught_samples_total else 0
    overall_taught_chance = taught_chance_total / taught_samples_total if taught_samples_total else 0
    print(f"\nTAUGHT TOTAL: {taught_hits_total}/{taught_samples_total} = {overall_taught_rate:.1%} (chance: {overall_taught_chance:.2%})")

    print("\n=======================================================")
    print("EVALUATING 15 HELD-OUT SHAPES (Generalization Transfer Test)")
    print("=======================================================")
    held_hits_total = 0
    held_samples_total = 0
    held_chance_total = 0.0

    for sent in held_out_samples:
        words = sent.split()
        if any(w not in known for w in words):
            print(f"Skipping unknown: {sent}")
            continue
        perms = distinct_permutations_count(words)
        ch_rate = 1.0 / perms
        hits, total, rank, num_distinct, top3 = in_order_rate(sentence_engine, words)
        held_hits_total += hits
        held_samples_total += total
        held_chance_total += ch_rate * total
        rate = hits / total if total else 0
        top_str = " | ".join(f"{seq.replace('WORD:', '')}: {cnt}" for seq, cnt in top3)
        print(f"  '{sent}' -> hits: {hits}/{total} ({rate:.1%}) | rank: {rank}/{num_distinct} | chance: {ch_rate:.2%}")
        print(f"      top sampled: {top_str}")

    overall_held_rate = held_hits_total / held_samples_total if held_samples_total else 0
    overall_held_chance = held_chance_total / held_samples_total if held_samples_total else 0
    print(f"\nHELD-OUT TOTAL: {held_hits_total}/{held_samples_total} = {overall_held_rate:.1%} (chance: {overall_held_chance:.2%})")

if __name__ == "__main__":
    main()
