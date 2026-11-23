"""Leave-one-route-out generalization matrix for the integer topology RNN."""

from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy.topology_integer_rnn import TopologyIntegerRNN, VerifiedExecutionTeacher

DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\rnn_generalization_matrix.json")
ROUTES = {
    "parity": "AUTONOMOUS_CHALLENGE_19_MUTUAL_RECURSION_PARITY",
    "maze": "AUTONOMOUS_CHALLENGE_21_RECURSIVE_MAZE_SOLVER",
    "ttt": "AUTONOMOUS_CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR",
}
SEEDS = (11, 23, 37, 41, 53, 67, 79, 83, 97, 101)


def run() -> dict:
    teacher = VerifiedExecutionTeacher(DB, anchor_width=4)
    routes = {name: [a.vector for a in teacher.primitive_route(cid)] for name, cid in ROUTES.items()}
    rows = []
    for held_name, held_out in routes.items():
        train_routes = [route for name, route in routes.items() if name != held_name]
        for seed in SEEDS:
            rng = random.Random(seed)
            network = TopologyIntegerRNN(4, 4, scale_bits=0, state_limit=128, use_gpu=True)
            network.set_weights(
                [[rng.randint(-1, 1) for _ in range(4)] for _ in range(4)],
                [[rng.randint(-1, 1) for _ in range(4)] for _ in range(4)],
            )
            for route in train_routes:
                network.learn_route(route, reward=1)
            held_score = network.route_score(held_out)
            reverse_score = network.route_score(list(reversed(held_out)))
            rows.append({
                "held_out": held_name,
                "seed": seed,
                "held_out_score": held_score,
                "reverse_score": reverse_score,
                "margin": held_score - reverse_score,
                "relative_margin": (held_score - reverse_score) / max(abs(held_score), abs(reverse_score), 1),
                "positive": held_score > reverse_score,
            })
    margins = [row["margin"] for row in rows]
    relative_margins = [row["relative_margin"] for row in rows]
    result = {
        "schema": "viv-rnn-generalization-matrix-v1",
        "routes": ROUTES,
        "runs": rows,
        "positive_runs": sum(row["positive"] for row in rows),
        "total_runs": len(rows),
        "positive_rate": sum(row["positive"] for row in rows) / len(rows),
        "margin_mean": statistics.mean(margins),
        "margin_stdev": statistics.stdev(margins),
        "margin_min": min(margins),
        "margin_max": max(margins),
        "relative_margin_mean": statistics.mean(relative_margins),
        "relative_margin_stdev": statistics.stdev(relative_margins),
        "relative_margin_min": min(relative_margins),
        "relative_margin_max": max(relative_margins),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUT.with_suffix(OUT.suffix + ".tmp")
    temp.write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf-8")
    temp.replace(OUT)
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, sort_keys=True))
