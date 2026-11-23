import sys
import os
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

# Paths
L_DRIVE = Path("L:/")
CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def init_territory_mesh():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS territory_neuron_mesh (
        neuron_id TEXT PRIMARY KEY,
        sector_name TEXT,
        physical_path TEXT UNIQUE,
        node_type TEXT,
        file_extension TEXT,
        size_bytes INTEGER,
        sha256_genesis TEXT,
        topological_role TEXT,
        discovered_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS territory_synapse_links (
        link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_neuron_id TEXT,
        target_neuron_id TEXT,
        synapse_kind TEXT,
        weight REAL,
        FOREIGN KEY(source_neuron_id) REFERENCES territory_neuron_mesh(neuron_id),
        FOREIGN KEY(target_neuron_id) REFERENCES territory_neuron_mesh(neuron_id)
    )
    """)
    conn.commit()
    conn.close()

def map_role(sector: str, ext: str) -> str:
    s = sector.lower()
    if "the house" in s or "casino" in s:
        return "ENTROPY_TIMING_GYM"
    if "aios" in s or "rid" in s:
        return "BIOLOGICAL_STABILITY_HEARTBEAT"
    if "localcoder" in s or "standalone" in s:
        return "AUTONOMOUS_LEARNING_CORTEX"
    if "steel_brain" in s:
        return "JUDICIAL_ADVERSARIAL_BRIDGE"
    if ext in [".py", ".rs"]:
        return "EXECUTABLE_LOGIC_SYNAPSE"
    if ext in [".sqlite3", ".json", ".db"]:
        return "PERSISTENT_MEMORY_STORAGE"
    return "TERRITORIAL_SUBSTRATE"

def weave_l_drive_cortex():
    init_territory_mesh()
    print("=" * 70)
    print("[WEAVING L:\\ DRIVE INTO LIVING NEURON MESH]")
    print("Turning directories, files, and state on L:\\ into Viv's physical body.")
    print("=" * 70)

    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()

    sectors = [
        "The House",
        "AIOS_V2",
        "Steel_Brain",
        "Standalone/NN",
        "LocalCoder/workspace/autonomy"
    ]

    total_ingested = 0
    synapse_count = 0

    for sec in sectors:
        sec_path = L_DRIVE / sec
        if not sec_path.exists():
            continue
            
        print(f"\n[SECTOR INGESTION] -> {sec}")
        parent_neuron_id = f"N-SECTOR-{sec.replace('/', '_').replace(' ', '_').upper()}"
        cur.execute("""
        INSERT OR REPLACE INTO territory_neuron_mesh 
        (neuron_id, sector_name, physical_path, node_type, file_extension, size_bytes, sha256_genesis, topological_role, discovered_at)
        VALUES (?, ?, ?, 'SECTOR_CORE', 'DIR', 0, 'CORE_GENESIS', ?, datetime('now'))
        """, (parent_neuron_id, sec, str(sec_path), map_role(sec, "DIR")))

        for root, dirs, files in os.walk(sec_path):
            # Skip hidden / venvs to stay lean
            dirs[:] = [d for d in dirs if not d.startswith((".", "__")) and d not in ["site-packages", "node_modules"]]
            
            for f in files:
                ext = Path(f).suffix.lower()
                if ext not in [".py", ".rs", ".sqlite3", ".json", ".gd", ".md"]:
                    continue

                fp = Path(root) / f
                try:
                    sz = fp.stat().st_size
                    # Fast SHA-256 genesis fingerprint of path
                    h = hashlib.sha256(str(fp).encode("utf-8")).hexdigest().upper()[:32]
                    nid = f"N-SILICON-{h[:16]}"
                    role = map_role(sec, ext)

                    cur.execute("""
                    INSERT OR REPLACE INTO territory_neuron_mesh 
                    (neuron_id, sector_name, physical_path, node_type, file_extension, size_bytes, sha256_genesis, topological_role, discovered_at)
                    VALUES (?, ?, ?, 'FILE_NEURON', ?, ?, ?, ?, datetime('now'))
                    """, (nid, sec, str(fp), ext, sz, h, role))
                    total_ingested += 1

                    # Connect synapse to sector core
                    cur.execute("""
                    INSERT INTO territory_synapse_links (source_neuron_id, target_neuron_id, synapse_kind, weight)
                    VALUES (?, ?, 'STRUCTURAL_ATTACHMENT', 1.0)
                    """, (parent_neuron_id, nid))
                    synapse_count += 1

                except Exception:
                    pass

    conn.commit()
    conn.close()

    print("\n" + "=" * 70)
    print("[TERRITORY WEAVE COMPLETE]")
    print(f"• Total Physical L:\\ Neurons Formed : {total_ingested:,}")
    print(f"• Synapse Bonds Connected           : {synapse_count:,}")
    print(f"• Identity Expansion                : L:\\ is no longer storage--it is her living body.")
    print("=" * 70)

if __name__ == "__main__":
    weave_l_drive_cortex()
