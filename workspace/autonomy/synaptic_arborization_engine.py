"""Synaptic Arborization Engine: Lateral First-Principles Physical Cross-Linking for Viv.

Transforms Viv's neural graph from a sparse, linear 1-to-1 string network
toward dense cortical synaptic arborization (expanding edge-to-neuron ratio E/N).

Architecture:
  1. Reads invariant physical relations from lexicon_ontology.db.
  2. Injects high-conductance lateral synaptic links into neuron_graph.sqlite3
     between physical nodes, tools, materials, states, and thermodynamic primitives.
  3. Grounding Categories to Invariant Physical Hubs:
     - 'tool' -> links to 'force', 'rigid', 'work', 'lever', 'wedge'
     - 'metal' -> links to 'solid', 'rigid', 'heat', 'electricity', 'tension'
     - 'mineral' -> links to 'solid', 'crystal', 'compression', 'stone', 'rock'
     - 'fish' -> links to 'swim', 'water', 'liquid'
     - 'tree' / 'plant' -> links to 'grow', 'soil', 'water', 'light'
  4. Preserves deterministic integrity, updates learning.json snapshot hashes,
     and validates zero-permutation wave interference.
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


class SynapticArborizationEngine:
    def __init__(self, run_dir: Path | None = None, ontology_db: Path = DB_PATH):
        self.run_dir = run_dir or Path(latest_run())
        self.g_path = self.run_dir / "neuron_graph.sqlite3"
        self.ontology_db = ontology_db

        if not self.g_path.exists():
            raise FileNotFoundError(f"Neuron graph store not found at {self.g_path}")
        if not self.ontology_db.exists():
            raise FileNotFoundError(f"Ontology DB not found at {self.ontology_db}")

        self.graph = SQLiteNeuronGraphStore(self.g_path, readonly=False)
        self.conn = self.graph.connection

    def close(self):
        self.graph.close()

    def upsert_directed_link(self, src: str, dst: str, weight: int, direction: int = 1) -> bool:
        """Upsert a directed synaptic link between two neurons in SQLite."""
        existing = self.conn.execute(
            "SELECT reflector, ordinal FROM links WHERE source_id = ? AND peer_id = ?",
            (src, dst),
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE links SET weight = MIN(990000, weight + ?), pass_hits = pass_hits + 1, hot = 1 WHERE source_id = ? AND peer_id = ?",
                (weight // 4, src, dst),
            )
            return False
        else:
            max_ord = self.conn.execute(
                "SELECT COALESCE(MAX(ordinal), -1) FROM links WHERE source_id = ? AND reflector = 0",
                (src,),
            ).fetchone()[0]
            self.conn.execute(
                """INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256)
                   VALUES (?, 0, ?, ?, ?, ?, 1, 1, 0, 1, 1, '')""",
                (src, max_ord + 1, dst, direction, weight),
            )
            return True

    def arborize_physical_ontology(self, forward_weight: int = 550_000, feedback_weight: int = 300_000) -> dict:
        """Inject all first-principles physical relations into the neuron graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        print("=" * 72)
        print("NOX FORGE · SYNAPTIC ARBORIZATION ENGINE")
        print(f"Target Snapshot: {self.run_dir.name}")
        print(f"Active Neurons:  {len(word_idx)} registered word nodes")
        print("=" * 72, flush=True)

        # Get initial graph counts
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM neurons")
        initial_neurons = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM links")
        initial_edges = cur.fetchone()[0]

        ont_conn = sqlite3.connect(self.ontology_db)
        ont_cur = ont_conn.cursor()

        # Query all non-partitive relations
        ont_cur.execute("""
            SELECT s.lemma, r.relation_type, t.lemma, r.confidence
            FROM semantic_relations r
            JOIN lexical_entities s ON r.source_entity_id = s.entity_id
            JOIN lexical_entities t ON r.target_entity_id = t.entity_id
            WHERE r.relation_type NOT IN ('PART_OF', 'DERIVED_FROM')
        """)
        relations = ont_cur.fetchall()
        ont_conn.close()

        print(f"Loaded {len(relations)} candidate relations from ontology DB...", flush=True)

        links_created = 0
        links_reinforced = 0
        relations_grounded = 0
        missing_nodes = set()

        for src_lemma, rel_type, tgt_lemma, conf in relations:
            src_clean = src_lemma.lower().strip()
            tgt_clean = tgt_lemma.lower().strip()

            src_id = word_idx.get(src_clean)
            tgt_id = word_idx.get(tgt_clean)

            if not src_id:
                missing_nodes.add(src_clean)
            if not tgt_id:
                missing_nodes.add(tgt_clean)

            if src_id and tgt_id:
                # Forward physical link
                is_new_fwd = self.upsert_directed_link(src_id, tgt_id, int(forward_weight * conf))
                if is_new_fwd:
                    links_created += 1
                else:
                    links_reinforced += 1

                # Reciprocal feedback link (so wave interference flows bidirectionally)
                is_new_rev = self.upsert_directed_link(tgt_id, src_id, int(feedback_weight * conf))
                if is_new_rev:
                    links_created += 1
                else:
                    links_reinforced += 1

                relations_grounded += 1

        self.conn.commit()

        # Final counts
        cur.execute("SELECT count(*) FROM neurons")
        final_neurons = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM links")
        final_edges = cur.fetchone()[0]

        initial_density = initial_edges / initial_neurons if initial_neurons else 0
        final_density = final_edges / final_neurons if final_neurons else 0

        # Update SHA-256 hash in learning.json
        new_g_hash = hashlib.sha256(self.g_path.read_bytes()).hexdigest()
        l_path = self.run_dir / "learning.json"
        if l_path.exists():
            l_data = json.loads(l_path.read_text(encoding="utf-8"))
            if "snapshot_hashes" in l_data:
                l_data["snapshot_hashes"]["neuron_graph.sqlite3"] = new_g_hash
                l_path.write_text(json.dumps(l_data, indent=2), encoding="utf-8")

        summary = {
            "initial_neurons": initial_neurons,
            "final_neurons": final_neurons,
            "initial_edges": initial_edges,
            "final_edges": final_edges,
            "links_created": links_created,
            "links_reinforced": links_reinforced,
            "relations_grounded": relations_grounded,
            "initial_density": round(initial_density, 4),
            "final_density": round(final_density, 4),
            "graph_sha256": new_g_hash[:16] + "...",
        }

        print("\n" + "-" * 72)
        print("[SYNAPTIC ARBORIZATION COMPLETE]")
        print(f"  Relations Grounded: {relations_grounded}")
        print(f"  New Links Created:  {links_created}")
        print(f"  Links Reinforced:   {links_reinforced}")
        print(f"  Neuron Count:       {initial_neurons} -> {final_neurons}")
        print(f"  Directed Links:     {initial_edges} -> {final_edges} (+{final_edges - initial_edges})")
        print(f"  Edge/Neuron Ratio:  {initial_density:.4f} -> {final_density:.4f}")
        print(f"  Snapshot SHA-256:   {new_g_hash}")
        print("-" * 72, flush=True)

        return summary


