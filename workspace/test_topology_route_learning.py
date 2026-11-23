"""Proof that route reinforcement changes only in-memory weights."""

from autonomy.topology_integer_rnn import ReadOnlyTopologyAnchors, TopologyIntegerRNN


DB = r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3"


def test_positive_and_negative_route_updates_are_bounded_and_receipted() -> None:
    anchors = ReadOnlyTopologyAnchors(DB, width=2).load([
        "neuron:func:make_greeting",
        "neuron:var:name:scope_1",
    ])
    route = [anchor.vector for anchor in anchors]
    network = TopologyIntegerRNN(2, 2, scale_bits=0, state_limit=32, use_gpu=True)
    network.set_weights([[1, 0], [0, 1]], [[0, 0], [0, 0]])
    before = network.weight_hidden.copy()
    positive = network.learn_route(route, reward=1)
    assert positive.transitions == 1
    assert positive.changed_cells > 0
    assert positive.weights_sha256
    assert (network.weight_hidden != before).any()
    negative = network.learn_route(route, reward=-1)
    assert negative.transitions == 1
    assert negative.changed_cells > 0
    assert all(abs(int(value)) <= 32 for value in network.weight_hidden.flat)
