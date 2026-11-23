"""Biological Homeostasis, Metabolism & Living Systems Engine for Viv.

Implements the Biological Bedrock for the Steward as Guardian of Human Life:
1. Metabolism & Cellular Respiration (The Living Thermodynamic Engine):
   - Human organism consumes food biomass as concentrated chemical potential energy.
   - Respiratory lungs inhale atmospheric oxygen for oxidative phosphorylation.
   - Digestion and cellular mitochondria transduce fuel into glucose and ATP.
   - ATP hydrolyzes into kinetic muscular contraction and essential thermal heat.
   - Inevitable metabolic byproduct generation discharges chemical waste and carbon dioxide.
2. Homeostatic Negative Feedback & Thermoregulation:
   - Living systems actively counter entropy via autonomous negative feedback loops.
   - Ambient cold threats trigger involuntary shivering, using muscle friction to generate heat.
   - Thermal overpressure triggers sweat secretion, using evaporative phase cooling to cool skin.
   - Dehydration and caloric depletion emit regulatory signals (thirst, hunger) to compel intake.
3. Electrochemical Nervous System & Sensorimotor Telemetry:
   - Biological circuits operate on electrochemical action potential pulses.
   - Sensory organs (optics/eye, acoustics/ear, dermal/skin) capture environmental physical stimuli.
   - Afferent nerve pathways conduct electrical pulses into the central brain.
   - The brain calculates motor signals and transmits reflex commands to muscles for movement.
4. Autonomous Immune Defense & Pathogen Neutralization:
   - Biological integrity is defended against invasive pathogens (bacteria, viruses).
   - Cellular damage and infection activate systemic immune responses.
   - White blood cells mobilize specialized antibodies to bind and neutralize invaders.
   - The central brain intentionally elevates core body temperature (fever) to denature pathogens.
   - Immune clearance heals tissues and restores homeostatic equilibrium.

Grounds Viv as a protective Steward with deep comprehension of human biological vulnerability.
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

BIOLOGICAL_CHAINS = [
    {
        "domain": "biology_metabolism_respiration",
        "title": "Metabolism, Respiration & Thermodynamic Life Support",
        "description": "Biological life operates as a thermodynamic engine; food biomass is metabolized with inhaled oxygen into glucose and ATP, powering muscular work and bodily heat while discharging metabolic waste.",
        "steps": [
            ("human", "CONSUMES", "food", "Human organism consumes nutritional biomass as chemical fuel."),
            ("food", "PROVIDES", "chemical", "Nutritional intake stores potential chemical energy in molecular bonds."),
            ("lung", "INHALES", "oxygen", "Respiratory lungs extract atmospheric oxygen for cellular aerobic oxidation."),
            ("oxygen", "POWERS", "cell", "Oxygen molecules diffuse through tissue capillaries to power cellular respiration."),
            ("cell", "CONVERTS_TO", "glucose", "Digestive and metabolic pathways break down nutrients into circulating glucose."),
            ("glucose", "GENERATES", "energy", "Mitochondrial glucose catabolism generates high-energy cellular ATP bonds."),
            ("energy", "FUELS", "muscle", "Chemical ATP hydrolysis delivers energy to contract skeletal and cardiac muscles."),
            ("muscle", "PRODUCES", "heat", "Metabolic muscular exertion expends energy and radiates essential basal body heat."),
            ("cell", "DISCHARGES", "waste", "Thermodynamic metabolic work inevitably discharges chemical byproducts and waste."),
        ],
    },
    {
        "domain": "biology_homeostatic_feedback",
        "title": "Homeostatic Negative Feedback & Thermoregulation",
        "description": "Homeostasis maintains internal physiological equilibrium against environmental entropy; ambient cold triggers involuntary muscle shivering to generate friction heat, while excessive heat triggers sweating for evaporative cooling.",
        "steps": [
            ("body", "REGULATES", "thermal", "The organism maintains a strict homeostatic core body temperature near 37C."),
            ("cold", "THREATENS", "body", "Sub-zero ambient air draws thermal energy away, creating severe hypothermia risk."),
            ("body", "TRIGGERS", "shiver", "Hypothalamic sensors detect temperature drop and initiate involuntary shivering oscillations."),
            ("shiver", "GENERATES", "heat", "Rapid antagonistic muscle contractions generate kinetic friction heat to warm the core."),
            ("hot", "TRIGGERS", "sweat", "Elevated ambient or metabolic temperature signals sweat glands to secrete liquid."),
            ("sweat", "COOLS", "skin", "Latent heat of vaporization evaporates sweat off the skin, drawing away excess heat."),
            ("waste", "CREATES", "thirst", "Continuous fluid loss through respiration and perspiration triggers the thirst reflex."),
            ("thirst", "REQUIRES", "water", "The thirst drive compels the human organism to drink water and restore fluid balance."),
            ("hunger", "DEMANDS", "food", "Depleted circulating glucose triggers the hunger reflex, compelling caloric replenishment."),
        ],
    },
    {
        "domain": "biology_electrochemical_nervous",
        "title": "Electrochemical Nervous System & Sensorimotor Reflex",
        "description": "The nervous system is an electrochemical network transducing physical stimuli into electrical action potentials; sensory organs transmit pulses to the brain, which commands rapid muscular movement and protective reflexes.",
        "steps": [
            ("eye", "CAPTURES", "light", "Retinal photoreceptor cells transduce incident optical light rays into neural signals."),
            ("ear", "DETECTS", "sound", "Cochlear hair cells detect mechanical acoustic pressure waves."),
            ("skin", "SENSES", "stimulus", "Dermal mechanoreceptors and thermoreceptors detect physical pressure and heat stimuli."),
            ("stimulus", "TRIGGERS", "nerve", "External mechanical or thermal stimuli activate sensory neuron membrane potentials."),
            ("nerve", "CONDUCTS", "pulse", "Nerve axons conduct rapid electrochemical action potential pulses."),
            ("pulse", "REACHES", "brain", "Afferent nerve pulses propagate into the brain for sensory telemetry processing."),
            ("brain", "PROCESSES", "pulse", "Neural cerebral networks integrate sensory signals to evaluate environmental threat."),
            ("brain", "COMMANDS", "reflex", "The brain issues immediate efferent motor instructions via somatic reflex arcs."),
            ("reflex", "ACTUATES", "muscle", "Motor neuron action potentials depolarize muscle fibers to actuate rapid contraction."),
            ("muscle", "EXECUTES", "movement", "Contracting muscle groups exert mechanical force to execute protective movement."),
        ],
    },
    {
        "domain": "biology_immune_pathogen_defense",
        "title": "Autonomous Immune Defense & Pathogen Neutralization",
        "description": "The immune system is the organism's autonomous defense architecture; when invasive bacteria or viruses cause cellular infection, antibodies neutralize the pathogens and the body creates a protective fever.",
        "steps": [
            ("virus", "CAUSES", "infection", "Invasive viral particles penetrate mucosal boundaries to initiate cellular infection."),
            ("bacteria", "ATTACKS", "cell", "Pathogenic bacteria secrete toxins and invade living host cells, causing damage."),
            ("damage", "TRIGGERS", "immune", "Cellular lysis and damage-associated molecular patterns activate systemic immune response."),
            ("immune", "MOBILIZES", "antibody", "Immune leukocytes mobilize antigen-specific antibodies to neutralize pathogens."),
            ("body", "CREATES", "fever", "The brain intentionally shifts the thermal setpoint upward, inducing a systemic fever."),
            ("fever", "INHIBITS", "virus", "Elevated core body temperature denatures viral proteins and suppresses pathogen growth."),
            ("antibody", "DESTROYS", "bacteria", "Targeted antibody opsonization and phagocytosis destroy invading bacterial colonies."),
            ("immune", "PROTECTS", "human", "Continuous immune surveillance protects human life from fatal infectious degradation."),
            ("immune", "HEALS", "body", "Tissue regenerative cytokines stimulate cellular mitosis to heal wounds and damage."),
        ],
    },
]


class BiologicalHomeostasisEngine:
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
        """Store Biological & Homeostatic causal chains and semantic relations in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        # 1. Upsert causal implication chains
        for ch in BIOLOGICAL_CHAINS:
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
        for ch in BIOLOGICAL_CHAINS:
            for src_w, rel, dst_w, desc in ch["steps"]:
                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (src_w,))
                src_row = cur.fetchone()
                if not src_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'biology', 1, ?)", (src_w, now_utc))
                    src_id = cur.lastrowid
                else:
                    src_id = src_row[0]

                cur.execute("SELECT entity_id FROM lexical_entities WHERE lemma = ?", (dst_w,))
                dst_row = cur.fetchone()
                if not dst_row:
                    cur.execute("INSERT INTO lexical_entities (lemma, part_of_speech, domain, is_concrete, created_utc) VALUES (?, 'noun', 'biology', 1, ?)", (dst_w, now_utc))
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
                        VALUES (?, ?, ?, 1.0, 'FIRST_PRINCIPLES_BIOLOGY_HOMEOSTASIS_V1', ?)
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

    def ground_biological_conduits(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground Biological & Homeostasis conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        injected_new = 0
        reinforced = 0
        missing = set()

        for chain in BIOLOGICAL_CHAINS:
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


def run_biological_verification():
    engine = BiologicalHomeostasisEngine()
    print("1. Compiling Biological & Homeostatic chains to ontology database...")
    c_count = engine.compile_chains_to_ontology()
    print(f"   Compiled/Updated {len(BIOLOGICAL_CHAINS)} chains into lexicon_ontology.db.")

    print("\n2. Grounding Biological Homeostasis conduits into neural graph...")
    stats = engine.ground_biological_conduits()
    print(f"   Injected New Links: {stats['new_links']}")
    print(f"   Reinforced Links:   {stats['reinforced_links']}")
    print(f"   Missing Tokens:     {stats['missing_tokens']}")
    print(f"   Total Neurons:      {stats['total_neurons']}")
    print(f"   Total Links:        {stats['total_links']}")
    print(f"   Edge/Neuron Ratio:  {stats['edge_neuron_ratio']}")
    print(f"   Manifest Hash:      {stats['manifest_hash'][:16]}...")
    engine.close()

    print("\n3. Testing Wave Interference across Biological Homeostasis & Living Systems...")
    g_path = Path(latest_run()) / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    res_engine = ConceptualResonanceEngine(graph)

    test_scenarios = [
        ("Hypothermia Shiver Defense", ["cold", "shiver"]),
        ("Thermal Overpressure Sweating", ["hot", "sweat"]),
        ("Metabolic Caloric Replenishment", ["food", "energy"]),
        ("Dehydration Thirst Reflex", ["waste", "thirst"]),
        ("Electrochemical Neural Action Pulse", ["stimulus", "nerve"]),
        ("Sensorimotor Muscle Reflex", ["brain", "reflex"]),
        ("Viral Pathogen Fever Response", ["virus", "fever"]),
        ("Immune Antibody Neutralization", ["bacteria", "antibody"]),
        ("Human Steward Protective Shield", ["human", "protect"]),
    ]

    for title, anchors in test_scenarios:
        attractors = res_engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_words = [f"{w} ({int(s):,})" for w, s in attractors]
        print(f"   Scenario [{title}]: anchors={anchors}")
        print(f"      Echoes -> {', '.join(top_words)}")

    graph.close()


if __name__ == "__main__":
    run_biological_verification()
