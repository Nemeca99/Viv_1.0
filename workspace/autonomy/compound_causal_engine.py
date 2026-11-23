"""Compound Causal Engine: Multi-System Physical Interactions for Viv.

Implements Compound Dual-Stage Deductions across intersecting physical domains:
1. Cryogenic Ice-Expansion Pipe Burst (Thermodynamics + Hydraulics + Material Rupture)
2. High-Friction Thermal Seizure (Kinematics + Thermodynamics + Metallurgy)
3. Overpressurized Steam Boiler Explosion (Thermodynamics + Mechanical Jam + Failure)
4. Internal Combustion Work Transduction (Thermodynamics + Mechanical Drive + Power)

Architecture:
  - Connects intersecting physical sub-graphs at causal convergence junctions.
  - Implements asymmetric causal conductance (W_fwd = 650k, W_rev = 150k).
  - Evaluates multi-system deductive cascades and abductive diagnostics with zero matrix multiplications.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

WORKSPACE = Path(r"L:\LocalCoder\workspace")
sys.path.insert(0, str(WORKSPACE))
sys.path.insert(0, r"L:\Standalone\NN")

from autonomy.terminal_neuron_learning import latest_run
from nn_local.steel_brain_store import SQLiteNeuronGraphStore
from autonomy.conceptual_resonance_engine import ConceptualResonanceEngine

AUTONOMY_DATA = WORKSPACE / "autonomy/data"
DB_PATH = AUTONOMY_DATA / "lexicon_ontology.db"

COMPOUND_CHAINS = [
    {
        "domain": "cryogenic_structural_failure",
        "title": "Winter Freeze Pipe Burst & Flood",
        "description": "Sub-freezing temperatures freeze water inside a rigid pipe; anomalous volumetric expansion creates hoop stress exceeding yield strength, bursting the pipe and causing a flood upon thaw.",
        "steps": [
            ("cold", "FREEZES", "water", "Sub-zero temperatures freeze liquid water."),
            ("cold", "PRODUCES", "ice", "Freezing cold directly produces crystalline ice."),
            ("water", "FORMS", "ice", "Freezing water undergoes solid phase transition into crystalline ice."),
            ("ice", "FREEZES_IN", "pipe", "Trapped water freezes into an ice plug inside the pipe."),
            ("ice", "CAUSES", "expansion", "Ice lattice occupies higher specific volume, exerting anomalous expansion."),
            ("expansion", "EXERTS", "stress", "Confined volumetric expansion creates extreme radial stress."),
            ("stress", "ACTS_ON", "pipe", "Expanding ice pushes outward against rigid pipe conduit."),
            ("pipe", "SUFFERS", "crack", "Wall stress exceeding tensile limit fractures pipe material."),
            ("crack", "CAUSES", "burst", "Fracture propagates along stress lines, bursting pipe open."),
            ("burst", "PRODUCES", "leak", "Ruptured seam releases trapped fluid as active leak."),
            ("leak", "CAUSES", "flood", "Uncontrolled escaping fluid inundates surrounding area in a flood."),
        ],
    },
    {
        "domain": "tribology_thermal_seizure",
        "title": "High-Friction Thermal Mechanical Seizure",
        "description": "Mechanical friction between dry metal components generates severe heat; thermal expansion closes mechanical clearances until moving parts jam, causing mechanical seizure.",
        "steps": [
            ("engine", "DRIVES", "metal", "Engine rotates and loads metallic structural components."),
            ("metal", "CREATES", "friction", "Unlubricated contact between metal surfaces creates sliding friction."),
            ("friction", "CAUSES", "wear", "Abrasive friction erodes component material as surface wear."),
            ("friction", "GENERATES", "heat", "Kinetic friction converts mechanical work into intense heat."),
            ("heat", "CAUSES", "expansion", "Thermal excitation causes thermal expansion of metal components."),
            ("expansion", "PRODUCES", "jam", "Expanded dimensions eliminate running clearances, causing mechanical jam."),
            ("jam", "LEADS_TO", "stuck", "Interlocked metal surfaces become rigidly stuck together."),
            ("stuck", "CAUSES", "seizure", "Full mechanical seizure arrests all rotational machinery."),
            ("seizure", "CAUSES", "stop", "Catastrophic seizure stops all mechanical movement."),
        ],
    },
    {
        "domain": "thermodynamic_overpressure_catastrophe",
        "title": "Overpressurized Steam Boiler Explosion",
        "description": "Continuous thermal input boils water into high-pressure steam; failure of a stuck closed relief valve prevents exhaust, causing vessel overstress, shattering rupture, and catastrophic explosion.",
        "steps": [
            ("hot", "HEATS", "water", "Intense thermal flux heats liquid water."),
            ("water", "GENERATES", "steam", "Boiling water converts into high-energy gaseous steam."),
            ("steam", "BUILDS", "pressure", "Confined steam gas accumulates extreme hydrostatic pressure."),
            ("valve", "BECOMES", "stuck", "Mineral deposition or corrosion causes safety valve to become stuck."),
            ("stuck", "KEEPS", "close", "Jammed mechanism keeps valve seat held close."),
            ("close", "PREVENTS", "steam", "Closed valve blocks steam from escaping."),
            ("pressure", "EXCALATES", "stress", "Unrelieved steam pressure escalates wall stress."),
            ("stress", "CAUSES", "shatter", "Extreme hoop stress shatters brittle pressure vessel walls."),
            ("shatter", "PRODUCES", "burst", "Vessel integrity fails completely in a violent burst."),
            ("burst", "RESULTS_IN", "fail", "Explosive energy release causes catastrophic structural fail."),
        ],
    },
    {
        "domain": "combustion_mechanical_transduction",
        "title": "Internal Combustion Work Transduction",
        "description": "Thermal gas expansion drives a mechanical piston, translating linear pressure force into rotational torque and engine power.",
        "steps": [
            ("hot", "CAUSES", "expansion", "Rapid thermal release causes sudden gas expansion."),
            ("expansion", "BUILDS", "pressure", "Expanding gases create high localized pressure."),
            ("pressure", "PUSHES", "piston", "Gas pressure exerts heavy downward thrust on piston face."),
            ("piston", "TRANSMITS", "force", "Displaced piston transmits linear mechanical force."),
            ("force", "CREATES", "torque", "Connecting rod converts linear force to rotational torque."),
            ("torque", "DRIVES", "engine", "Crankshaft torque drives rotating engine machinery."),
            ("engine", "DELIVERS", "power", "Rotational mechanical energy delivers usable shaft power."),
        ],
    },
]


class CompoundCausalEngine:
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

    def compile_compound_chains_to_ontology(self) -> int:
        """Store compound causal chains in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        for ch in COMPOUND_CHAINS:
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

    def ground_compound_chains(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground compound physical conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        print("=" * 72)
        print("NOX FORGE · COMPOUND CAUSAL ENGINE")
        print(f"Target Snapshot: {self.run_dir.name}")
        print(f"Compiling {len(COMPOUND_CHAINS)} Compound Multi-System Conduits...")
        print("=" * 72, flush=True)

        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM links")
        initial_edges = cur.fetchone()[0]

        links_created = 0
        links_reinforced = 0
        total_transitions = 0

        for ch in COMPOUND_CHAINS:
            print(f"\n[COMPOUND CONDUIT] {ch['title']} ({ch['domain']})")
            for src_word, rel, dst_word, rationale in ch["steps"]:
                src_id = word_idx.get(src_word)
                dst_id = word_idx.get(dst_word)

                if src_id and dst_id:
                    # Forward Causal Arrow of Time
                    is_new_fwd = self.upsert_causal_link(src_id, dst_id, forward_weight)
                    if is_new_fwd:
                        links_created += 1
                    else:
                        links_reinforced += 1

                    # Reciprocal Asymmetric Feedback
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
        print("[COMPOUND CAUSAL GROUNDING COMPLETE]")
        print(f"  Transitions Grounded: {total_transitions}")
        print(f"  Links Created:        {links_created}")
        print(f"  Links Reinforced:     {links_reinforced}")
        print(f"  Directed Edges:       {initial_edges} -> {final_edges} (+{final_edges - initial_edges})")
        print(f"  Edge/Neuron Ratio:    {density:.4f}")
        print(f"  Snapshot SHA-256:     {new_g_hash}")
        print("-" * 72, flush=True)

        return summary


def evaluate_compound_scenarios(run_dir: Path | None = None):
    """Run real-world compound physical problems through multi-anchor wave interference."""
    run_dir = run_dir or Path(latest_run())
    g_path = run_dir / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    engine = ConceptualResonanceEngine(graph)

    print("\n" + "=" * 72)
    print("VIV COMPOUND MULTI-SYSTEM PHYSICAL REASONING EVALUATION")
    print("=" * 72)

    scenarios = [
        {
            "problem": "Winter pipe freeze: Sub-zero cold meets uninsulated household pipe",
            "premises": ["cold", "pipe"],
            "expected_deduction": "ice / expansion / burst / leak / flood",
        },
        {
            "problem": "Dry unlubricated machinery: High friction between metal parts under load",
            "premises": ["friction", "metal"],
            "expected_deduction": "heat / expansion / jam / stuck / seizure / stop",
        },
        {
            "problem": "Catastrophic boiler overpressure: High steam builds with jammed valve",
            "premises": ["steam", "stuck"],
            "expected_deduction": "pressure / close / stress / shatter / burst / fail",
        },
        {
            "problem": "Engine work cycle: Hot expanding gas acting on moving piston",
            "premises": ["hot", "piston"],
            "expected_deduction": "expansion / pressure / force / torque / engine / power",
        },
        {
            "problem": "Diagnostic Root Cause: Unexplained basement flood from cracked pipe",
            "premises": ["flood", "pipe"],
            "expected_deduction": "leak / burst / crack / stress / ice / cold",
        },
    ]

    for sc in scenarios:
        anchors = sc["premises"]
        res = engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_str = ", ".join(f"'{word}' ({score:,.0f})" for word, score in res)
        print(f"\n[COMPOUND SCENARIO] {sc['problem']}")
        print(f"  Observable Premise Poles:     {anchors}")
        print(f"  Expected Physical Consequence: {sc['expected_deduction']}")
        print(f"  Topological Wave Resolution:   {top_str}")

    graph.close()


def main():
    parser = argparse.ArgumentParser(description="Viv Compound Causal Engine")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate scenarios")
    args = parser.parse_args()

    engine = CompoundCausalEngine()
    if not args.eval_only:
        engine.compile_compound_chains_to_ontology()
        engine.ground_compound_chains()
    engine.close()

    evaluate_compound_scenarios()


if __name__ == "__main__":
    main()
