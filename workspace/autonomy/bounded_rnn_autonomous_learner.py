"""Bounded autonomous consumer for Rust-admitted integer-RNN candidates."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from autonomy.topology_integer_rnn import TopologyIntegerRNN, VerifiedExecutionTeacher


class AdmissionError(RuntimeError):
    pass


def run_bounded_cycle(
    receipt_path: str | Path,
    *,
    database: str | Path,
    gate_binary: str | Path,
    output_path: str | Path,
) -> dict:
    """Run one read-only route replay after independent Rust admission."""
    receipt_file = Path(receipt_path)
    gate = subprocess.run([str(gate_binary), str(receipt_file)], capture_output=True, text=True)
    if gate.returncode != 0:
        raise AdmissionError(gate.stderr.strip() or gate.stdout.strip() or "Rust gate denied")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    candidate = TopologyIntegerRNN.load_candidate(
        receipt["candidate_path"], expected_topology_sha256=receipt["topology_sha256"]
    )
    teacher = VerifiedExecutionTeacher(database, anchor_width=candidate.input_size)
    ids = receipt["verified_receipt_ids"]
    seen = teacher.primitive_route(ids[0])
    held_out = teacher.primitive_route(ids[1])
    replay_seen = candidate.route_score([a.vector for a in seen])
    replay_held_out = candidate.route_score([a.vector for a in held_out])
    output = {
        "schema": "viv-bounded-rnn-autonomous-cycle-v1",
        "status": "PASS",
        "admission_receipt": str(receipt_file),
        "candidate_weights_sha256": candidate._weights_digest(),
        "replayed_seen_score": replay_seen,
        "replayed_held_out_score": replay_held_out,
        "bounded_steps": 1,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(output, sort_keys=True, indent=2), encoding="utf-8")
    temp.replace(target)
    return output


__all__ = ["AdmissionError", "run_bounded_cycle"]
