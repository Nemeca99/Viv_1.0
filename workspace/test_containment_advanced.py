"""Nested fork/join and round-trip identity/drift proofs."""

from autonomy.containment_advanced import fork_join, round_trip_fact


def test_nested_fork_join_credits_local_child_traces() -> None:
    receipt = fork_join("parent", [("wiki_physics", lambda: True), ("viv_alu_opcodes", lambda: True)])
    assert receipt.status == "PASS"
    assert len(receipt.children) == 2
    assert all(child.local_trace for child in receipt.children)


def test_nested_fork_join_keeps_successful_child_when_sibling_fails() -> None:
    receipt = fork_join("parent", [("retrieval", lambda: True), ("alu", lambda: False)])
    assert receipt.status == "HOLD"
    assert receipt.children[0].status == "PASS"
    assert receipt.children[1].status == "HOLD"
    assert receipt.children[0].local_trace == ("CHILD:retrieval",)


def test_round_trip_identity_passes() -> None:
    result = round_trip_fact({"subject": "sky", "relation": "scatters", "object": "blue_light"})
    assert result["status"] == "PASS"
    assert result["original_sha256"] == result["recovered_sha256"]


def test_round_trip_drift_fails_closed() -> None:
    result = round_trip_fact({"subject": "sky", "relation": "scatters", "object": "blue_light"}, inject_drift=True)
    assert result["status"] == "HOLD"
    assert result["original_sha256"] != result["recovered_sha256"]
