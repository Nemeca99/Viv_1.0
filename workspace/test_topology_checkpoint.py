"""Persistence and held-out reload proof for integer RNN candidates."""

from pathlib import Path

from autonomy.topology_integer_rnn import TopologyIntegerRNN


def test_candidate_checkpoint_reloads_and_rejects_wrong_topology() -> None:
    network = TopologyIntegerRNN(2, 2, scale_bits=0, state_limit=64, use_gpu=True)
    network.set_weights([[1, 2], [3, 4]], [[5, 6], [7, 8]])
    path = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\test_candidate_checkpoint.json")
    saved = network.save_candidate(path, topology_sha256="topology-a", receipt_ids=["receipt-1"])
    restored = TopologyIntegerRNN.load_candidate(path, expected_topology_sha256="topology-a")
    assert restored._weights_digest() == saved["weights_sha256"]
    assert restored.traverse([[1, 0], [0, 1]]).hidden == network.traverse([[1, 0], [0, 1]]).hidden
    try:
        TopologyIntegerRNN.load_candidate(path, expected_topology_sha256="topology-b")
    except ValueError as error:
        assert "topology hash" in str(error)
    else:
        raise AssertionError("wrong topology checkpoint was accepted")
