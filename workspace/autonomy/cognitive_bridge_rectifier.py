r"""Full Bridge Cognitive Rectifier (Graetz Diamond Semantic Engine).

Implements a 4-diode bridge rectifier topology over semantic dualities and antipodal polarities.
Converts alternating semantic oscillations (AC: thesis/antithesis, hot/cold, true/false)
into unipolar, unidirectional cognitive drive (DC) across grounded dimensional axes,
smoothed by a simulated capacitor (The Dream Phase).

Circuit Topology:
           [ Positive Anode (P+) ]
                  /        \
          (D1)   /          \   (D2)
                v            v
      [ Forward Rail ]   [ Inverted Rail ]
                \            /
          (D3)   \          /   (D4)
                  v        v
           [ Negative Anode (P-) ]
                     |
                     v
         [ UNIPOLAR AXIS LOAD: V_DC ]
                     |
            [ SMOOTHING CAPACITOR ] (Dream Pass)
"""

from __future__ import annotations

import math
from pathlib import Path
import sqlite3
import time
from typing import Any


ONTOLOGY_DB = Path(__file__).resolve().parent / "data" / "lexicon_ontology.db"

# Empty by default: all dimensional axes must emerge from SQLite ontology edges.
# Exported only as an empty mapping for backwards import compatibility.
DIMENSIONAL_AXIS_REGISTRY: dict[str, tuple[str, str, str]] = {}


def _topological_axis(word: str) -> tuple[str, str, str] | None:
    """Resolve an antipodal axis strictly from verified SQL edges (no hardcoded Python dictionary)."""
    w_clean = word.casefold().strip()
    if ONTOLOGY_DB.is_file():
        try:
            with sqlite3.connect(f"file:{ONTOLOGY_DB.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
                row = con.execute(
                    "SELECT source.lemma, target.lemma, relation.relation_id, relation.evidence_text "
                    "FROM semantic_relations AS relation "
                    "JOIN lexical_entities AS source ON source.entity_id=relation.source_entity_id "
                    "JOIN lexical_entities AS target ON target.entity_id=relation.target_entity_id "
                    "WHERE lower(source.lemma)=? AND relation.relation_type IN ('OPPOSES','OPPOSITE_OF') "
                    "ORDER BY relation.confidence DESC, relation.relation_id LIMIT 1",
                    (w_clean,),
                ).fetchone()
            if row:
                source, target, relation_id, evidence = (str(row[0]), str(row[1]), int(row[2]), str(row[3] or ""))
                axis_label = evidence if evidence.startswith("AXIS:") else f"AXIS:OPPOSES:{relation_id}"
                # Canonicalize positive/negative pole order deterministically by relation pair
                rev = None
                with sqlite3.connect(f"file:{ONTOLOGY_DB.resolve()}?mode=ro", uri=True, timeout=1.0) as con:
                    rev = con.execute(
                        "SELECT relation.relation_id FROM semantic_relations AS relation "
                        "JOIN lexical_entities AS s ON s.entity_id=relation.source_entity_id "
                        "JOIN lexical_entities AS t ON t.entity_id=relation.target_entity_id "
                        "WHERE lower(s.lemma)=? AND lower(t.lemma)=? AND relation.relation_type IN ('OPPOSES','OPPOSITE_OF') LIMIT 1",
                        (target.casefold(), source.casefold()),
                    ).fetchone()
                if rev and int(rev[0]) < relation_id:
                    return axis_label, target, source
                return axis_label, source, target
        except sqlite3.Error:
            pass
    return None


class DiodeConductionPath:
    """Represents a single directed diode in the 4-diode Graetz diamond."""

    def __init__(self, diode_id: str, anode: str, cathode: str, forward_bias: bool):
        self.diode_id = diode_id
        self.anode = anode
        self.cathode = cathode
        self.forward_bias = forward_bias

    def conducts(self, input_polarity: float) -> bool:
        """Conducts only if forward biased relative to the input wave polarity."""
        if self.forward_bias:
            return input_polarity > 0.0
        return input_polarity < 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "diode": self.diode_id,
            "anode": self.anode,
            "cathode": self.cathode,
            "bias": "FORWARD" if self.forward_bias else "REVERSE_RECTIFIED",
        }


