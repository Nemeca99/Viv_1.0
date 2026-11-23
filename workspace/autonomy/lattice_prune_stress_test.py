"""Simulate a retention-weight decay and lattice pruning stress-test on Viv's neural graph.

Evaluates topological fault tolerance across:
1. Admitted sentence-expert recall under progressive background lattice decay and pruning.
2. Open pathfinder route distribution resilience under varying unreinforced link retention.
Zero mutations to disk: runs entirely within an in-memory SQLite store clone.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sqlite3
import sys
import time
import zlib

WORKSPACE = Path(__file__).resolve().parent.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

STANDALONE = Path(r"L:\Standalone\NN")
if str(STANDALONE) not in sys.path:
    sys.path.insert(0, str(STANDALONE))

from autonomy.terminal_neuron_learning import (
    latest_run, memory_clone, open_curriculum, verify_run,
)

from nn_local.steel_brain_store import SQLiteNeuronGraphStore, _canonical_json, _compress, _sha256_bytes
from nn_local.neuronizer import Neuronizer, UniversalCurriculumEngine
from nn_local.cuda_backend import CudaLibrary
from main_core.mind_runtime_gate import RuntimeBodyGuard, BodyRuntimeHold

BENCHMARK_SENTENCES = (
    # Grade 1 Animals
    "The cat sat.",
    "The dog ate.",
    "The bird ran.",
    "The fish swam.",
    # Grade 2 Attributes & Capacity
    "The sun is hot.",
    "The tree is tall.",
    "The moon is bright.",
    "The mind can learn.",
    # Grade 3 Homophone Duels
    "Fish swim in sea.",
    "The cat can see.",
    "The cat sat there.",
    "They ate their fish.",
    "They ran to sea.",
    "The dog is too big.",
    "One and one is two.",
)

SEEDS = (812, 1812, 2812)


def apply_lattice_pruning(
    graph: SQLiteNeuronGraphStore,
    *,
    decay_fraction: float = 0.0,
    prune_unreinforced: bool = False,
    unreinforced_keep_ratio: float = 1.0,
    prune_seed: int = 42,
) -> dict[str, int]:
    """Apply simulated retention decay or pruning to low-multiplicity links in-memory."""
    # Find all neurons in graph
    cursor = graph.connection.cursor()
    cursor.execute("SELECT neuron_id, payload FROM neurons")
    rows = cursor.fetchall()
    
    modified_neurons = []
    total_edges = 0
    decayed_edges = 0
    pruned_edges = 0
    reinforced_edges = 0
    
    import random
    rng = random.Random(prune_seed)
    
    for neuron_id, payload_blob in rows:
        payload = json.loads(zlib.decompress(payload_blob).decode("utf-8"))
        reflectors = payload.get("reflectors", {})
        changed = False
        
        for channel, edges in reflectors.items():
            for edge in edges:
                total_edges += 1
                pass_hits = int(edge.get("pass_hits", 0))
                weight = int(edge.get("weight", 950000))
                hot = bool(edge.get("hot", True))
                
                if pass_hits > 1:
                    reinforced_edges += 1
                    continue  # Protect reinforced attractor bridges
                
                # Unreinforced edge (pass_hits <= 1)
                if decay_fraction > 0.0 and hot:
                    new_weight = max(10000, int(weight * (1.0 - decay_fraction)))
                    if new_weight != weight:
                        edge["weight"] = new_weight
                        decayed_edges += 1
                        changed = True
                
                if prune_unreinforced and hot:
                    if rng.random() > unreinforced_keep_ratio:
                        edge["hot"] = False
                        pruned_edges += 1
                        changed = True
        
        if changed:
            raw = _canonical_json(payload)
            packed = _compress(raw)
            source_sha256 = _sha256_bytes(raw)
            cursor.execute(
                "UPDATE neurons SET payload = ?, source_sha256 = ?, raw_bytes = ?, stored_bytes = ? WHERE neuron_id = ?",
                (packed, source_sha256, len(raw), len(packed), neuron_id),
            )
    
    graph.connection.commit()
    # Rebuild SQLite links table projection to reflect updated neuron payloads
    cursor.execute("DELETE FROM links")
    for neuron_id, payload_blob in cursor.execute("SELECT neuron_id, payload FROM neurons").fetchall():
        payload = json.loads(zlib.decompress(payload_blob).decode("utf-8"))
        edge_rows = list(graph._edge_rows(payload))
        if edge_rows:
            cursor.executemany(
                """INSERT INTO links(
                       source_id,reflector,ordinal,peer_id,direction,weight,uses,
                       pass_hits,fail_hits,hot,evidence_count,evidence_sha256
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                edge_rows,
            )
    graph.connection.commit()
    
    return {
        "total_edges": total_edges,
        "reinforced_edges": reinforced_edges,
        "decayed_edges": decayed_edges,
        "pruned_edges": pruned_edges,
        "active_links": graph.connection.execute("SELECT count(*) FROM links WHERE hot = 1").fetchone()[0],
    }


