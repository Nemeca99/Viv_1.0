"""Read-only integration proof from SQLite topology anchors into integer RNN."""

import sqlite3

from autonomy.topology_integer_rnn import ReadOnlyTopologyAnchors, TopologyIntegerRNN


DB = r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3"


def test_verified_topology_route_is_read_only_and_reproducible() -> None:
    with sqlite3.connect(DB) as conn:
        edge = conn.execute(
            "SELECT source_id, target_id FROM viv_code_synapses ORDER BY source_id, target_id LIMIT 1"
        ).fetchone()
    assert edge is not None
    source, target = edge
    anchors = ReadOnlyTopologyAnchors(DB, width=2).load([source, target])
    network = TopologyIntegerRNN(2, 2, scale_bits=0, use_gpu=True)
    network.set_weights([[1, 0], [0, 1]], [[1, 0], [0, 1]])
    receipt_a = network.traverse([anchor.vector for anchor in anchors])
    network.reset()
    receipt_b = network.traverse([anchor.vector for anchor in anchors])
    assert receipt_a.hidden == receipt_b.hidden
    assert receipt_a.steps == 2
    assert receipt_a.backend in {"cupy-int32", "numpy-int64"}
