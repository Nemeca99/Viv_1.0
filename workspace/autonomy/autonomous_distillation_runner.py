"""Topology-backed distillation entry point with fail-closed tutor proposals."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

WORKSPACE = Path(__file__).resolve().parent.parent
for root in (WORKSPACE, Path(r"L:\Standalone\NN")):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from autonomy.fractal_cognitive_engine import FractalCognitiveEngine
from autonomy.learning_paths import latest_verified_run
from nn_local.steel_brain_store import SQLiteNeuronGraphStore


def dynamic_candidates(limit: int = 8) -> list[str]:
    """Return lexical nodes from the latest verified topology."""
    run = latest_verified_run()
    if not run:
        return []
    with SQLiteNeuronGraphStore(Path(run) / "neuron_graph.sqlite3", readonly=True) as graph:
        return sorted(graph.manifest().get("word_index", {}))[:max(0, int(limit))]


def run_orchestrator(*, max_lessons: int = 1, duration_minutes: float = 0.0, base_temp: float = 0.0, **_) -> list[dict]:
    """Attempt topology-backed tutor cycles; never synthesize scripted lessons."""
    del duration_minutes, base_temp
    engine = FractalCognitiveEngine()
    results = [engine.execute_fractal_mastery_cycle(word, use_teacher_context=True)
               for word in dynamic_candidates(max_lessons)]
    if not results:
        print("[DISTILLATION HOLD] No verified topology candidate is available.", flush=True)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-lessons", type=int, default=1)
    parser.add_argument("--duration-minutes", type=float, default=0.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    args = parser.parse_args()
    run_orchestrator(max_lessons=args.max_lessons, duration_minutes=args.duration_minutes, base_temp=args.temperature)


if __name__ == "__main__":
    main()