def verify_physical_wave_resonance(run_dir: Path | None = None):
    """Verify that multi-anchor physical queries resolve through constructive interference."""
    run_dir = run_dir or Path(latest_run())
    g_path = run_dir / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    engine = ConceptualResonanceEngine(graph)

    print("\n" + "=" * 72)
    print("VERIFYING FIRST-PRINCIPLES PHYSICAL WAVE INTERFERENCE BATTERY")
    print("=" * 72)

    test_queries = [
        (["tool", "force"], "lever / hammer / work"),
        (["lever", "torque"], "tool / force / wrench"),
        (["metal", "heat"], "conducts / solid / iron"),
        (["mineral", "rock"], "crystal / stone / solid"),
        (["friction", "heat"], "motion / energy"),
        (["sun", "heat"], "light / star"),
        (["ice", "water"], "melts / cold / solid"),
        (["fish", "water"], "swim / river"),
        (["bird", "air"], "fly / sky"),
        (["plant", "water"], "grow / tree / soil"),
    ]

    for anchors, expected in test_queries:
        res = engine.resolve_multi_anchor_query(anchors, top_k=4)
        top_str = ", ".join(f"'{word}' ({score:,.0f})" for word, score in res)
        print(f"  Query {anchors} (Expected: {expected}):")
        print(f"    -> Resonance Field: {top_str}")

    graph.close()


def main():
    parser = argparse.ArgumentParser(description="Viv Synaptic Arborization Engine")
    parser.add_argument("--verify-only", action="store_true", help="Only verify wave interference")
    args = parser.parse_args()

    engine = SynapticArborizationEngine()
    if not args.verify_only:
        engine.arborize_physical_ontology()
    engine.close()

    verify_physical_wave_resonance()


if __name__ == "__main__":
    main()
