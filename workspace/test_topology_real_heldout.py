"""Real SQLite topology retrieval/generalization separation proof."""

from autonomy.topology_integer_rnn import TopologyIntegerRNN, VerifiedExecutionTeacher


DB = r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3"


def test_single_route_candidate_is_not_mislabeled_as_generalization() -> None:
    teacher = VerifiedExecutionTeacher(DB, anchor_width=4)
    seen = teacher.primitive_route("AUTONOMOUS_CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR")
    held_out = teacher.primitive_route("AUTONOMOUS_CHALLENGE_21_RECURSIVE_MAZE_SOLVER")
    seen_vectors = [anchor.vector for anchor in seen]
    held_out_vectors = [anchor.vector for anchor in held_out]
    network = TopologyIntegerRNN(4, 4, scale_bits=0, state_limit=128, use_gpu=True)
    network.set_weights([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], [[0] * 4 for _ in range(4)])
    network.learn_route(seen_vectors, reward=1)
    result = network.evaluate_held_out(seen_vectors, held_out_vectors, list(reversed(held_out_vectors)))
    assert result.seen_score > 0
    # One training route is insufficient evidence after the structural
    # representation change. The evaluator must fail closed here; the
    # leave-one-route-out matrix is the stronger multi-route experiment.
    assert result.held_out_score <= result.negative_score
    assert not result.passed
