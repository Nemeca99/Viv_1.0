"""Sensory Wave Dynamics & Universal Energy Conservation Engine for Viv.

Implements the Final Foundational Sensory and Physical Bedrock:
1. Light & Optics:
   - Straight-line ray propagation (sun -> light -> ray)
   - Opaque obstruction and shadows (obstacle -> blocks -> shadow)
   - Specular reflection (mirror -> reflects -> light -> image)
   - Refractive lens bending (glass / water -> bends / refracts -> lens -> focuses -> image)
2. Sound & Acoustic Waves:
   - Mechanical vibration of matter (vibration -> generates -> sound)
   - Medium requirement (sound -> traverses -> air / water / solid)
   - Vacuum barrier (vacuum -> prevents -> sound; no sound in space)
   - Acoustic boundaries and echoes (boundary -> reflects -> echo -> ear / sensor)
3. The Master Law: Conservation of Energy & Multi-State Transduction:
   - Total energy is strictly conserved (energy -> conserves -> work)
   - Multi-state cascade: Fuel (chemical) -> Boiler (thermal) -> Turbine (kinetic) -> Generator (electric) -> Bulb (light)
   - Thermodynamic dissipation: Friction and resistance dissipate usable work into ambient heat and entropy.

Grounds Viv in universal sensory reality and the physical law of conservation.
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

SENSORY_ENERGY_CHAINS = [
    {
        "domain": "optics_wave_propagation",
        "title": "Light Propagation, Reflection & Refraction",
        "description": "Light radiates as straight electromagnetic rays; opaque obstacles block rays casting shadows; specular surfaces reflect light; transparent media like glass or water refract and bend rays through lenses to focus images.",
        "steps": [
            ("sun", "RADIATES", "light", "High-temperature stellar fusion radiates broadband electromagnetic light."),
            ("light", "TRAVELS_AS", "ray", "Photons traverse homogeneous media in straight-line geometric rays."),
            ("light", "ILLUMINATES", "obstacle", "Light rays impinge upon intervening physical matter."),
            ("obstacle", "BLOCKS", "light", "Opaque matter absorbs or scatters incoming incident light rays."),
            ("obstacle", "CASTS", "shadow", "Occlusion of straight light rays creates an unilluminated shadow zone."),
            ("mirror", "REFLECTS", "light", "Smooth polished specular boundary redirects incident rays at equal reflection angles."),
            ("mirror", "FORMS", "image", "Reflected coherent rays produce a visible virtual or real image."),
            ("water", "REFRACTS", "light", "Optical density disparity bends light ray trajectories at fluid interfaces."),
            ("glass", "BENDS", "ray", "Differential refractive index decelerates and refracts light rays."),
            ("lens", "FOCUSES", "light", "Curved transparent glass converges or diverges rays to focus an optical image."),
        ],
    },
    {
        "domain": "acoustics_mechanical_vibration",
        "title": "Acoustic Waves, Physical Medium & Resonance",
        "description": "Sound is mechanical vibration propagating through material media; acoustic waves traverse gases, liquids, and solids, but cannot propagate across a vacuum; acoustic boundaries reflect echoes detected by ears or sensors.",
        "steps": [
            ("vibration", "GENERATES", "sound", "Periodic mechanical oscillation of physical mass generates acoustic pressure waves."),
            ("sound", "PROPAGATES_AS", "wave", "Longitudinal compression and rarefaction waves transmit acoustic energy."),
            ("sound", "REQUIRES", "air", "Acoustic pressure waves rely on compressible air molecules for transmission."),
            ("sound", "TRAVERSES", "water", "Fluid density enables rapid propagation of hydroacoustic pressure waves."),
            ("sound", "TRAVERSES", "solid", "Elastic atomic lattice transmits longitudinal and transverse acoustic waves."),
            ("vacuum", "PREVENTS", "sound", "Devoid of atomic matter, a vacuum provides no medium to transmit acoustic waves."),
            ("vibration", "DETERMINES", "pitch", "Fundamental oscillation frequency governs perceived high or low acoustic pitch."),
            ("boundary", "REFLECTS", "sound", "Acoustic impedance mismatch at rigid walls reflects returning waves."),
            ("sound", "CREATES", "echo", "Time-delayed reflection of sound waves off distant obstacles forms an echo."),
            ("ear", "DETECTS", "vibration", "Auditory sensors transduce incoming air vibrations into neural sensory signals."),
        ],
    },
    {
        "domain": "thermodynamics_energy_conservation",
        "title": "Conservation of Energy & Master Transduction Law",
        "description": "The First Law of Thermodynamics dictates total energy in an isolated system is strictly conserved; energy is never created or destroyed, only transduced between chemical, thermal, kinetic, electrical, and optical states with entropic dissipation.",
        "steps": [
            ("energy", "CONSERVES", "work", "Universal First Law: Total energy remains invariant; work done equals energy transduced."),
            ("fuel", "STORES", "chemical", "Molecular chemical bonds hold concentrated potential chemical energy."),
            ("chemical", "CONVERTS_TO", "thermal", "Exothermic combustion releases chemical bond energy as high-temperature heat."),
            ("thermal", "EXPANDS", "steam", "Thermal heat boils water into pressurized high-enthalpy expanding steam."),
            ("steam", "DRIVES", "kinetic", "Vapor expansion exerts mechanical pressure driving turbine kinetic rotation."),
            ("kinetic", "SPINS", "generator", "Rotating mechanical shaft spins magnetic rotor inside electrical generator."),
            ("generator", "PRODUCES", "electric", "Electromagnetic induction transduces mechanical kinetic energy into electric power."),
            ("electric", "POWERS", "light", "Electrical current energizes resistive filaments or diodes to emit optical light."),
            ("friction", "DISSIPATES", "heat", "Mechanical friction and electrical resistance irreversibly degrade usable energy into heat."),
            ("heat", "INCREASES", "entropy", "Second Law of Thermodynamics: Thermal dissipation increases total systemic entropy."),
        ],
    },
]


class SensoryEnergyEngine:
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
        """Store Sensory & Energy causal chains and semantic relations in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        # 1. Upsert causal implication chains
        for ch in SENSORY_ENERGY_CHAINS:
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
        for ch in SENSORY_ENERGY_CHAINS:
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
                        VALUES (?, ?, ?, 1.0, 'FIRST_PRINCIPLES_SENSORY_ENERGY_V1', ?)
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

    def ground_sensory_energy_conduits(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground Sensory & Conservation of Energy conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        injected_new = 0
        reinforced = 0
        missing = set()

        for chain in SENSORY_ENERGY_CHAINS:
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


def run_sensory_energy_verification():
    engine = SensoryEnergyEngine()
    print("1. Compiling Sensory & Energy chains to ontology database...")
    c_count = engine.compile_chains_to_ontology()
    print(f"   Compiled/Updated {len(SENSORY_ENERGY_CHAINS)} chains into lexicon_ontology.db.")

    print("\n2. Grounding Sensory & Conservation conduits into neural graph...")
    stats = engine.ground_sensory_energy_conduits()
    print(f"   Injected New Links: {stats['new_links']}")
    print(f"   Reinforced Links:   {stats['reinforced_links']}")
    print(f"   Total Neurons:      {stats['total_neurons']}")
    print(f"   Total Links:        {stats['total_links']}")
    print(f"   Edge/Neuron Ratio:  {stats['edge_neuron_ratio']}")
    print(f"   Manifest Hash:      {stats['manifest_hash'][:16]}...")
    engine.close()

    print("\n3. Testing Wave Interference across Light, Sound, and Conservation of Energy...")
    g_path = Path(latest_run()) / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    res_engine = ConceptualResonanceEngine(graph)

    test_scenarios = [
        ("Light & Shadow Ray Occlusion", ["light", "shadow"]),
        ("Mirror Reflection & Image", ["mirror", "image"]),
        ("Lens Refraction Focus", ["glass", "lens"]),
        ("Sound Transmission in Air", ["sound", "air"]),
        ("Vacuum Sound Barrier", ["sound", "vacuum"]),
        ("Acoustic Boundary Echo", ["sound", "echo"]),
        ("Fuel to Electricity Cascade", ["fuel", "electric"]),
        ("Energy Conservation Law", ["energy", "work"]),
    ]

    for title, anchors in test_scenarios:
        attractors = res_engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_words = [f"{w} ({int(s):,})" for w, s in attractors]
        print(f"   Scenario [{title}]: anchors={anchors}")
        print(f"      Echoes -> {', '.join(top_words)}")

    graph.close()


if __name__ == "__main__":
    run_sensory_energy_verification()