class SmoothingCapacitor:
    """Simulates an electrolytic capacitor filtering cognitive AC ripple into pure DC."""

    def __init__(self, capacitance: float = 250.0, load_resistance: float = 100.0):
        self.capacitance = capacitance  # Aligned with 250-word Dream Phase milestone
        self.load_resistance = load_resistance
        self.tau = capacitance * load_resistance  # RC time constant
        self.charge: float = 0.0
        self.v_dc: float = 0.0
        self.ripple_voltage: float = 0.0
        self.history: list[float] = []

    def update(self, v_in_rectified: float) -> tuple[float, float]:
        """Update capacitor charge with new rectified pulsating DC input.
        
        Returns (v_dc, ripple_voltage).
        """
        self.history.append(v_in_rectified)
        if len(self.history) > 50:
            self.history.pop(0)

        # Peak detection with RC decay
        if v_in_rectified >= self.v_dc:
            self.v_dc = v_in_rectified
        else:
            # Exponential decay between pulses
            dt_step = 1.0 / max(1.0, self.capacitance)
            decay_factor = math.exp(-dt_step / (self.tau / 1000.0))
            self.v_dc = self.v_dc * decay_factor

        # Calculate ripple factor: standard deviation of recent outputs
        if len(self.history) >= 2:
            mean = sum(self.history) / len(self.history)
            variance = sum((x - mean) ** 2 for x in self.history) / len(self.history)
            self.ripple_voltage = math.sqrt(variance)
        else:
            self.ripple_voltage = 0.0

        return self.v_dc, self.ripple_voltage


class FullBridgeCognitiveRectifier:
    """4-Diode Semantic Rectifier: converts bidirectional antipodes into unipolar DC drive."""

    def __init__(self):
        self.capacitor = SmoothingCapacitor(capacitance=250.0)
        self.total_ac_pulses = 0
        self.total_rectified_energy = 0.0
        self.rectified_axis_hits: dict[str, int] = {}

    def rectify(self, word: str) -> dict[str, Any]:
        """Pass an input word through the Full Bridge Rectifier circuit."""
        w = word.lower().strip()
        self.total_ac_pulses += 1

        axis_data = _topological_axis(w)
        if axis_data is None:
            # Infinite impedance: non-conducting open circuit
            return {
                "circuit": "FULL_BRIDGE_RECTIFIER",
                "status": "OPEN_CIRCUIT_IMPEDANCE",
                "word": w,
                "input_waveform": "ZERO_POLARITY",
                "rectified_dc_out": 0.0,
                "conducting_diodes": [],
                "active_diodes": [],
                "axis": None,
                "reason": "Concrete entity or non-scalar concept has zero AC potential across dimensional bridge.",
                "ripple_voltage": self.capacitor.ripple_voltage,
            }

        axis, p_plus, p_minus = axis_data
        self.rectified_axis_hits[axis] = self.rectified_axis_hits.get(axis, 0) + 1

        # Determine input phase: Positive pole (+1.0) or Negative pole (-1.0)
        is_positive = (w == p_plus)
        v_in = 1.0 if is_positive else -1.0

        # Construct the 4-diode bridge
        d1 = DiodeConductionPath("D1", p_plus, axis, forward_bias=True)
        d2 = DiodeConductionPath("D2", p_minus, axis, forward_bias=False)
        d3 = DiodeConductionPath("D3", axis, p_minus, forward_bias=True)
        d4 = DiodeConductionPath("D4", axis, p_plus, forward_bias=False)

        # Full Bridge Rectification: Regardless of + or - wave, output is +|V|
        if is_positive:
            # Positive half-cycle conducts through D1 and D4
            active_diodes = [d1.to_dict(), d4.to_dict()]
            conduction_path = f"{p_plus} -> [D1] -> {axis} -> [D4] -> Ground({p_minus})"
        else:
            # Negative half-cycle conducts through D2 and D3
            active_diodes = [d2.to_dict(), d3.to_dict()]
            conduction_path = f"{p_minus} -> [D2] -> {axis} -> [D3] -> Ground({p_plus})"

        v_rectified = abs(v_in)
        self.total_rectified_energy += v_rectified

        # Smooth through capacitor
        v_dc_smoothed, ripple = self.capacitor.update(v_rectified)

        return {
            "circuit": "FULL_BRIDGE_RECTIFIER",
            "status": "RECTIFIED_DC_CONDUCTION",
            "word": w,
            "axis": axis,
            "poles": {"positive": p_plus, "negative": p_minus},
            "input_phase": "+V_PEAK" if is_positive else "-V_PEAK",
            "v_in": v_in,
            "v_out_rectified": v_rectified,
            "v_dc_smoothed": round(v_dc_smoothed, 4),
            "ripple_voltage": round(ripple, 4),
            "conduction_path": conduction_path,
            "active_diodes": active_diodes,
            "conducting_diodes": active_diodes,
            "rectified_hits_on_axis": self.rectified_axis_hits[axis],
            "verified": True,
        }

    def get_circuit_telemetry(self) -> dict[str, Any]:
        """Return cumulative telemetry of the cognitive rectifier."""
        return {
            "total_ac_pulses": self.total_ac_pulses,
            "total_rectified_energy": self.total_rectified_energy,
            "active_axes_count": len(self.rectified_axis_hits),
            "axis_distribution": self.rectified_axis_hits,
            "smoothed_dc_voltage": round(self.capacitor.v_dc, 4),
            "ripple_factor": round(self.capacitor.ripple_voltage, 4),
        }
