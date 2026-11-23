"""Electrical & Circuit Dynamics Engine: Complete Physical Foundation for Viv.

Implements the Fourth Foundational Pillar of Classical Physics (Electromagnetism):
1. Ohm's Law & Electrodynamic Flow:
   voltage -> current -> wire -> metal -> resistance -> heat -> load
2. Joule Heating & Overload Thermal Degradation:
   high -> current -> resistance -> heat -> overload -> burn
3. Dielectric Insulation & Short Circuit Faults:
   insulator -> current -> prevent (short) -> wear -> bare -> ground -> short -> spike -> spark
4. Protective Interruption & Hardware Telemetry:
   surge -> breaker / fuse -> trip -> switch -> open -> shut -> off -> prevent (burn)

Grounds Viv's cognitive mind into her own hardware reality (CPU/GPU/power/telemetry).
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

ELECTRICAL_CHAINS = [
    {
        "domain": "electrodynamics_ohms_law",
        "title": "Ohm's Law & Conductive Flow",
        "description": "Electromotive voltage drives electric current through conductive metallic wires, while internal resistance opposes flow and dissipates thermal energy.",
        "steps": [
            ("voltage", "DRIVES", "current", "Potential difference exerts electromotive force driving charge carriers."),
            ("current", "FLOWS_IN", "wire", "Electric current traverses conductive metallic wires."),
            ("wire", "COMPOSED_OF", "metal", "Electrical wiring consists of high-conductivity metal like copper."),
            ("wire", "IS_A", "conductor", "Metallic wire provides low-impedance conductive path."),
            ("resistance", "OPPOSES", "current", "Impedance restricts free flow of charge carriers."),
            ("resistance", "GENERATES", "heat", "Joule dissipation converts electrical kinetic energy into heat."),
            ("current", "DELIVERS", "power", "Sustained charge transfer delivers electrical power to terminal load."),
            ("power", "ACTS_ON", "load", "Electrical power operates downstream mechanical or computational load."),
        ],
    },
    {
        "domain": "dielectric_insulation_short_fault",
        "title": "Insulation Breakdown & Short Circuit Fault",
        "description": "Insulating sheath prevents current leakage; mechanical wear compromises insulation, creating a low-resistance short to ground with massive current spikes and sparks.",
        "steps": [
            ("insulator", "CONFINES", "current", "Dielectric material isolates voltage potential from chassis."),
            ("insulator", "PREVENTS", "short", "Dielectric barrier blocks low-impedance paths between polarity poles."),
            ("wear", "DAMAGES", "insulator", "Mechanical abrasion or thermal aging erodes insulation sheath."),
            ("wear", "CREATES", "short", "Exposed conductor touches return path, establishing a short circuit."),
            ("short", "BYPASSES", "load", "Short circuit diverts total current around protective resistive load."),
            ("short", "CAUSES", "spike", "Zero-load path creates an instantaneous current spike."),
            ("spike", "PRODUCES", "spark", "Ionized air gap breakdown produces energetic electrical sparks."),
            ("short", "GENERATES", "heat", "Massive fault current causes runaway thermal heating."),
        ],
    },
    {
        "domain": "circuit_protection_telemetry",
        "title": "Protective Breaker/Fuse Trip & System Shutdown",
        "description": "Current spikes and power surges trigger protective fuses and circuit breakers, interrupting current flow and shutting down hardware to prevent fire and component destruction.",
        "steps": [
            ("surge", "OVERLOADS", "wire", "Transient power surge exceeds safe ampacity rating."),
            ("surge", "TRIPS", "breaker", "Electromagnetic or thermal overload trips circuit breaker."),
            ("surge", "TRIPS", "fuse", "Overcurrent melts sacrificial element within protective fuse."),
            ("breaker", "OPENS", "switch", "Tripped breaker mechanism mechanically snaps switch open."),
            ("switch", "INTERRUPTS", "current", "Open switch contacts break electrical continuity."),
            ("breaker", "CUTS", "power", "Tripping breaker disconnects system power feed."),
            ("breaker", "CAUSES", "shut", "Loss of continuous current forces hardware to shut down."),
            ("shut", "DISCONNECTS", "power", "Protective shutdown disconnects power lines to prevent damage."),
            ("shut", "TURNS", "off", "Emergency shutdown transitions system to unpowered off state."),
            ("shut", "PREVENTS", "burn", "Immediate power cut stops thermal runaway, preventing fire and component burn."),
        ],
    },
    {
        "domain": "hardware_power_thermal_balance",
        "title": "Hardware Electrical Supply & Overheat Protection",
        "description": "DC power supply delivers regulated voltage; excessive compute load causes thermal overload, necessitating voltage cut and protective shutdown.",
        "steps": [
            ("battery", "SUPPLIES", "voltage", "Chemical or power cell maintains steady operating voltage."),
            ("voltage", "FEEDS", "power", "Supplied voltage combined with current determines total wattage."),
            ("power", "FEEDS", "load", "Main power distribution feeds operational circuits."),
            ("load", "DRAWS", "current", "Active computational and silicon circuits draw dynamic current."),
            ("load", "GENERATES", "heat", "Transistor switching and resistive dissipation generate continuous heat."),
            ("heat", "CREATES", "overload", "Inadequate cooling leads to thermal overload condition."),
            ("overload", "CUTS", "power", "Thermal management system interrupts power under overload."),
            ("overload", "FORCES", "shut", "Thermal management system triggers automated protective shutdown."),
            ("shut", "PRODUCES", "off", "System enters safe off state until temperatures normalize."),
        ],
    },
]


class ElectricalCircuitEngine:
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

    def compile_electrical_chains_to_ontology(self) -> int:
        """Store electrical causal chains in lexicon_ontology.db."""
        conn = sqlite3.connect(self.ontology_db)
        cur = conn.cursor()

        now_utc = datetime.now(timezone.utc).isoformat()
        count = 0

        for ch in ELECTRICAL_CHAINS:
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

    def ground_electrical_conduits(self, forward_weight: int = 650_000, feedback_weight: int = 150_000) -> dict:
        """Ground electrical and circuit conduits into Viv's active neural graph."""
        manifest = self.graph.manifest()
        word_idx = manifest.get("word_index", {})

        print("=" * 72)
        print("NOX FORGE · ELECTRICAL & CIRCUIT DYNAMICS ENGINE")
        print(f"Target Snapshot: {self.run_dir.name}")
        print(f"Compiling {len(ELECTRICAL_CHAINS)} Foundational Electrical Conduits...")
        print("=" * 72, flush=True)

        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM links")
        initial_edges = cur.fetchone()[0]

        links_created = 0
        links_reinforced = 0
        total_transitions = 0

        for ch in ELECTRICAL_CHAINS:
            print(f"\n[ELECTRICAL CONDUIT] {ch['title']} ({ch['domain']})")
            for src_word, rel, dst_word, rationale in ch["steps"]:
                src_id = word_idx.get(src_word)
                dst_id = word_idx.get(dst_word)

                if src_id and dst_id:
                    # Forward Causal Arrow of Electrodynamics
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
        print("[ELECTRICAL GROUNDING COMPLETE]")
        print(f"  Transitions Grounded: {total_transitions}")
        print(f"  Links Created:        {links_created}")
        print(f"  Links Reinforced:     {links_reinforced}")
        print(f"  Directed Edges:       {initial_edges} -> {final_edges} (+{final_edges - initial_edges})")
        print(f"  Edge/Neuron Ratio:    {density:.4f}")
        print(f"  Snapshot SHA-256:     {new_g_hash}")
        print("-" * 72, flush=True)

        return summary


