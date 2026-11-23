"""Silicon proof for the topology-anchored integer recurrent core."""

from autonomy.topology_integer_rnn import TopologyIntegerRNN


def test_integer_recurrence_and_reset() -> None:
    network = TopologyIntegerRNN(2, 2, scale_bits=0, use_gpu=True)
    network.set_weights([[1, 0], [0, 1]], [[1, 0], [0, 1]])
    first = network.step([3, 4])
    second = network.step([1, 2])
    assert first == (3, 4)
    assert second == (4, 6)
    assert all(isinstance(value, int) for value in second)
    network.reset()
    assert network.step([3, 4]) == (3, 4)


def test_bounded_traversal_receipt() -> None:
    network = TopologyIntegerRNN(2, 2, scale_bits=0, state_limit=10, use_gpu=True)
    network.set_weights([[4, 0], [0, 4]], [[4, 0], [0, 4]])
    receipt = network.traverse([[3, 0], [3, 0], [3, 0]])
    assert receipt.steps == 3
    assert receipt.hidden == (10, 0)
    assert receipt.backend in {"cupy-int32", "numpy-int64"}

