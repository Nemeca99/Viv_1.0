"""Read-only held-out check for Viv's route learning.

Question: do fresh route samples for sentences that were never taught come out in input
order more often than chance, compared with sentences that were taught? Nothing is
written to the graph, curriculum, pointers, or any run directory. The Rust body gate must
ALLOW the mind runtime before any model/graph work starts.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from autonomy.terminal_neuron_learning import (
    STANDALONE, WORKSPACE, input_words, latest_run, open_curriculum, verify_run,
)

if str(STANDALONE) not in sys.path:
    sys.path.insert(0, str(STANDALONE))

SEEDS = tuple(1000 + 97 * index for index in range(20))
HELD_OUT = (
    "The dog is tall.", "The cat is big.", "The sun is dark.", "The bird can learn.",
    "The tree is blue.", "The fish is hot.", "The star is big.", "The moon is bright.",
    "The cat is tall.", "The dog is dark.", "The wave is blue.", "The sky is bright.",
)
OUT = WORKSPACE / "autonomy/logs/held_out_route_eval.jsonl"


def in_order_rate(sentence_engine, words):
    visible = sorted(f"WORD:{word}" for word in words)
    expected = " ".join(f"WORD:{word}" for word in words)
    distribution = sentence_engine.sample_state_distribution(visible, seeds=SEEDS)
    total = sum(int(count) for count in distribution.values())
    hits = int(distribution.get(expected, 0))
    return hits, total


def chance(words):
    return 1.0 / math.factorial(len(set(words))) if len(set(words)) == len(words) else None


def main():
    from main_core.mind_runtime_gate import BodyRuntimeHold, RuntimeBodyGuard

    try:
        RuntimeBodyGuard(requested_threads=2).check(force=True)
    except BodyRuntimeHold as hold:
        print("BODY HOLD, nothing evaluated: " + json.dumps(hold.verdict, sort_keys=True))
        return 2
    from nn_local.steel_brain_store import SQLiteNeuronGraphStore
    from nn_local.neuronizer import Neuronizer, UniversalCurriculumEngine
    from nn_local.cuda_backend import CudaLibrary
    from autonomy.terminal_neuron_learning import memory_clone

    run = latest_run()
    record = verify_run(run)
    graph = memory_clone(SQLiteNeuronGraphStore(Path(run) / "neuron_graph.sqlite3", readonly=True))
    curriculum = open_curriculum(Path(run) / "curriculum.sqlite3")
    try:
        engine = UniversalCurriculumEngine(graph, CudaLibrary(), curriculum, assembly_evidence=True)
        sentence_engine = Neuronizer(graph, engine.library)
        known = set(graph.manifest()["word_index"])
        taught = [key for key, value in record["lessons"].items() if value.get("state") == "PASS"]
        report = {"run": str(run), "at_utc": datetime.now(timezone.utc).isoformat(), "seeds": len(SEEDS),
                  "groups": {}}
        groups = {
            "taught": [key.split() for key in taught],
            "held_out": [input_words(text) for text in HELD_OUT],
        }
        skipped = []
        for name, sentences in groups.items():
            rows, hits_all, total_all, expected_chance = [], 0, 0, 0.0
            for words in sentences:
                if any(word not in known for word in words):
                    skipped.append(" ".join(words))
                    continue
                if name == "held_out" and " ".join(words) in record["lessons"]:
                    continue
                hits, total = in_order_rate(sentence_engine, words)
                rows.append({"sentence": " ".join(words), "in_order": hits, "samples": total})
                hits_all += hits
                total_all += total
                baseline = chance(words)
                expected_chance += (baseline or 0.0) * total
            report["groups"][name] = {
                "sentences": len(rows), "in_order": hits_all, "samples": total_all,
                "rate": hits_all / total_all if total_all else None,
                "chance_rate": expected_chance / total_all if total_all else None,
                "rows": rows,
            }
        report["skipped_unknown_words"] = skipped
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(report) + "\n")
        for name, group in report["groups"].items():
            print(f"{name}: {group['in_order']}/{group['samples']} in order = "
                  f"{group['rate']:.3f} (chance ~{group['chance_rate']:.3f}) over {group['sentences']} sentences")
        if skipped:
            print("skipped (word not in graph):", ", ".join(skipped))
        return 0
    finally:
        graph.close()
        curriculum.close()


if __name__ == "__main__":
    sys.exit(main())
