"""Spatial Geometry & Dimensional Scaling Engine for Viv.

Implements the Foundations of Geometry, Topology, and Dimensional Scaling:
1. Dimensional Progression: 0D (Point) -> 1D (Line) -> 2D (Area/Surface) -> 3D (Cube/Sphere).
2. Planar Polygon Constraints: Triangles (immutable angles, truss rigidity) and Squares.
3. Radial Curvature & Circles: Radius, diameter, circular circumference, spherical rotation.
4. The Square-Cube Law: Surface area expands quadratically (r^2) while volume expands cubically (r^3).

Grounds Viv's physical world model in foundational spatial mathematics.
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

GEOMETRY_CHAINS = [
    {
        "domain": "geometry_dimensional_topology",
        "title": "Dimensional Progression & Spatial Topology",
        "description": "Points define zero-dimensional positions; moving points generate one-dimensional lines; intersecting lines sweep two-dimensional area surfaces; enclosing surfaces bounds three-dimensional volume.",
        "steps": [
            ("point", "EXTENDS_INTO", "line", "Continuous translation of a zero-dimensional point traces a one-dimensional line."),
            ("line", "ENCLOSES", "area", "Closed perimeter of interconnected lines bounds a two-dimensional planar area."),
            ("line", "FORMS", "angle", "Intersecting lines define an angular aperture between their direction vectors."),
            ("surface", "BOUNDS", "cube", "Six orthogonal planar surfaces enclose the three-dimensional volume of a cube."),
            ("surface", "ENCLOSES", "sphere", "Continuous isotropic curved surface bounds the three-dimensional volume of a sphere."),
            ("boundary", "CONFINES", "shape", "Spatial perimeter sets the exterior limits defining geometric shape."),
            ("perimeter", "SURROUNDS", "area", "One-dimensional linear perimeter traces the closed outer boundary of planar area."),
            ("point", "IS_A", "shape", "A point is the fundamental zero-dimensional geometric primitive."),
        ],
    },
    {
        "domain": "geometry_polygons_truss",
        "title": "Planar Polygon & Truss Rigidity",
        "description": "Three intersecting lines form a rigid triangle with immutable angles; four equal perpendicular sides form a square; triangles resist deformation, providing structural rigidity.",
        "steps": [
            ("line", "FORMS", "triangle", "Three intersecting linear segments enclose a planar three-sided polygon."),
            ("triangle", "HAS_PART", "angle", "Interior angles of a planar triangle strictly sum to one hundred eighty degrees."),
            ("triangle", "HAS_PROPERTY", "rigid", "Triangular geometry cannot deform without changing edge lengths, providing truss rigidity."),
            ("triangle", "IS_A", "shape", "A triangle is a fundamental three-sided planar polygon."),
            ("line", "FORMS", "square", "Four equal orthogonal line segments join at right angles to form a square."),
            ("square", "HAS_PART", "angle", "Four perpendicular corners establish ninety-degree interior angles."),
            ("square", "ENCLOSES", "area", "Square bounds planar surface area equal to side length squared."),
            ("square", "IS_A", "shape", "A square is a regular four-sided planar polygon."),
        ],
    },
    {
        "domain": "geometry_radial_circles",
        "title": "Radial Symmetry & Circular Curvature",
        "description": "All points equidistant from a central anchor point form a circle; radius defines half the diameter; rotating a circle around its axis generates a 3D sphere.",
        "steps": [
            ("radius", "DEFINES", "circle", "Locus of all points at a fixed radial distance from origin forms a circle."),
            ("diameter", "EQUALS", "radius", "Collinear chord passing through center equals twice the radial length."),
            ("circle", "HAS_PROPERTY", "radius", "Constant radius establishes perfect radial symmetry across all orientations."),
            ("circle", "ENCLOSES", "area", "Circular perimeter bounds planar surface area proportional to radius squared."),
            ("circle", "ROTATES_INTO", "sphere", "Revolving a circle three hundred sixty degrees around its diameter generates a sphere."),
            ("sphere", "HAS_PART", "surface", "Exterior curved skin forms an equiradial spherical surface boundary."),
            ("circle", "IS_A", "shape", "A circle is a continuous curved two-dimensional planar shape."),
            ("sphere", "IS_A", "shape", "A sphere is a perfectly symmetrical three-dimensional curved solid."),
        ],
    },
    {
        "domain": "geometry_square_cube_scaling",
        "title": "Square Cube Dimensional Scaling Law",
        "description": "As an object scales linearly, its surface boundary expands quadratically by power of two, while its internal capacity expands cubically by power of three.",
        "steps": [
            ("area", "SCALES_AS", "square", "Surface area scales with the square of linear characteristic length."),
            ("cube", "SCALES_AS", "three", "Three-dimensional volumetric capacity scales with the cube of linear dimension."),
            ("surface", "EXPANDS_AS", "square", "Boundary skin growth rate decelerates relative to internal volume expansion."),
            ("sphere", "EXPANDS_AS", "cube", "Enclosed interior volume increases as the third power of radial expansion."),
            ("cube", "HAS_PART", "surface", "Six planar boundary faces form the exterior envelope of a cube."),
            ("cube", "IS_A", "solid", "A regular hexahedron is a three-dimensional Euclidean solid."),
            ("sphere", "IS_A", "solid", "A spherical manifold encloses continuous three-dimensional space."),
            ("cube", "IS_A", "shape", "A cube is a classical three-dimensional geometric polyhedron."),
        ],
    },
]


class SpatialGeometryEngine:
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
        """Store spatial geometry causal chains and semantic relations in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        # 1. Upsert causal implication chains
        for ch in GEOMETRY_CHAINS:
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
        for ch in GEOMETRY_CHAINS:
            for src_w, rel, dst_w, desc in ch["steps"]:
                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (src_w,))
                src_row = cur.fetchone()
                if not src_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'geometry', 1, ?)", (src_w, now_utc))
                    src_id = cur.lastrowid
                else:
                    src_id = src_row[0]

                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (dst_w,))
                dst_row = cur.fetchone()
                if not dst_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'geometry', 1, ?)", (dst_w, now_utc))
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
                        VALUES (?, ?, ?, 1.0, 'FIRST_PRINCIPLES_GEOMETRY_V1', ?)
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

    def ground_geometry_conduits(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground spatial geometry conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        injected_new = 0
        reinforced = 0
        missing = set()

        for chain in GEOMETRY_CHAINS:
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


def run_geometry_verification():
    engine = SpatialGeometryEngine()
    print("1. Compiling Spatial Geometry chains to ontology database...")
    c_count = engine.compile_chains_to_ontology()
    print(f"   Compiled/Updated {len(GEOMETRY_CHAINS)} chains into lexicon_ontology.db.")

    print("\n2. Grounding Spatial Geometry conduits into neural graph...")
    stats = engine.ground_geometry_conduits()
    print(f"   Injected New Links: {stats['new_links']}")
    print(f"   Reinforced Links:   {stats['reinforced_links']}")
    print(f"   Total Neurons:      {stats['total_neurons']}")
    print(f"   Total Links:        {stats['total_links']}")
    print(f"   Edge/Neuron Ratio:  {stats['edge_neuron_ratio']}")
    print(f"   Manifest Hash:      {stats['manifest_hash'][:16]}...")
    engine.close()

    print("\n3. Testing Wave Interference across Spatial Geometry...")
    g_path = Path(latest_run()) / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    res_engine = ConceptualResonanceEngine(graph)

    test_scenarios = [
        ("0D to 1D to 2D (Point/Line)", ["point", "line"]),
        ("Triangle Truss Rigidity", ["triangle", "rigid"]),
        ("Circular Radius to Sphere", ["circle", "radius"]),
        ("Square Cube Scaling (Area/Volume)", ["surface", "square"]),
        ("Abductive Boundary Diagnosis", ["perimeter", "area"]),
    ]

    for title, anchors in test_scenarios:
        attractors = res_engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_words = [f"{w} ({int(s):,})" for w, s in attractors]
        print(f"   Scenario [{title}]: anchors={anchors}")
        print(f"      Echoes -> {', '.join(top_words)}")

    graph.close()


if __name__ == "__main__":
    run_geometry_verification()
