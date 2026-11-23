"""Newtonian Dynamics & Gravitational Kinematics Engine for Viv.

Implements the Classical Mechanics Foundation of Newton's Laws and Gravity:
1. Newton's First Law: Inertia & Momentum (Mass resists acceleration; moving mass holds momentum).
2. Newton's Second Law: Force = Mass * Acceleration (F = ma; force accelerates mass, increasing velocity).
3. Newton's Third Law: Action & Reaction (Equal and opposite reaction forces, thrust, recoil, impact).
4. Gravitational Attraction & Free Fall (Planetary gravity pulls mass, converting potential energy to kinetic impact).

Grounds Viv's physical world model in foundational dynamic first principles.
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

NEWTONIAN_CHAINS = [
    {
        "domain": "physics_inertia_momentum",
        "title": "Inertial Momentum & Resistance to Acceleration",
        "description": "Mass possesses intrinsic inertia resisting changes in motion; moving mass carries momentum that requires opposing force to decelerate or halt.",
        "steps": [
            ("mass", "POSSESSES", "inertia", "Inherent property of matter resisting changes in its velocity state."),
            ("inertia", "RESISTS", "acceleration", "Inertial mass resists acceleration when subjected to external force."),
            ("mass", "CARRIES", "momentum", "Product of mass and velocity constitutes linear momentum."),
            ("momentum", "REQUIRES", "force", "Altering momentum requires continuous application of unbalanced net force."),
            ("force", "CHANGES", "speed", "Applied impulse accelerates or decelerates the moving body."),
            ("force", "HALTS", "momentum", "Opposing counter-force dissipates momentum to bring body to rest."),
            ("friction", "DECELERATES", "mass", "Contact drag friction exerts opposing force that slows down mass."),
            ("inertia", "IS_A", "property", "Inertia is an intrinsic physical property of all matter."),
        ],
    },
    {
        "domain": "physics_force_acceleration",
        "title": "Newtonian Force Acceleration Dynamics",
        "description": "Unbalanced force acting on mass generates proportional acceleration (F = ma); greater mass requires greater force to achieve equivalent velocity change.",
        "steps": [
            ("force", "ACTS_ON", "mass", "Mechanical or gravitational force vector acts on physical mass."),
            ("force", "CAUSES", "acceleration", "Unbalanced net force induces acceleration in direction of force vector."),
            ("acceleration", "INCREASES", "speed", "Positive acceleration continuously increases velocity magnitude."),
            ("acceleration", "CHANGES", "velocity", "Acceleration alters both speed and directional trajectory of travel."),
            ("mass", "OPPOSES", "force", "Larger mass diminishes acceleration achieved from a fixed input force."),
            ("force", "TRANSFERS", "energy", "Work done by force across distance transfers mechanical energy into the body."),
            ("speed", "GENERATES", "kinetic", "Motion manifests as kinetic energy proportional to mass times velocity squared."),
            ("kinetic", "IS_A", "energy", "Kinetic energy represents active mechanical energy of moving mass."),
        ],
    },
    {
        "domain": "physics_action_reaction",
        "title": "Action Reaction Dynamics & Thrust Recoil",
        "description": "Every applied force induces an instantaneous equal and opposite reaction force; expelled exhaust mass generates forward thrust while the emitter experiences recoil.",
        "steps": [
            ("force", "PRODUCES", "reaction", "Newton's third law dictates mutual interaction between interacting bodies."),
            ("thrust", "EXPELS", "mass", "Reaction engine expels propellant mass at high exhaust velocity."),
            ("thrust", "PROPELS", "load", "Forward reaction force accelerates vehicle payload forward."),
            ("thrust", "CAUSES", "recoil", "Conservation of momentum imposes equal backward recoil force on emitter."),
            ("impact", "CREATES", "collision", "Sudden mechanical contact between bodies initiates high-energy collision."),
            ("collision", "CAUSES", "recoil", "Elastic or inelastic shock waves force impacting bodies to rebound."),
            ("ground", "EXERTS", "reaction", "Rigid surface exerts upward normal reaction force matching applied weight."),
            ("reaction", "BALANCES", "weight", "Static equilibrium achieved when upward normal reaction equals gravity."),
        ],
    },
    {
        "domain": "physics_gravity_freefall",
        "title": "Gravitational Attraction & Kinetic Free Fall",
        "description": "Planetary mass exerts downward gravitational attraction, causing free-falling bodies to accelerate toward ground and converting potential energy into kinetic impact.",
        "steps": [
            ("earth", "EXERTS", "gravity", "Planetary mass generates downward gravitational field."),
            ("gravity", "ATTRACTS", "mass", "Universal gravitation pulls all physical mass toward center of gravity."),
            ("gravity", "CREATES", "weight", "Gravitational acceleration acting on mass produces downward weight force."),
            ("gravity", "CAUSES", "fall", "Unsupported body in gravitational field enters free fall acceleration."),
            ("drop", "IS_A", "fall", "Releasing an object drops it into gravitational free fall."),
            ("fall", "ACCELERATES", "mass", "Downward gravitational acceleration continuously increases falling speed."),
            ("fall", "CONVERTS", "potential", "Loss of elevation converts gravitational potential energy into kinetic motion."),
            ("potential", "BECOMES", "kinetic", "Total mechanical energy is conserved as potential energy becomes kinetic."),
            ("fall", "TERMINATES_IN", "impact", "Free fall trajectory terminates abruptly upon striking rigid ground."),
            ("impact", "STRIKES", "ground", "Kinetic energy discharges against ground boundary surface."),
            ("impact", "CAUSES", "bounce", "Elastic rebound converts shock kinetic energy into upward bounce motion."),
        ],
    },
]


class NewtonianDynamicsEngine:
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
        """Store Newtonian causal chains and semantic relations in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        # 1. Upsert causal implication chains
        for ch in NEWTONIAN_CHAINS:
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
        for ch in NEWTONIAN_CHAINS:
            for src_w, rel, dst_w, desc in ch["steps"]:
                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (src_w,))
                src_row = cur.fetchone()
                if not src_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'physics', 1, ?)", (src_w, now_utc))
                    src_id = cur.lastrowid
                else:
                    src_id = src_row[0]

                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (dst_w,))
                dst_row = cur.fetchone()
                if not dst_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'physics', 1, ?)", (dst_w, now_utc))
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
                        VALUES (?, ?, ?, 1.0, 'FIRST_PRINCIPLES_NEWTONIAN_V1', ?)
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

    def ground_newtonian_conduits(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground Newtonian mechanics conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        injected_new = 0
        reinforced = 0
        missing = set()

        for chain in NEWTONIAN_CHAINS:
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


def run_newtonian_verification():
    engine = NewtonianDynamicsEngine()
    print("1. Compiling Newtonian chains to ontology database...")
    c_count = engine.compile_chains_to_ontology()
    print(f"   Compiled/Updated {len(NEWTONIAN_CHAINS)} chains into lexicon_ontology.db.")

    print("\n2. Grounding Newtonian conduits into neural graph...")
    stats = engine.ground_newtonian_conduits()
    print(f"   Injected New Links: {stats['new_links']}")
    print(f"   Reinforced Links:   {stats['reinforced_links']}")
    print(f"   Total Neurons:      {stats['total_neurons']}")
    print(f"   Total Links:        {stats['total_links']}")
    print(f"   Edge/Neuron Ratio:  {stats['edge_neuron_ratio']}")
    print(f"   Manifest Hash:      {stats['manifest_hash'][:16]}...")
    engine.close()

    print("\n3. Testing Wave Interference across Newtonian Dynamics...")
    g_path = Path(latest_run()) / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    res_engine = ConceptualResonanceEngine(graph)

    test_scenarios = [
        ("Newton's 1st Law (Inertia)", ["mass", "inertia"]),
        ("Newton's 2nd Law (F = ma)", ["force", "mass"]),
        ("Newton's 3rd Law (Thrust/Recoil)", ["thrust", "recoil"]),
        ("Gravitational Fall", ["gravity", "fall"]),
        ("Kinetic Impact Rebound", ["impact", "ground"]),
        ("Abductive Gravity Diagnosis", ["weight", "drop"]),
    ]

    for title, anchors in test_scenarios:
        attractors = res_engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_words = [f"{w} ({int(s):,})" for w, s in attractors]
        print(f"   Scenario [{title}]: anchors={anchors}")
        print(f"      Echoes -> {', '.join(top_words)}")

    graph.close()


if __name__ == "__main__":
    run_newtonian_verification()
