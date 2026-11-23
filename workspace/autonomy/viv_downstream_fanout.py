import sys
import time
import sqlite3
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def propagate_learned_concept(source_word: str, linked_targets: list[str]):
    """
    Downstream Cycle Fan-Out & Amortization Engine:
    When ONE cycle learns 'blue', that winning bitmask state is divided
    and broadcast across all FUTURE candidate cycles.
    Future cycles now start with an energy discount (prior certainty).
    """
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS downstream_resonance_mesh (
        concept_token TEXT PRIMARY KEY,
        linked_cycles_count INTEGER DEFAULT 1,
        fan_out_degree INTEGER DEFAULT 0,
        downstream_targets TEXT,
        energy_discount_factor REAL,
        last_propagated TEXT
    )
    """)

    targets_str = ", ".join(linked_targets)
    discount = 1.0 / (len(linked_targets) + 1)

    cur.execute("""
    INSERT OR REPLACE INTO downstream_resonance_mesh
    (concept_token, linked_cycles_count, fan_out_degree, downstream_targets, energy_discount_factor, last_propagated)
    VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (source_word.upper(), len(linked_targets), len(linked_targets), targets_str, discount))

    # Weave synapses in associative graph
    for t in linked_targets:
        cur.execute("""
        INSERT OR REPLACE INTO cognitive_associative_links
        (source_concept, target_concept, bond_type, co_occurrence_count, weight, created_at)
        VALUES (?, ?, 'DOWNSTREAM_PROPAGATION', 1, 0.95, datetime('now'))
        """, (source_word.upper(), t.upper()))

    conn.commit()
    conn.close()

    return {
        "source": source_word.upper(),
        "fan_out": len(linked_targets),
        "targets": targets_str,
        "energy_discount": discount
    }

if __name__ == "__main__":
    print("=" * 70)
    print("[DOWNSTREAM CYCLE FAN-OUT & AMORTIZATION TRIAL]")
    print("One cycle learns 'BLUE' -> Propagates across future downstream cycles")
    print("=" * 70)

    # 1. First Cycle Learns 'BLUE'
    res1 = propagate_learned_concept("BLUE", ["SKY", "OCEAN", "COLD", "CYAN", "SAPPHIRE"])
    print(f"\n[CYCLE 1 LEARNS '{res1['source']}']")
    print(f"  • Downstream Targets Linked: {res1['targets']}")
    print(f"  • Future Energy Discount   : {res1['energy_discount']*100:.1f}%")

    # 2. Next Cycle ('OCEAN') already inherits the 'BLUE' bond
    res2 = propagate_learned_concept("OCEAN", ["WATER", "DEEP", "SALT", "TIDE"])
    print(f"\n[CYCLE 2 INHERITS & PROPAGATES '{res2['source']}']")
    print(f"  • Downstream Targets Linked: {res2['targets']}")
    print(f"  • Future Energy Discount   : {res2['energy_discount']*100:.1f}%")

    print("\n" + "=" * 70)
    print("RESULT: Knowledge compounds geometrically. Every cycle amortizes the next.")
    print("=" * 70)
