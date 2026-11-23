"""Proof that autonomous consumption requires Rust admission and reloads state."""

import json
from pathlib import Path

from autonomy.bounded_rnn_autonomous_learner import AdmissionError, run_bounded_cycle


ROOT = Path(r"L:\LocalCoder\workspace")
DB = ROOT / "autonomy" / "viv_code_topology.sqlite3"
RECEIPT = ROOT / "autonomy" / ".tmp" / "rnn_learning_receipt.json"
GATE = ROOT / "hive_control" / "target" / "debug" / "rnn_candidate_gate.exe"


def test_bounded_cycle_consumes_admitted_candidate() -> None:
    output = run_bounded_cycle(
        RECEIPT,
        database=DB,
        gate_binary=GATE,
        output_path=ROOT / "autonomy" / ".tmp" / "bounded_cycle_receipt.json",
    )
    assert output["status"] == "PASS"
    assert output["bounded_steps"] == 1
    assert output["replayed_held_out_score"] > 0


def test_bounded_cycle_rejects_hold_receipt() -> None:
    hold = ROOT / "autonomy" / ".tmp" / "rnn_learning_hold.json"
    try:
        run_bounded_cycle(
            hold,
            database=DB,
            gate_binary=GATE,
            output_path=ROOT / "autonomy" / ".tmp" / "should_not_exist.json",
        )
    except AdmissionError:
        return
    raise AssertionError("autonomous cycle accepted a denied receipt")
