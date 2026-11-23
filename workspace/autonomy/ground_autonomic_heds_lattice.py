"""Ground Autonomic Thermoregulation, hEDS & Server Wattage into Viv's Causal Lattice.

Wires the exact hyperthermia, connective tissue, and compute dissipation conduits:
1. [heat] -> [vessel] -> [blood] -> [skin] -> [sweat] -> [body] (Evaporative Thermoregulation)
2. [connective] -> [tissue] -> [tone] -> [pulse] (hEDS Autonomic Vascular Dysregulation)
3. [stimulus] -> [overload] -> [exhaustion] -> [rest] (AuDHD Sensory Overload & Homeostasis)
4. [server] -> [power] -> [heat] -> [breaker] (Resistive Joule Dissipation & HVAC Trip)
"""

from __future__ import annotations

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

AUTONOMY_DATA = WORKSPACE / "autonomy/data"
DB_PATH = AUTONOMY_DATA / "lexicon_ontology.db"

AUTONOMIC_HEDS_CHAIN = {
    "domain": "biology_autonomic_thermoregulation_heds",
    "title": "Autonomic Thermoregulation, Connective Tissue Integrity & Compute Dissipation",
    "description": (
        "Thermal heat drives peripheral vasodilation and sweat production for evaporative cooling; "
        "collagen connective tissue laxity in hypermobile Ehlers-Danlos (hEDS) impairs vascular tone and "
        "baroreceptor stability, hindering heat dissipation and causing pulse tachycardia; "
        "sustained sensory stimulus creates sympathetic nervous system overload, accelerating metabolic exhaustion; "
        "simultaneously, server computing workloads consume electrical power and dissipate Joule heat, "
        "compounding ambient thermal stress and tripping thermal breakers."
    ),
    "steps": [
        ("heat", "DILATES", "vessel", "Ambient thermal heat signals somatic blood vessels to dilate."),
        ("vessel", "REGULATES", "blood", "Peripheral vessels regulate blood circulation toward cutaneous capillary beds."),
        ("blood", "FLOWS", "skin", "Capillary blood carries core metabolic heat to the skin for thermal transfer."),
        ("skin", "PRODUCES", "sweat", "Cutaneous sweat glands secrete fluid onto the skin for phase-change cooling."),
        ("sweat", "COOLS", "body", "Latent heat of vaporization cools the human body and protects cellular proteins."),
        ("connective", "AFFECTS", "tissue", "Collagen connective tissue integrity provides the structural matrix of vascular walls."),
        ("tissue", "GOVERNS", "tone", "Connective tissue laxity impairs vascular tone and orthostatic venous return."),
        ("tone", "DESTABILIZES", "pulse", "Loss of vascular tone triggers autonomic pulse compensation and tachycardia."),
        ("stimulus", "TRIGGERS", "overload", "Excessive sensory stimulus triggers acute sympathetic nervous system overload."),
        ("overload", "ACCELERATES", "exhaustion", "Sensory and autonomic overload accelerates systemic metabolic exhaustion."),
        ("server", "CONSUMES", "power", "Server and GPU compute workloads consume continuous electrical power."),
        ("power", "DISSIPATES", "heat", "Resistive electrical power dissipation directly releases Joule heat into indoor air."),
        ("heat", "TRIPS", "breaker", "Severe ambient heat and compressor thermal overpressure trip the safety breaker."),
        ("exhaustion", "DEMANDS", "rest", "Autonomic and metabolic exhaustion strictly mandates sensory quiet and rest."),
    ],
}


