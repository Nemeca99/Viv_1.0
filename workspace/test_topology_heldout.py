"""Held-out route proof for the integer topology recurrent learner."""

from autonomy.topology_integer_rnn import TopologyIntegerRNN


def test_unseen_route_beats_reversed_route_after_learning() -> None:
    network = TopologyIntegerRNN(2, 2, scale_bits=0, state_limit=128, use_gpu=True)
    network.set_weights([[1, 0], [0, 1]], [[0, 0], [0, 0]])
    seen = [[2, 1], [1, 2]]
    held_out = [[3, 1], [1, 3]]
    negative = list(reversed(held_out))
    network.learn_route(seen, reward=1)
    result = network.evaluate_held_out(seen, held_out, negative)
    assert result.passed
    assert result.held_out_score > result.negative_score
