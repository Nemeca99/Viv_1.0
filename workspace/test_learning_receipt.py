"""End-to-end receipt proof for a held-out learning candidate."""

import json
from pathlib import Path

from autonomy.topology_integer_rnn import TopologyIntegerRNN, HeldOutEvaluation


def test_learning_receipt_records_pass_or_hold_without_promotion() -> None:
    network = TopologyIntegerRNN(2, 2, scale_bits=0, state_limit=64, use_gpu=True)
    network.set_weights([[1, 0], [0, 1]], [[1, 0], [0, 1]])
    receipt_path = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\test_learning_receipt.json")
    payload = network.write_learning_receipt(
        receipt_path,
        candidate_path=r"L:\LocalCoder\workspace\autonomy\.tmp\candidate.json",
        topology_sha256="a" * 64,
        receipt_ids=["verified-1"],
        evaluation=HeldOutEvaluation(10, 8, 7, True),
    )
    loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert payload == loaded
    assert loaded["status"] == "PASS"
    assert loaded["evaluation"]["held_out_margin"] == 1
