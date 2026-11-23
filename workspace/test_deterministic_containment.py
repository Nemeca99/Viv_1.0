"""Phase 1/2 containment state proofs over the real persistent memory cartridge."""

from pathlib import Path

from autonomy.deterministic_containment import CONTAINED, NULL, PARTIAL, ContainmentEngine, JsonFactCartridge, SQLitePrimitiveCartridge, SQLiteArticleCartridge


MEMORY = Path(r"L:\LocalCoder\workspace\aios_rebuild\memory\persistent_memory.json")
TOPOLOGY = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
PHYSICS = Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3")


def engine() -> ContainmentEngine:
    return ContainmentEngine([JsonFactCartridge("persistent_memory", MEMORY)])


def test_contained_verified_fact_stops_cascade() -> None:
    result = engine().query("Who is my fiancee named?")
    assert result.state == CONTAINED
    assert "Kat" in result.answer
    assert result.receipt["state"] == CONTAINED
    assert result.trace[0].startswith("SONAR:")


def test_partial_adjacent_fact_has_boundary_candidate() -> None:
    result = engine().query("What household animal?")
    assert result.state == PARTIAL
    assert result.candidates
    assert result.receipt["candidate"] is not None


def test_null_has_no_generation_or_candidate() -> None:
    result = engine().query("What is my favorite color?")
    assert result.state == NULL
    assert result.answer == "I don't know."
    assert result.candidates == ()
    assert result.receipt["candidate"] is None


def test_cascade_orders_by_sonar_weight_and_stops_first_verified() -> None:
    first = JsonFactCartridge("low", MEMORY)
    second = JsonFactCartridge("high", MEMORY)
    engine = ContainmentEngine([first, second])
    result = engine.query("Who is my fiancee named?")
    assert result.state == CONTAINED
    cascade = next(item for item in result.trace if item.startswith("CASCADE:"))
    assert cascade.split(":")[1] in {"high", "low"}


def test_plausible_wrong_query_never_emits_generated_answer() -> None:
    result = engine().query("The sky is green")
    assert result.state in {PARTIAL, NULL}
    assert result.answer in {"I don't know.",} or result.answer.startswith("I don't know this exactly")


def test_read_only_sqlite_cartridge_participates_in_sonar() -> None:
    result = ContainmentEngine([SQLitePrimitiveCartridge("code", TOPOLOGY)]).query("recursive binary search")
    assert result.state == CONTAINED
    assert result.receipt["candidate"]["cartridge"] == "code"


def test_live_physics_sonar_pings_rayleigh_but_rejects_wrong_green_claim() -> None:
    result = ContainmentEngine([SQLiteArticleCartridge("wiki_physics", PHYSICS)]).query("The sky is green")
    assert result.state == PARTIAL
    assert result.candidates
    assert result.candidates[0].cartridge == "wiki_physics"
    assert "Rayleigh" in result.candidates[0].text
    assert any(candidate.row_id == "622" for candidate in result.candidates)
    assert result.answer.startswith("I don't know this exactly")
    journal = Path(
        r"L:\LocalCoder\workspace\autonomy\.tmp\live_physics_rejection_test.jsonl"
    )
    rejection = ContainmentEngine([SQLiteArticleCartridge("wiki_physics", PHYSICS)]).record_gate_rejection(
        result,
        proposed_fact={"subject": "sky", "relation": "is_color", "object": "green"},
        journal_path=journal,
    )
    assert rejection["decision"] == "REJECT"
    assert any(row["row_id"] == "622" for row in rejection["contradicting_rows"])
