"""Grounded known/unknown answer proof for the isolated RNN bridge."""

import hashlib
from pathlib import Path

from autonomy.grounded_rnn_answer_bridge import GroundedRNNAnswerBridge, NULL_UNLEARNED_ENTITY


ROOT = Path(r"L:\LocalCoder\workspace")
MEMORY = ROOT / "aios_rebuild" / "memory" / "persistent_memory.json"
DB = ROOT / "autonomy" / "viv_code_topology.sqlite3"
CANDIDATE = ROOT / "autonomy" / ".tmp" / "rnn_candidate.json"


def test_known_fact_is_answered_from_memory_and_unknown_fails_closed() -> None:
    topology_hash = hashlib.sha256(DB.read_bytes()).hexdigest()
    bridge = GroundedRNNAnswerBridge(MEMORY, CANDIDATE, topology_sha256=topology_hash)
    known = bridge.answer("Who is my fiancee named?")
    assert known["status"] == "GROUNDED"
    assert "Kat" in known["answer"]
    assert known["evidence"]
    assert known["evidence_receipt"]["schema"] == "viv-grounded-rnn-answer-receipt-v1"
    unknown = bridge.answer("What is my dog's name?")
    assert unknown["answer"] == NULL_UNLEARNED_ENTITY
    assert unknown["evidence"] == []
    assert unknown["evidence_receipt"]["evidence"] == []


def test_held_out_fact_and_reload_produce_receipts() -> None:
    topology_hash = hashlib.sha256(DB.read_bytes()).hexdigest()
    first = GroundedRNNAnswerBridge(MEMORY, CANDIDATE, topology_sha256=topology_hash)
    held_out = first.answer("Who are her kids?")
    reloaded = GroundedRNNAnswerBridge(MEMORY, CANDIDATE, topology_sha256=topology_hash)
    replay = reloaded.answer("Who are her kids?")
    assert held_out["status"] == "GROUNDED"
    assert "Alex" in held_out["answer"] and "Aiden" in held_out["answer"]
    assert held_out["answer"] == replay["answer"]
    assert held_out["evidence_receipt"] == replay["evidence_receipt"]


def test_bounded_known_unknown_fact_matrix() -> None:
    topology_hash = hashlib.sha256(DB.read_bytes()).hexdigest()
    bridge = GroundedRNNAnswerBridge(MEMORY, CANDIDATE, topology_sha256=topology_hash)
    known_questions = [
        "Who is my fiancee named?",
        "Who is my kid Alex?",
        "Who are Alex and Aiden?",
        "What household pets do I have?",
    ]
    unknown_questions = [
        "What is my dog's name?",
        "What is my favorite color?",
        "Where did I go to college?",
        "What is my cat's name?",
    ]
    for question in known_questions:
        result = bridge.answer(question)
        assert result["status"] == "GROUNDED", question
        assert result["evidence"], question
        assert result["evidence_receipt"]["evidence"] == result["evidence"]
    for question in unknown_questions:
        result = bridge.answer(question)
        assert result["answer"] == NULL_UNLEARNED_ENTITY, question
        assert result["status"] == "HOLD", question
        assert result["evidence"] == [], question
        assert result["evidence_receipt"]["evidence"] == []
