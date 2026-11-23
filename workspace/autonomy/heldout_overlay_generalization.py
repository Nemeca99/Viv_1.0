"""Held-out route matrix for the integer-RNN overlay learner."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from deterministic_containment import CONTAINED, ContainmentEngine, SQLiteOverlayCartridge
from live_learning_cycle import OVERLAY, SOURCE, make_overlay, digest
from topology_integer_rnn import TopologyIntegerRNN


OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\heldout_overlay_generalization.json")


def anchor(text: str) -> tuple[int, int]:
    raw = hashlib.sha256(text.encode()).digest()
    return (int(raw[0]) - 128, int(raw[1]) - 128)


def route(query: str, engine: ContainmentEngine) -> tuple[list[tuple[int, int]], str]:
    result = engine.query(query)
    return [anchor(item) for item in result.trace[:3]] or [anchor(query)], result.state


def main() -> None:
    make_overlay()
    with sqlite3.connect(SOURCE) as src, sqlite3.connect(OVERLAY) as dst:
        row = src.execute("SELECT article_id,title,summary FROM articles WHERE lower(title) LIKE '%diffuse sky radiation%' LIMIT 1").fetchone()
        if row:
            dst.execute("INSERT INTO articles VALUES (?,?,?,?,?,?)", (*row, "", "", ""))
            dst.commit()
    engine = ContainmentEngine([SQLiteOverlayCartridge("overlay", OVERLAY, source_path=SOURCE)])
    train_route, train_state = route("Rayleigh scattering", engine)
    held_route, held_state = route("Diffuse sky radiation", engine)
    if train_state != CONTAINED or held_state != CONTAINED:
        raise RuntimeError({"train": train_state, "held_out": held_state})
    rows = []
    for seed in range(5):
        model = TopologyIntegerRNN(2, 2, use_gpu=True)
        # Deterministic seed-specific integer perturbation keeps candidates distinct.
        model.weight_input[0, 0] = seed
        model.learn_route(train_route, reward=1)
        held_score = model.route_score(held_route)
        negative_score = model.route_score(list(reversed(held_route)))
        rows.append({"seed": seed, "train_state": train_state, "held_out_state": held_state, "retrieval_pass": held_state == CONTAINED, "held_out_score": held_score, "negative_score": negative_score, "margin": held_score - negative_score, "generalization_pass": held_score > negative_score})
        model.save_candidate(OUT.with_name(f"heldout_candidate_seed{seed}.json"), topology_sha256=digest(SOURCE), receipt_ids=[f"heldout-{seed}"])
        OUT.with_name(f"heldout_rejected_seed{seed}.json").write_text(json.dumps({"status": "REJECTED", "seed": seed, "negative_score": negative_score, "reason": "reversed held-out route"}, indent=2) + "\n", encoding="utf-8")
    margins = [row["margin"] for row in rows]
    receipt = {"schema": "viv-heldout-overlay-generalization-v1", "status": "PASS" if all(row["generalization_pass"] for row in rows) else "HOLD", "split": {"train_query": "Rayleigh scattering", "held_out_query": "Diffuse sky radiation", "negative": "reversed held-out route"}, "retrieval": {"train_state": train_state, "held_out_state": held_state, "pass": all(row["retrieval_pass"] for row in rows)}, "generalization": {"runs": rows, "positive_runs": sum(row["generalization_pass"] for row in rows), "margin_min": min(margins), "margin_max": max(margins), "sign_stable": all(value > 0 for value in margins) or all(value < 0 for value in margins)}, "source_sha256": digest(SOURCE), "rejected_candidates_preserved": True}
    OUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "positive_runs": receipt["generalization"]["positive_runs"], "margin_min": receipt["generalization"]["margin_min"], "sign_stable": receipt["generalization"]["sign_stable"], "receipt": str(OUT)}))


if __name__ == "__main__":
    main()
