"""Causal Chain Engine: Multi-Clause Functional & Physical Causal Reasoning for Viv.

Implements the Second Layer of the Weft:
Transitions Viv from static taxonomic/physical atoms to dynamic causal sequences,
predictive cascades, and abductive physical troubleshooting without matrix multiplies.

Causal Conduits:
  1. Thermodynamic Expansion & Power:
     hot -> water -> boiling -> steam -> pressure -> force -> piston -> move
  2. Hydraulic Plumbing & Blockage Diagnosis:
     water -> pipe -> blockage -> stop (flow) -> pressure -> stress -> rupture -> leak
  3. Mechanical Leverage & Fastening:
     hand -> tool -> force -> lever -> torque -> bolt -> joint -> stop (movement)
  4. Pressure Safety Regulation:
     high -> pressure -> valve -> open -> steam -> low (pressure) -> prevent (rupture)
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Sequence

WORKSPACE = Path(r"L:\LocalCoder\workspace")
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import latest_run
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
from autonomy.conceptual_resonance_engine import ConceptualResonanceEngine

AUTONOMY_DATA = WORKSPACE / "autonomy/data"
DB_PATH = AUTONOMY_DATA / "lexicon_ontology.db"

# Multi-clause causal chains specification
# Each chain is a sequence of (source, relation, target, rationale)
CAUSAL_CHAINS = [
    {
        "domain": "thermodynamics_propulsion",
        "title": "Steam Power & Expansion Cascade",
        "description": "Thermal energy converts water to steam, building pressure that exerts mechanical force.",
        "steps": [
            ("hot", "HEATS", "water", "Thermal energy increases water kinetic excitation."),
            ("water", "CAUSES", "boiling", "Water heated to threshold undergoes boiling."),
            ("boiling", "GENERATES", "steam", "Vaporization generates high-volume steam gas."),
            ("steam", "INCREASES", "pressure", "Confined steam gas multiplies expansive pressure."),
            ("pressure", "EXERTS", "force", "Hydrostatic pressure exerts directional force against boundaries."),
            ("force", "ACTS_ON", "piston", "Expansive force pushes mechanical piston."),
            ("piston", "CAUSES", "move", "Displaced piston drives mechanical movement."),
        ],
    },
    {
        "domain": "hydraulics_plumbing",
        "title": "Pipe Blockage & Rupture Diagnosis",
        "description": "Flow obstruction in a confined conduit concentrates hydrostatic stress leading to structural rupture.",
        "steps": [
            ("water", "FLOWS_IN", "pipe", "Liquid water flows along hydraulic conduit."),
            ("pipe", "TRANSMITS", "flow", "Pipe conduit directs fluid volumetric flow."),
            ("pipe", "CONFINES", "pressure", "Pipe walls contain internal hydrostatic fluid pressure."),
            ("pipe", "EXPERIENCES", "stress", "Fluid pressure applies mechanical hoop stress to pipe walls."),
            ("pipe", "CONTAINS", "blockage", "Debris accumulation lodges inside pipe conduit."),
            ("blockage", "OBSTRUCTS", "flow", "Physical blockage impedes fluid velocity."),
            ("blockage", "BUILDS", "pressure", "Incompressible fluid accumulates high upstream pressure."),
            ("pressure", "CREATES", "stress", "Hydrostatic pressure exerts tensile stress on pipe walls."),
            ("stress", "CAUSES", "rupture", "Wall stress exceeding tensile limits causes structural rupture."),
            ("rupture", "PRODUCES", "leak", "Ruptured conduit releases fluid as an active leak."),
            ("leak", "OCCURS_IN", "pipe", "Escaping fluid issues from breach in damaged pipe."),
        ],
    },
    {
        "domain": "mechanics_fastening",
        "title": "Tool Mechanical Advantage & Joint Clamping",
        "description": "Human mechanical input through a lever magnifies torque to lock fasteners and arrest unwanted movement.",
        "steps": [
            ("hand", "GRIPS", "tool", "Operator applies manual grasp to mechanical tool."),
            ("hand", "APPLIES", "force", "Muscular contraction applies linear input force."),
            ("tool", "TRANSMITS", "lever", "Tool moment arm acts as a mechanical lever."),
            ("lever", "MULTIPLIES", "torque", "Moment arm multiplies rotational torque (tau = r x F)."),
            ("torque", "ROTATES", "bolt", "Applied torque turns threaded bolt into tapped hole."),
            ("bolt", "CLAMPS", "joint", "Axial screw tension clamps structural joint."),
            ("joint", "STOPS", "movement", "High static friction in clamped joint arrests movement."),
        ],
    },
    {
        "domain": "safety_regulation",
        "title": "Pressure Relief Valve Regulation",
        "description": "Automated pressure relief mitigates excessive stress and prevents conduit failure.",
        "steps": [
            ("high", "BUILDS", "pressure", "Excessive thermodynamic accumulation creates high pressure."),
            ("pressure", "ACTS_ON", "valve", "Elevated pressure overcomes safety valve spring force."),
            ("valve", "OPENS", "steam", "Displaced valve seat opens exhaust path for steam."),
            ("valve", "LOWERS", "pressure", "Fluid exhaust drops system pressure to safe threshold."),
            ("valve", "PREVENTS", "rupture", "Pressure reduction eliminates risk of vessel rupture."),
        ],
    },
]


class CausalChainEngine:
    def __init__(self, run_dir: Path | None = None, ontology_db: Path = DB_PATH):
        self.run_dir = run_dir or Path(latest_run())
        self.g_path = self.run_dir / "neuron_graph.sqlite3"
        self.ontology_db = ontology_db

        if not self.g_path.exists():
            raise FileNotFoundError(f"Neuron graph store not found at {self.g_path}")
        self.graph = SQLiteNeuronGraphStore(self.g_path, readonly=False)
        self.conn = self.graph.connection

    def close(self):
        self.graph.close()

    def compile_causal_chains_to_ontology(self) -> int:
        """Store causal chains in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS causal_implication_chains (
                chain_id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                step_sequence TEXT NOT NULL,
                created_utc TEXT NOT NULL
            )
        """)

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        for ch in CAUSAL_CHAINS:
            cur.execute("""
                SELECT chain_id FROM causal_implication_chains
                WHERE title = ?
            """, (ch["title"],))
            existing = cur.fetchone()

            steps_json = json.dumps(ch["steps"])
            if existing:
                cur.execute("""
                    UPDATE causal_implication_chains
                    SET domain = ?, description = ?, step_sequence = ?, created_utc = ?
                    WHERE chain_id = ?
                """, (ch["domain"], ch["description"], steps_json, now_utc, existing[0]))
            else:
                cur.execute("""
                    INSERT INTO causal_implication_chains (domain, title, description, step_sequence, created_utc)
                    VALUES (?, ?, ?, ?, ?)
                """, (ch["domain"], ch["title"], ch["description"], steps_json, now_utc))
                count += 1

        conn.commit()
        conn.close()
        return count

    def upsert_causal_link(self, src: str, dst: str, weight: int) -> bool:
        """Insert or reinforce a directional causal link."""
        existing = self.conn.execute(
            "SELECT reflector, ordinal FROM links WHERE source_id = ? AND peer_id = ?",
            (src, dst),
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE links SET weight = MIN(990000, weight + ?), pass_hits = pass_hits + 2, hot = 1 WHERE source_id = ? AND peer_id = ?",
                (weight // 3, src, dst),
            )
            return False
        else:
            max_ord = self.conn.execute(
                "SELECT COALESCE(MAX(ordinal), -1) FROM links WHERE source_id = ? AND reflector = 0",
                (src,),
            ).fetchone()[0]
            self.conn.execute(
                """INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256)
                   VALUES (?, 0, ?, ?, 1, ?, 1, 1, 0, 1, 1, '')""",
                (src, max_ord + 1, dst, weight),
            )
            return True

    def ground_causal_chains_into_lattice(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Inject directional causal conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        print("=" * 72)
        print("NOX FORGE · CAUSAL CHAIN ENGINE")
        print(f"Target Snapshot: {self.run_dir.name}")
        print(f"Compiling {len(CAUSAL_CHAINS)} Invariant Multi-Clause Physical Chains...")
        print("=" * 72, flush=True)

        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM links")
        initial_edges = cur.fetchone()[0]

        links_created = 0
        links_reinforced = 0
        total_transitions = 0

        for ch in CAUSAL_CHAINS:
            print(f"\n[CAUSAL CONDUIT] {ch['title']} ({ch['domain']})")
            for src_word, rel, dst_word, rationale in ch["steps"]:
                src_id = word_idx.get(src_word)
                dst_id = word_idx.get(dst_word)

                if src_id and dst_id:
                    # Forward Causal Arrow of Time (Primary gradient: W = 650,000)
                    is_new_fwd = self.upsert_causal_link(src_id, dst_id, forward_weight)
                    if is_new_fwd:
                        links_created += 1
                    else:
                        links_reinforced += 1

                    # Asymmetric Feedback Link (Secondary associative echo: W = 150,000)
                    is_new_rev = self.upsert_causal_link(dst_id, src_id, feedback_weight)
                    if is_new_rev:
                        links_created += 1
                    else:
                        links_reinforced += 1

                    total_transitions += 1
                    print(f"  Grounded: [{src_word}] --({rel})--> [{dst_word}]")
                else:
                    missing = [w for w, i in [(src_word, src_id), (dst_word, dst_id)] if not i]
                    print(f"  [MISSING TOKEN] Could not link {src_word} -> {dst_word} (missing: {missing})")

        self.conn.commit()

        cur.execute("SELECT count(*) FROM neurons")
        neurons_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM links")
        final_edges = cur.fetchone()[0]

        density = final_edges / neurons_count if neurons_count else 0

        # Update SHA-256 hash in learning.json
        new_g_hash = hashlib.sha256(self.g_path.read_bytes()).hexdigest()
        l_path = self.run_dir / "learning.json"
        if l_path.exists():
            l_data = json.loads(l_path.read_text(encoding="utf-8"))
            if "snapshot_hashes" in l_data:
                l_data["snapshot_hashes"]["neuron_graph.sqlite3"] = new_g_hash
                l_path.write_text(json.dumps(l_data, indent=2), encoding="utf-8")

        summary = {
            "initial_edges": initial_edges,
            "final_edges": final_edges,
            "links_created": links_created,
            "links_reinforced": links_reinforced,
            "total_transitions": total_transitions,
            "final_density": round(density, 4),
            "snapshot_sha256": new_g_hash,
        }

        print("\n" + "-" * 72)
        print("[CAUSAL GROUNDING COMPLETE]")
        print(f"  Transitions Grounded: {total_transitions}")
        print(f"  Links Created:        {links_created}")
        print(f"  Links Reinforced:     {links_reinforced}")
        print(f"  Directed Edges:       {initial_edges} -> {final_edges} (+{final_edges - initial_edges})")
        print(f"  Edge/Neuron Ratio:    {density:.4f}")
        print(f"  Snapshot SHA-256:     {new_g_hash}")
        print("-" * 72, flush=True)

        return summary


def evaluate_causal_reasoning_scenarios(run_dir: Path | None = None):
    """Run real-world physical problem solving scenarios through topological wave interference."""
    run_dir = run_dir or Path(latest_run())
    g_path = run_dir / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    engine = ConceptualResonanceEngine(graph)

    print("\n" + "=" * 72)
    print("DEMONSTRATING VIV'S MULTI-CLAUSE PHYSICAL REASONING ENGINE")
    print("=" * 72)

    scenarios = [
        {
            "problem": "Blocked household pipe with stopped water flow",
            "premises": ["pipe", "blockage"],
            "expected_deduction": "pressure / stress / rupture / leak",
        },
        {
            "problem": "Boiler heating water in a confined chamber",
            "premises": ["hot", "steam"],
            "expected_deduction": "pressure / force / piston / move",
        },
        {
            "problem": "Operator clamping a loose structural joint",
            "premises": ["lever", "torque"],
            "expected_deduction": "bolt / joint / stop / movement",
        },
        {
            "problem": "Active pipe leak symptom (Abductive Root Cause Diagnostic)",
            "premises": ["leak", "rupture"],
            "expected_deduction": "stress / pressure / blockage / pipe",
        },
        {
            "problem": "High pressure safety regulation intervention",
            "premises": ["high", "valve"],
            "expected_deduction": "pressure / steam / open / prevents rupture",
        },
    ]

    for sc in scenarios:
        anchors = sc["premises"]
        res = engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_str = ", ".join(f"'{word}' ({score:,.0f})" for word, score in res)
        print(f"\n[SCENARIO] {sc['problem']}")
        print(f"  Given Observable Anchors: {anchors}")
        print(f"  Expected Physical Consequence: {sc['expected_deduction']}")
        print(f"  Topological Wave Resolution:   {top_str}")

    graph.close()


def main():
    parser = argparse.ArgumentParser(description="Viv Causal Chain Engine")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate causal reasoning")
    args = parser.parse_args()

    engine = CausalChainEngine()
    if not args.eval_only:
        engine.compile_causal_chains_to_ontology()
        engine.ground_causal_chains_into_lattice()
    engine.close()

    evaluate_causal_reasoning_scenarios()


if __name__ == "__main__":
    main()
