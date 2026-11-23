"""Independent-seed stability experiment for topology-RNN held-out margins."""

from __future__ import annotations

import hashlib
import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autonomy.topology_integer_rnn import TopologyIntegerRNN, VerifiedExecutionTeacher


DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_generalization_stability.json")
SEEDS = (11, 23, 37, 41, 53, 67, 79, 83, 97, 101)


def run() -> dict:
    teacher = VerifiedExecutionTeacher(DB, anchor_width=4)
    seen = [a.vector for a in teacher.primitive_route("AUTONOMOUS_CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR")]
    held_out = [a.vector for a in teacher.primitive_route("AUTONOMOUS_CHALLENGE_21_RECURSIVE_MAZE_SOLVER")]
    negative = list(reversed(held_out))
    rows = []
    for seed in SEEDS:
        rng = random.Random(seed)
        network = TopologyIntegerRNN(4, 4, scale_bits=0, state_limit=128, use_gpu=True)
        wi = [[rng.randint(-1, 1) for _ in range(4)] for _ in range(4)]
        wh = [[rng.randint(-1, 1) for _ in range(4)] for _ in range(4)]
        network.set_weights(wi, wh)
        network.learn_route(seen, reward=1)
        evaluation = network.evaluate_held_out(seen, held_out, negative)
        rows.append({
            "seed": seed,
            "seen_score": evaluation.seen_score,
            "held_out_score": evaluation.held_out_score,
            "negative_score": evaluation.negative_score,
            "margin": evaluation.held_out_score - evaluation.negative_score,
            "positive": evaluation.held_out_score > evaluation.negative_score,
        })
    margins = [row["margin"] for row in rows]
    result = {
        "schema": "viv-rnn-generalization-stability-v1",
        "seeds": list(SEEDS),
        "runs": rows,
        "positive_runs": sum(row["positive"] for row in rows),
        "positive_rate": sum(row["positive"] for row in rows) / len(rows),
        "margin_mean": statistics.mean(margins),
        "margin_stdev": statistics.stdev(margins) if len(margins) > 1 else 0.0,
        "margin_min": min(margins),
        "margin_max": max(margins),
        "topology_sha256": hashlib.sha256(DB.read_bytes()).hexdigest(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(OUT.suffix + ".tmp")
    temp.write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
    temp.replace(OUT)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
