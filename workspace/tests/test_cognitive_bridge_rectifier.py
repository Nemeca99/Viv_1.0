"""Unit tests for Full Bridge Cognitive Rectifier (Graetz Diamond Semantic Engine)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest
import autonomy.cognitive_bridge_rectifier as rectifier_module
from autonomy.cognitive_bridge_rectifier import (
    DIMENSIONAL_AXIS_REGISTRY,
    DiodeConductionPath,
    FullBridgeCognitiveRectifier,
    SmoothingCapacitor,
)


@pytest.fixture(autouse=True)
def sqlite_antipodal_ontology(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a test SQLite ontology with verified OPPOSES edges so tests never rely on Python hardcoding."""
    db_path = tmp_path / "test_lexicon_ontology.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE lexical_entities (entity_id INTEGER PRIMARY KEY, lemma TEXT UNIQUE)")
        con.execute(
            "CREATE TABLE semantic_relations ("
            "relation_id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "source_entity_id INTEGER, relation_type TEXT, target_entity_id INTEGER, "
            "confidence REAL, evidence_text TEXT)"
        )
        words = ["hot", "cold", "bright", "dark", "true", "false", "bird", "table", "apple", "frog", "cloud"]
        for idx, w in enumerate(words, 1):
            con.execute("INSERT INTO lexical_entities (entity_id, lemma) VALUES (?, ?)", (idx, w))
        id_map = {w: idx for idx, w in enumerate(words, 1)}
        pairs = [
            ("hot", "cold", "AXIS:thermal"),
            ("bright", "dark", "AXIS:luminance"),
            ("true", "false", "AXIS:veracity"),
        ]
        for pos_w, neg_w, axis in pairs:
            con.execute(
                "INSERT INTO semantic_relations (source_entity_id, relation_type, target_entity_id, confidence, evidence_text) VALUES (?, 'OPPOSES', ?, 0.99, ?)",
                (id_map[pos_w], id_map[neg_w], axis),
            )
            con.execute(
                "INSERT INTO semantic_relations (source_entity_id, relation_type, target_entity_id, confidence, evidence_text) VALUES (?, 'OPPOSES', ?, 0.99, ?)",
                (id_map[neg_w], id_map[pos_w], axis),
            )
        con.commit()
    monkeypatch.setattr(rectifier_module, "ONTOLOGY_DB", db_path)
    yield db_path


def test_positive_pole_conduction():
    """Verify positive half-cycle (+V) conduction through D1 and D4 to positive DC rail."""
    rectifier = FullBridgeCognitiveRectifier()
    res = rectifier.rectify("hot")

    assert res["circuit"] == "FULL_BRIDGE_RECTIFIER"
    assert res["status"] == "RECTIFIED_DC_CONDUCTION"
    assert res["word"] == "hot"
    assert res["axis"] == "AXIS:thermal"
    assert res["input_phase"] == "+V_PEAK"
    assert res["v_in"] == 1.0
    assert res["v_out_rectified"] == 1.0
    assert len(res["active_diodes"]) == 2
    diode_ids = [d["diode"] for d in res["active_diodes"]]
    assert "D1" in diode_ids
    assert "D4" in diode_ids
    assert "Ground(cold)" in res["conduction_path"]


def test_negative_pole_rectification():
    """Verify negative half-cycle (-V) inverted rectification through D2 and D3 into unipolar positive DC."""
    rectifier = FullBridgeCognitiveRectifier()
    res = rectifier.rectify("cold")

    assert res["circuit"] == "FULL_BRIDGE_RECTIFIER"
    assert res["status"] == "RECTIFIED_DC_CONDUCTION"
    assert res["word"] == "cold"
    assert res["axis"] == "AXIS:thermal"
    assert res["input_phase"] == "-V_PEAK"
    assert res["v_in"] == -1.0
    # Must be unipolar positive DC drive: |V_in| = +1.0
    assert res["v_out_rectified"] == 1.0
    assert len(res["active_diodes"]) == 2
    diode_ids = [d["diode"] for d in res["active_diodes"]]
    assert "D2" in diode_ids
    assert "D3" in diode_ids
    assert "Ground(hot)" in res["conduction_path"]


def test_antipodal_pair_both_conduct_to_same_axis():
    """Verify that both ends of an antipodal pair rectify to identical dimensional axis."""
    rectifier = FullBridgeCognitiveRectifier()
    res_pos = rectifier.rectify("true")
    res_neg = rectifier.rectify("false")

    assert res_pos["axis"] == "AXIS:veracity"
    assert res_neg["axis"] == "AXIS:veracity"
    assert res_pos["v_out_rectified"] == 1.0
    assert res_neg["v_out_rectified"] == 1.0


def test_open_circuit_fail_closed_for_concrete_entities():
    """Concrete nouns (e.g. bird, table, apple) must fail closed as open circuit impedance."""
    rectifier = FullBridgeCognitiveRectifier()
    
    for concrete in ["bird", "table", "apple", "frog", "cloud"]:
        res = rectifier.rectify(concrete)
        assert res["status"] == "OPEN_CIRCUIT_IMPEDANCE"
        assert res["rectified_dc_out"] == 0.0
        assert res["active_diodes"] == []
        assert res["axis"] is None


def test_smoothing_capacitor_charge_and_ripple():
    """Verify smoothing capacitor peak detection and ripple reduction."""
    cap = SmoothingCapacitor(capacitance=250.0, load_resistance=100.0)

    # Initial state
    assert cap.v_dc == 0.0

    # First pulse
    v_dc, ripple = cap.update(1.0)
    assert v_dc == 1.0
    assert ripple == 0.0

    # Multiple steady DC pulses: ripple should approach 0
    for _ in range(10):
        v_dc, ripple = cap.update(1.0)

    assert v_dc == 1.0
    assert ripple == 0.0


def test_circuit_telemetry_accumulation():
    """Verify cumulative circuit telemetry reports pulses and axis distribution accurately."""
    rectifier = FullBridgeCognitiveRectifier()
    rectifier.rectify("hot")
    rectifier.rectify("cold")
    rectifier.rectify("dark")
    rectifier.rectify("bright")
    rectifier.rectify("bird")  # Open circuit

    telemetry = rectifier.get_circuit_telemetry()
    assert telemetry["total_ac_pulses"] == 5
    assert telemetry["total_rectified_energy"] == 4.0
    assert telemetry["active_axes_count"] == 2
    assert telemetry["axis_distribution"]["AXIS:thermal"] == 2
    assert telemetry["axis_distribution"]["AXIS:luminance"] == 2
