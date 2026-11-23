"""Proof that only verified execution receipts teach the integer recurrent core."""

from autonomy.topology_integer_rnn import TopologyIntegerRNN, VerifiedExecutionTeacher


DB = r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3"


def test_graduated_primitive_teaches_function_route() -> None:
    teacher = VerifiedExecutionTeacher(DB, anchor_width=2)
    anchors = teacher.primitive_route("AUTONOMOUS_CHALLENGE_26_RECURSIVE_QUICKSORT")
    assert anchors
    network = TopologyIntegerRNN(2, 2, scale_bits=0, state_limit=64, use_gpu=True)
    receipt = network.learn_route([anchor.vector for anchor in anchors], reward=1)
    assert receipt.reward == 1
    assert receipt.transitions == max(0, len(anchors) - 1)
    assert receipt.weights_sha256


def test_unverified_primitive_is_rejected() -> None:
    teacher = VerifiedExecutionTeacher(DB, anchor_width=2)
    try:
        teacher.primitive_route("AUTONOMOUS_CHALLENGE_27_RECURSIVE_EXPRESSION_EVALUATOR")
    except (KeyError, ValueError):
        return
    raise AssertionError("unverified primitive was accepted as a teacher route")