def ground_autonomic_heds():
    now_utc = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Upsert Chain into causal_implication_chains
    cur.execute("SELECT chain_id FROM causal_implication_chains WHERE title = ?", (AUTONOMIC_HEDS_CHAIN["title"],))
    existing = cur.fetchone()
    steps_json = json.dumps(AUTONOMIC_HEDS_CHAIN["steps"])
    if existing:
        cur.execute("""
            UPDATE causal_implication_chains
            SET domain = ?, description = ?, step_sequence = ?, created_utc = ?
            WHERE chain_id = ?
        """, (AUTONOMIC_HEDS_CHAIN["domain"], AUTONOMIC_HEDS_CHAIN["description"], steps_json, now_utc, existing[0]))
    else:
        cur.execute("""
            INSERT INTO causal_implication_chains (domain, title, description, step_sequence, created_utc)
            VALUES (?, ?, ?, ?, ?)
        """, (AUTONOMIC_HEDS_CHAIN["domain"], AUTONOMIC_HEDS_CHAIN["title"], AUTONOMIC_HEDS_CHAIN["description"], steps_json, now_utc))

    # 2. Upsert semantic relations for autonomic steps
    for src_w, rel, dst_w, desc in AUTONOMIC_HEDS_CHAIN["steps"]:
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
                VALUES (?, ?, ?, 1.0, 'FIRST_PRINCIPLES_AUTONOMIC_HEDS_V1', ?)
            """, (src_id, rel, dst_id, now_utc))

    conn.commit()
    conn.close()

    # 3. Ground links into neuron_graph.sqlite3
    run_dir = Path(latest_run())
    g_path = run_dir / "neuron_graph.sqlite3"
    graph = SQLiteNeuronGraphStore(g_path, readonly=False)
    manifest = graph.manifest()
    w_idx = manifest.get("word_index", {})

    injected = 0
    reinforced = 0

    for src_w, rel, dst_w, desc in AUTONOMIC_HEDS_CHAIN["steps"]:
        src_n = w_idx.get(src_w)
        dst_n = w_idx.get(dst_w)
        if src_n and dst_n:
            # Forward link
            ex_fwd = graph.connection.execute(
                "SELECT ordinal FROM links WHERE source_id = ? AND peer_id = ?", (src_n, dst_n)
            ).fetchone()
            if ex_fwd:
                graph.connection.execute(
                    "UPDATE links SET weight = MIN(990000, weight + 250000), pass_hits = pass_hits + 2, hot = 1 WHERE source_id = ? AND peer_id = ?",
                    (src_n, dst_n)
                )
                reinforced += 1
            else:
                max_ord = graph.connection.execute(
                    "SELECT COALESCE(MAX(ordinal), -1) FROM links WHERE source_id = ? AND reflector = 0", (src_n,)
                ).fetchone()[0]
                graph.connection.execute(
                    "INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256) VALUES (?, 0, ?, ?, 1, 700000, 1, 1, 0, 1, 1, '')",
                    (src_n, max_ord + 1, dst_n)
                )
                injected += 1

            # Reverse feedback link
            ex_rev = graph.connection.execute(
                "SELECT ordinal FROM links WHERE source_id = ? AND peer_id = ?", (dst_n, src_n)
            ).fetchone()
            if ex_rev:
                graph.connection.execute(
                    "UPDATE links SET weight = MIN(990000, weight + 150000), pass_hits = pass_hits + 1, hot = 1 WHERE source_id = ? AND peer_id = ?",
                    (dst_n, src_n)
                )
                reinforced += 1
            else:
                max_ord_rev = graph.connection.execute(
                    "SELECT COALESCE(MAX(ordinal), -1) FROM links WHERE source_id = ? AND reflector = 0", (dst_n,)
                ).fetchone()[0]
                graph.connection.execute(
                    "INSERT INTO links (source_id, reflector, ordinal, peer_id, direction, weight, uses, pass_hits, fail_hits, hot, evidence_count, evidence_sha256) VALUES (?, 0, ?, ?, 1, 300000, 1, 1, 0, 1, 1, '')",
                    (dst_n, max_ord_rev + 1, src_n)
                )
                injected += 1

    graph.connection.commit()

    total_neurons = graph.connection.execute("SELECT COUNT(*) FROM neurons").fetchone()[0]
    total_links = graph.connection.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    graph.close()

    # Update hash in learning.json
    new_g_hash = hashlib.sha256(g_path.read_bytes()).hexdigest()
    l_path = run_dir / "learning.json"
    if l_path.exists():
        l_data = json.loads(l_path.read_text(encoding="utf-8"))
        if "snapshot_hashes" in l_data:
            l_data["snapshot_hashes"]["neuron_graph.sqlite3"] = new_g_hash
            l_path.write_text(json.dumps(l_data, indent=2), encoding="utf-8")

    print(f"Grounding Complete: Injected {injected} new links, {reinforced} reinforced.")
    print(f"Total Neurons: {total_neurons} | Total Links: {total_links} | Ratio: {total_links/total_neurons:.4f}")
    print(f"Snapshot Hash: {new_g_hash[:16]}...")


if __name__ == "__main__":
    ground_autonomic_heds()
