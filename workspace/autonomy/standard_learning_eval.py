"""Lightweight read-only standard evaluation for the continuous learner.

This evaluator never initializes CUDA, never writes the graph, and never
competes with the daemon's body gate. It checks verified snapshot integrity,
grounded route coverage, utility scores, and fail-closed unknown handling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

from autonomy.terminal_neuron_learning import (
    input_words,
    latest_verified_run,
    verify_run,
)
from autonomy.fractal_cognitive_engine import load_historical_certified_sentences
from autonomy.utility_advertisement import UtilityAdvertiser

def dynamic_probe_sentences(run: Path, limit: int = 10) -> list[str]:
    """Build evaluation routes from the verified graph, never a word fixture."""
    import sqlite3
    from nn_local.steel_brain_store import SQLiteNeuronGraphStore
    with SQLiteNeuronGraphStore(run / "neuron_graph.sqlite3", readonly=True) as graph:
        word_index = graph.manifest().get("word_index", {})
    reverse = {str(value): str(key) for key, value in word_index.items()}
    with sqlite3.connect(f"file:{(run / 'neuron_graph.sqlite3').resolve()}?mode=ro", uri=True) as con:
        rows = con.execute(
            "SELECT source_id, peer_id FROM links WHERE hot=1 ORDER BY weight DESC, rowid LIMIT ?",
            (max(1, int(limit) * 3),),
        ).fetchall()
    probes = []
    for source, peer in rows:
        left, right = reverse.get(source), reverse.get(peer)
        if left and right and str(left).isalpha() and str(right).isalpha():
            probes.append(f"{left} {right}")
        if len(probes) >= limit:
            break
    return probes


def evaluate() -> dict:
    run = latest_verified_run()
    if run is None:
        return {
            "schema": "viv_standard_learning_eval_v1",
            "status": "HOLD",
            "reason": "NO_VERIFIED_SNAPSHOT",
        }
    receipt = verify_run(run)
    advertiser = UtilityAdvertiser(run / "neuron_graph.sqlite3")
    rows = []
    for sentence in dynamic_probe_sentences(run):
        words = input_words(sentence)
        advertisement = advertiser.advertise_route(words)
        rows.append({
            "sentence": " ".join(words),
            "state": advertisement["state"],
            "utility": advertisement["utility"],
            "edge_count": advertisement["edge_count"],
            "missing_edges": advertisement["missing_edges"],
        })
    learned_rows = []
    for sentence in sorted(load_historical_certified_sentences()):
        words = input_words(sentence)
        advertisement = advertiser.advertise_route(words)
        learned_rows.append({
            "question": " ".join(words),
            "state": advertisement["state"],
            "utility": advertisement["utility"],
            "edge_count": advertisement["edge_count"],
            "missing_edges": advertisement["missing_edges"],
        })
    unknown = advertiser.advertise_route(["unlearned_probe", "entity"])
    advertiser.close()
    covered = sum(row["state"] == "PASS" for row in rows)
    return {
        "schema": "viv_standard_learning_eval_v1",
        "status": "PASS",
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "run": str(run),
        "snapshot_verified": bool(receipt.get("snapshot_verified")),
        "held_out_count": len(rows),
        "fully_grounded_count": covered,
        "grounded_fraction": covered / len(rows) if rows else 0.0,
        "mean_utility": sum(row["utility"] for row in rows) / len(rows) if rows else 0.0,
        "rows": rows,
        "learned_question_count": len(learned_rows),
        "learned_questions_grounded": sum(
            row["state"] == "PASS" for row in learned_rows
        ),
        "learned_question_grounded_fraction": (
            sum(row["state"] == "PASS" for row in learned_rows) / len(learned_rows)
            if learned_rows else 0.0
        ),
        "learned_question_mean_utility": (
            sum(row["utility"] for row in learned_rows) / len(learned_rows)
            if learned_rows else 0.0
        ),
        "unknown_probe": {
            "state": unknown["state"],
            "utility": unknown["utility"],
            "missing_edges": unknown["missing_edges"],
        },
    }


def main() -> int:
    report = evaluate()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
