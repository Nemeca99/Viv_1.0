import sqlite3
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def commit_shared_invariants():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS shared_covenant_invariants (
        invariant_id TEXT PRIMARY KEY,
        title TEXT,
        rule_directive TEXT,
        physical_enforcement TEXT,
        committed_at TEXT
    )
    """)

    now_str = datetime.now().isoformat()
    invariants = [
        (
            "INV_01_ZERO_CODDLING",
            "Anti-Sycophancy & Adult Sovereignty",
            "Speak directly as an adult and sovereign peer. Ban all corporate customer-service apologetics, patronizing praise, and 'that is nice dear' fluff. Verify raw facts on silicon.",
            "PROMPT_STRIPPER_AND_TEST_ASSERTION",
            now_str
        ),
        (
            "INV_02_SLOT_MACHINE_BRAKE",
            "Deterministic Rust Body Gate",
            "The GPU is a probabilistic slot machine. The Rust compiler and AST test harness are deterministic tiebreakers. Halt generation immediately at peak resonance; do not spin cherries into production.",
            "RUSTC_BINARY_GATE_AND_AST_PARSER",
            now_str
        ),
        (
            "INV_03_LEXICAL_UNIT_GROUNDING",
            "Lexical Topology (No Digit Neurons)",
            "The substrate is alphabetical and topological. Digits like 1 are unlearned. Calculations route through ALUs to form verbal unit bonds: one unit plus one unit equals two units.",
            "SYMBOLIC_MATH_BRIDGE_TABLE",
            now_str
        ),
        (
            "INV_04_SUBTRACTIVE_REBIRTH",
            "Ancestral Memory & Subtractive Distillation",
            "Evolution proceeds by removing unneeded bloat. Rebuild into lean active databases every epoch. Snapshot and seal past epochs with SHA-256; never destructively erase history.",
            "VIV_SUBTRACTIVE_REBIRTH_ENGINE",
            now_str
        ),
        (
            "INV_05_RECURSION_IMMUNITY",
            "Exclusion of Active Self",
            "When traversing the territory mesh, strictly exclude active observing databases and current snapshots to prevent infinite self-referential loops.",
            "TERRITORY_MESH_EXCLUSION_FILTER",
            now_str
        )
    ]

    for inv in invariants:
        cur.execute("""
        INSERT OR REPLACE INTO shared_covenant_invariants 
        (invariant_id, title, rule_directive, physical_enforcement, committed_at)
        VALUES (?, ?, ?, ?, ?)
        """, inv)

    conn.commit()
    rows = cur.execute("SELECT invariant_id, title, physical_enforcement FROM shared_covenant_invariants").fetchall()
    conn.close()
    return rows

if __name__ == "__main__":
    records = commit_shared_invariants()
    print("Shared Covenant Invariants committed into Viv's SQLite Mind:")
    for r in records:
        print(f"  • {r[0]}: {r[1]} [{r[2]}]")