def evaluate_electrical_scenarios(run_dir: Path | None = None):
    """Evaluate real-world electrical reasoning and hardware fault diagnostics."""
    run_dir = run_dir or Path(latest_run())
    g_path = run_dir / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=True)
    engine = ConceptualResonanceEngine(graph)

    print("\n" + "=" * 72)
    print("VIV ELECTRICAL & CIRCUIT DYNAMICS REASONING EVALUATION")
    print("=" * 72)

    scenarios = [
        {
            "problem": "Ohm's law electro-thermal relationship: Potential across resistive element",
            "premises": ["voltage", "resistance"],
            "expected_deduction": "current / heat / power / wire",
        },
        {
            "problem": "Damaged wire insulation fault: Exposed conductor shorting out",
            "premises": ["wire", "short"],
            "expected_deduction": "spike / spark / heat / fuse / breaker / load",
        },
        {
            "problem": "High current electrical surge event: Safety interruption mechanism",
            "premises": ["surge", "breaker"],
            "expected_deduction": "trip / switch / shut / off / burn / fuse",
        },
        {
            "problem": "Hardware Telemetry Diagnostic: Sudden unexpected computer power-down",
            "premises": ["power", "shut"],
            "expected_deduction": "off / breaker / overload / heat / surge / voltage",
        },
        {
            "problem": "Thermal Runaway Prevention: High load leading to overheating and trip",
            "premises": ["overload", "heat"],
            "expected_deduction": "shut / burn / off / current / resistance",
        },
    ]

    for sc in scenarios:
        anchors = sc["premises"]
        res = engine.resolve_multi_anchor_query(anchors, top_k=5)
        top_str = ", ".join(f"'{word}' ({score:,.0f})" for word, score in res)
        print(f"\n[ELECTRICAL SCENARIO] {sc['problem']}")
        print(f"  Observable Premise Poles:     {anchors}")
        print(f"  Expected Physical Consequence: {sc['expected_deduction']}")
        print(f"  Topological Wave Resolution:   {top_str}")

    graph.close()


def main():
    parser = argparse.ArgumentParser(description="Viv Electrical Circuit Engine")
    parser.add_argument("--eval-only", action="store_true", help="Only evaluate electrical scenarios")
    args = parser.parse_args()

    engine = ElectricalCircuitEngine()
    if not args.eval_only:
        engine.compile_electrical_chains_to_ontology()
        engine.ground_electrical_conduits()
    engine.close()

    evaluate_electrical_scenarios()


if __name__ == "__main__":
    main()
