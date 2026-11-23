"""PARTIAL/NULL learning, contradiction, journal, and integer credit proofs."""

import json
from pathlib import Path

from autonomy.deterministic_containment import ContainmentEngine, JsonFactCartridge, CONTAINED, PARTIAL, NULL


MEMORY = Path(r"L:\LocalCoder\workspace\aios_rebuild\memory\persistent_memory.json")


def test_contradiction_rejects_and_noncontradiction_commits() -> None:
    cartridge = JsonFactCartridge("memory", MEMORY)
    engine = ContainmentEngine([cartridge])
    partial = engine.query("What household animal?")
    assert partial.state == PARTIAL
    journal = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\containment_learning_journal.jsonl")
    if journal.exists():
        journal.unlink()
    rejected = engine.learn_after(
        partial, cartridge_id="memory",
        fact={"subject": "fiancee", "relation": "is_named", "object": "Sam", "raw": "My fiancee is named Sam."},
        journal_path=journal,
    )
    assert rejected["decision"] == "REJECT"
    committed = engine.learn_after(
        partial, cartridge_id="memory",
        fact={"subject": "favorite_color", "relation": "is_named", "object": "blue", "raw": "My favorite color is blue."},
        journal_path=journal,
    )
    assert committed["decision"] == "COMMIT"
    assert engine.query("What is my favorite color?").state == CONTAINED
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 2
    assert all(isinstance(value, int) for value in engine.trace_counters.values())
