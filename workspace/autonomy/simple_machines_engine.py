"""Simple Machines & Mechanical Advantage Engine for Viv.

Implements the Classical Mechanics Foundation of Simple Machines:
1. Lever & Fulcrum (Law of the Lever: F1 * d1 = F2 * d2)
2. Wheel & Axle (Continuous Leverage & Rolling Friction Reduction)
3. Pulley System (Cable Tension & Load Hoisting)
4. Inclined Plane / Ramp (Trading Slope Distance for Lifting Force)
5. Wedge (Double Incline Lateral Splitting & Cleaving)
6. Screw & Helical Thread (Torque to Linear Axial Clamping)
7. Mechanical Work & Conservation of Energy (Work = Force * Distance)

Grounds Viv's physical world model in foundational engineering first principles.
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

SIMPLE_MACHINE_CHAINS = [
    {
        "domain": "mechanics_leverage",
        "title": "Leverage, Fulcrum Pivot & Mechanical Advantage",
        "description": "A rigid beam pivoting on a fulcrum amplifies input effort into multiplied output force to lift heavy loads, trading distance for mechanical advantage.",
        "steps": [
            ("lever", "PIVOTS_ON", "fulcrum", "Rigid beam pivots freely across stationary support point."),
            ("fulcrum", "SUPPORTS", "lever", "Stationary pivot sustains load and reaction forces."),
            ("effort", "APPLIED_TO", "lever", "Input mechanical force is exerted on the effort arm."),
            ("lever", "TRANSMITS", "torque", "Moment arm converts applied effort into rotational torque."),
            ("lever", "MULTIPLIES", "force", "Long effort arm multiplies effective force at the load arm."),
            ("force", "LIFTS", "load", "Multiplied output force elevates heavy gravitational load."),
            ("lever", "REDUCES", "effort", "Mechanical advantage minimizes human or motor effort required."),
            ("lever", "IS_A", "tool", "A lever is a fundamental force-multiplying physical tool."),
        ],
    },
    {
        "domain": "mechanics_wheel_axle",
        "title": "Wheel & Axle Mechanical Transduction",
        "description": "A circular wheel affixed to a central axle acts as continuous leverage, converting rotational torque into linear motion and dramatically reducing rolling friction.",
        "steps": [
            ("wheel", "ROTATES_ON", "axle", "Circular outer perimeter rotates around a concentric central axle shaft."),
            ("torque", "TURNS", "wheel", "Rotational drive torque turns the wheel-axle assembly."),
            ("wheel", "TRANSMITS", "torque", "Differential radius between wheel and axle multiplies drive torque."),
            ("wheel", "REDUCES", "friction", "Rolling point contact replaces sliding drag with minimal rolling friction."),
            ("wheel", "MOVES", "load", "Wheel rotation translates heavy cargo across terrain."),
            ("axle", "SUPPORTS", "load", "Rigid central axle bears structural vehicle weight."),
            ("wheel", "MULTIPLIES", "force", "Radius ratio provides continuous rotational mechanical advantage."),
            ("wheel", "IS_A", "machine", "A wheel and axle is a classical continuous simple machine."),
        ],
    },
    {
        "domain": "mechanics_pulley_hoist",
        "title": "Pulley System Cable Tension & Hoist",
        "description": "Grooved wheels redirect line tension along a flexible rope or cable, reversing lifting direction and dividing load weight across supporting lines.",
        "steps": [
            ("pulley", "GUIDES", "rope", "Grooved wheel guides flexible rope without slipping."),
            ("rope", "TRANSMITS", "tension", "Tensile stress propagates continuously along line length."),
            ("cable", "IS_A", "rope", "High-tensile steel cable acts as heavy-duty load line."),
            ("pulley", "CHANGES", "direction", "Fixed pulley reverses applied force direction for pulling."),
            ("tension", "LIFTS", "load", "Upward tensile vectors counteract downward gravity load."),
            ("pulley", "HOISTS", "load", "Movable block and tackle hoists suspended equipment."),
            ("pulley", "REDUCES", "effort", "Multiple rope segments divide total suspended load weight."),
            ("pulley", "IS_A", "machine", "A pulley is a classical tension-redirecting simple machine."),
        ],
    },
    {
        "domain": "mechanics_inclined_plane",
        "title": "Inclined Plane Slope & Force Reduction",
        "description": "A stationary sloped ramp trades increased travel distance against gravitational load, greatly reducing the required mechanical effort to lift an object.",
        "steps": [
            ("ramp", "IS_A", "plane", "A ramp provides a planar incline at an angle above the horizontal."),
            ("plane", "HAS_PROPERTY", "slope", "Inclined geometry creates an elevated gradient."),
            ("ramp", "INCREASES", "distance", "Traversing the slope extends travel distance over vertical rise."),
            ("ramp", "REDUCES", "force", "Support reaction bears normal weight, reducing required pull force."),
            ("ramp", "REDUCES", "effort", "Shallower slope gradient directly minimizes lifting effort."),
            ("ramp", "EASES", "lift", "Sliding or rolling along incline enables effortless vertical elevation."),
            ("distance", "TRADES", "force", "Golden rule of mechanics: mechanical advantage trades distance for force."),
            ("work", "CONSERVES", "energy", "Mechanical work (force * distance) remains conserved across lossless systems."),
        ],
    },
    {
        "domain": "mechanics_wedge_cleaving",
        "title": "Wedge Cleaving & Lateral Force Splitting",
        "description": "A movable dual inclined plane (wedge or axe blade) converts forward driving impact into high lateral splitting forces to divide materials.",
        "steps": [
            ("force", "DRIVES", "wedge", "Downward impact or hydraulic pressure drives wedge tip into material."),
            ("wedge", "HAS_PART", "blade", "Sharpened leading apex concentrates contact stress."),
            ("axe", "IS_A", "wedge", "An axe is a handheld impact wedge for woodcutting."),
            ("wedge", "SPLITS", "wood", "Lateral thrust overcomes tensile grain cohesion to split timber."),
            ("blade", "CUTS", "metal", "High contact stress shears metal or crystalline bonds."),
            ("wedge", "CONVERTS", "force", "Inclined faces convert longitudinal force into lateral expansion."),
            ("wedge", "CAUSES", "split", "Material cleaves along path of maximum shear strain."),
            ("wedge", "IS_A", "tool", "A wedge is a classical portable inclined plane tool."),
        ],
    },
    {
        "domain": "mechanics_screw_clamping",
        "title": "Screw Helical Thread & Joint Clamping",
        "description": "A helical inclined plane wrapped around a cylinder converts rotational torque into massive linear compression to fasten structural joints.",
        "steps": [
            ("torque", "TURNS", "screw", "Rotational torque is applied to screw head or drive slot."),
            ("screw", "HAS_PART", "thread", "Continuous helical inclined ridge winds along cylindrical shank."),
            ("thread", "HAS_PROPERTY", "pitch", "Axial distance between adjacent thread crests determines mechanical lead."),
            ("screw", "CONVERTS", "torque", "Helical geometry converts rotational motion into linear thrust."),
            ("thread", "GENERATES", "clamp", "Axial bolt preload generates massive compressive clamping force."),
            ("screw", "FASTENS", "joint", "High compression locks structural joint members rigidly in place."),
            ("clamp", "SECURES", "joint", "Frictional interface prevents joint loosening and shear separation."),
            ("screw", "IS_A", "fastener", "A threaded screw is a self-locking helical fastener."),
        ],
    },
]


class SimpleMachinesEngine:
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

    def compile_chains_to_ontology(self) -> int:
        """Store simple machine causal chains and semantic relations in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        # 1. Upsert causal implication chains
        for ch in SIMPLE_MACHINE_CHAINS:
            cur.execute("SELECT chain_id FROM causal_implication_chains WHERE title = ?", (ch["title"],))
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

        # 2. Upsert semantic relations for all individual steps
        for ch in SIMPLE_MACHINE_CHAINS:
            for src_w, rel, dst_w, desc in ch["steps"]:
                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (src_w,))
                src_row = cur.fetchone()
                if not src_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'mechanics', 1, ?)", (src_w, now_utc))
                    src_id = cur.lastrowid
                else:
                    src_id = src_row[0]

                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (dst_w,))
                dst_row = cur.fetchone()
                if not dst_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'mechanics', 1, ?)", (dst_w, now_utc))
                    dst_id = cur.lastrowid
                else:
                    dst_id = dst_row[0]

                cur.execute("""
                    SELECT relation_id FROM semantic_relations
                    WHERE source_entity_id = ? AND relation_type = ? AND target_entity_id = ?
                """, (src_id, rel, dst_id))
                rel_row = cur.fetchone()
                if not rel_row:
                    cur.execute("""
                        INSERT INTO semantic_relations (source_entity_id, relation_type, target_entity_id, confidence, evidence_text, created_utc)
                        VALUES (?, ?, ?, 1.0, 'FIRST_PRINCIPLES_SIMPLE_MACHINES_V1', ?)
                    """, (src_id, rel, dst_id, now_utc))

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

    def ground_machine_conduits(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground simple machine conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        injected_new = 0
        reinforced = 0
        missing = set()

        for chain in SIMPLE_MACHINE_CHAINS:
            for src_w, rel, dst_w, desc in chain["steps"]:
                src_n = word_idx.get(src_w)
                dst_n = word_idx.get(dst_w)

                if not src_n:
                    missing.add(src_w)
                if not dst_n:
                    missing.add(dst_w)

                if src_n and dst_n:
                    # Forward causal transmission
                    if self.upsert_causal_link(src_n, dst_n, forward_weight):
                        injected_new += 1
                    else:
                        reinforced += 1

                    # Asymmetric feedback link (abductive inference)
                    if self.upsert_causal_link(dst_n, src_n, feedback_weight):
                        injected_new += 1
                    else:
                        reinforced += 1

        self.conn.commit()

        total_neurons = self.conn.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
        total_links = self.conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        density = total_links / total_neurons if total_neurons else 0

        # Update SHA-256 hash in learning.json
        new_g_hash = hashlib.sha256(self.g_path.read_bytes()).hexdigest()
        l_path = self.run_dir / "learning.json"
        if l_path.exists():
            l_data = json.loads(l_path.read_text(encoding="utf-8"))
            if "snapshot_hashes" in l_data:
                l_data["snapshot_hashes"]["neuron_graph.sqlite3"] = new_g_hash
                l_path.write_text(json.dumps(l_data, indent=2), encoding="utf-8")

        return {
            "new_links": injected_new,
            "reinforced_links": reinforced,
            "missing_tokens": list(missing),
            "total_neurons": total_neurons,
            "total_links": total_links,
            "edge_neuron_ratio": round(density, 4),
            "manifest_hash": new_g_hash,
        }


def run_simple_machines_verification():
    engine = SimpleMachinesEngine()
    print("1. Compiling Simple Machine chains to ontology database...")
    c_count = engine.compile_chains_to_ontology()
    print(f"   Compiled/Updated {len(SIMPLE_MACHINE_CHAINS)} chains into lexicon_ontology.db.")

    print("\n2. Grounding Simple Machine conduits into neural graph...")
    stats = engine.ground_machine_conduits()
    print(f"   Injected New Links: {stats['new_links']}")
    print(f"   Reinforced Links:   {stats['reinforced_links']}")
    print(f"   Total Neurons:      {stats['total_neurons']}")
    print(f"   Total Links:        {stats['total_links']}")
    print(f"   Edge/Neuron Ratio:  {stats['edge_neuron_ratio']}")
    print(f"   Manifest Hash:      {stats['manifest_hash'][:16]}...")
    engine.close()

    print("\n3. Testing Wave Interference & Emergent Reasoning across Simple Machines...")
    g_path = Path(latest_run()) / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    res_engine = ConceptualResonanceEngine(graph)

    test_scenarios = [
        ("Lever Mechanical Advantage", ["lever", "fulcrum"]),
        ("Wheel & Axle Motion", ["wheel", "axle"]),
        ("Pulley Hoist Tension", ["pulley", "rope"]),
        ("Inclined Plane Force Reduction", ["ramp", "slope"]),
        ("Wedge Wood Cleaving", ["wedge", "force"]),
        ("Screw Helical Clamping", ["screw", "thread"]),
        ("Abductive Hoist Diagnostic", ["lift", "load"]),
        ("Abductive Clamping Diagnostic", ["clamp", "joint"]),
    ]

    for title, anchors in test_scenarios:
        attractors = res_engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_words = [f"{w} ({int(s):,})" for w, s in attractors]
        print(f"   Scenario [{title}]: anchors={anchors}")
        print(f"      Echoes -> {', '.join(top_words)}")

    graph.close()


if __name__ == "__main__":
    run_simple_machines_verification()