def evaluate_benchmark(se: Neuronizer, sentences: tuple[str, ...]) -> dict[str, any]:
    """Test recall and route distributions across the benchmark suite."""
    recall_results = []
    total_samples = 0
    passed_samples = 0
    
    for sentence_text in sentences:
        words = [w.strip(".,!?").lower() for w in sentence_text.split() if w.strip(".,!?")]
        expected_route = tuple(f"WORD:{w}" for w in words)
        expected_str = " ".join(expected_route)
        
        try:
            recall = se.sample_admitted_sentence_distribution(expected_route, seeds=SEEDS)
            hits = recall.get(expected_str, 0)
            total = sum(recall.values())
            passed = hits == total and total == len(SEEDS)
            passed_samples += hits
            total_samples += total
            recall_results.append({
                "sentence": sentence_text,
                "passed": passed,
                "hits": hits,
                "total": total,
                "distribution": recall,
            })
        except Exception as exc:
            recall_results.append({
                "sentence": sentence_text,
                "passed": False,
                "error": str(exc),
            })
            total_samples += len(SEEDS)
            
    return {
        "passed_sentences": sum(1 for r in recall_results if r.get("passed")),
        "total_sentences": len(sentences),
        "passed_samples": passed_samples,
        "total_samples": total_samples,
        "accuracy": passed_samples / max(1, total_samples),
        "results": recall_results,
    }


def run_pruning_stress_test():
    RuntimeBodyGuard(requested_threads=2).check(force=True)
    run = latest_run()
    record = verify_run(run)
    
    print(f"Loaded snapshot: {run.name}")
    print(f"Benchmark sentences: {len(BENCHMARK_SENTENCES)}")
    print("=" * 70)
    
    experiments = [
        ("Level 0: Baseline (Intact Lattice)", {"decay_fraction": 0.0, "prune_unreinforced": False, "unreinforced_keep_ratio": 1.0}),
        ("Level 1: 25% Weight Decay", {"decay_fraction": 0.25, "prune_unreinforced": False, "unreinforced_keep_ratio": 1.0}),
        ("Level 2: 50% Weight Decay", {"decay_fraction": 0.50, "prune_unreinforced": False, "unreinforced_keep_ratio": 1.0}),
        ("Level 3: 75% Weight Decay", {"decay_fraction": 0.75, "prune_unreinforced": False, "unreinforced_keep_ratio": 1.0}),
        ("Level 4: Prune 25% Unreinforced Links", {"decay_fraction": 0.0, "prune_unreinforced": True, "unreinforced_keep_ratio": 0.75}),
        ("Level 5: Prune 50% Unreinforced Links", {"decay_fraction": 0.0, "prune_unreinforced": True, "unreinforced_keep_ratio": 0.50}),
        ("Level 6: Prune 75% Unreinforced Links", {"decay_fraction": 0.0, "prune_unreinforced": True, "unreinforced_keep_ratio": 0.25}),
        ("Level 7: Prune 100% Unreinforced Links (Skeleton Only)", {"decay_fraction": 0.0, "prune_unreinforced": True, "unreinforced_keep_ratio": 0.0}),
    ]
    
    summary_report = []
    
    for label, params in experiments:
        t0 = time.monotonic()
        # Fresh in-memory clone for each experiment
        graph = memory_clone(SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True))
        curriculum = open_curriculum(run / "curriculum.sqlite3")
        engine = UniversalCurriculumEngine(graph, CudaLibrary(), curriculum, assembly_evidence=True)
        se = Neuronizer(graph, engine.library)
        
        prune_stats = apply_lattice_pruning(graph, **params)
        eval_stats = evaluate_benchmark(se, BENCHMARK_SENTENCES)
        dt = time.monotonic() - t0
        
        row = {
            "regime": label,
            "active_links": prune_stats["active_links"],
            "pruned_edges": prune_stats["pruned_edges"],
            "decayed_edges": prune_stats["decayed_edges"],
            "reinforced_edges": prune_stats["reinforced_edges"],
            "passed_sentences": f"{eval_stats['passed_sentences']}/{eval_stats['total_sentences']}",
            "recall_accuracy": f"{eval_stats['accuracy'] * 100:.1f}%",
            "eval_time_s": round(dt, 2),
        }
        summary_report.append({**row, "details": eval_stats})
        print(f"[{label}]")
        print(f"  Active Links: {row['active_links']} (Pruned: {row['pruned_edges']}, Decayed: {row['decayed_edges']})")
        print(f"  Sentence Recall Accuracy: {row['passed_sentences']} ({row['recall_accuracy']}) in {row['eval_time_s']}s")
        print("-" * 70)
        
    out_path = WORKSPACE / "autonomy/logs/lattice_prune_stress_test.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary_report, indent=2), encoding="utf-8")
    print(f"\nStress-test complete. Report saved to: {out_path}")
    return summary_report


if __name__ == "__main__":
    run_pruning_stress_test()
