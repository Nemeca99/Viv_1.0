import sqlite3
import hashlib

def setup_triadic_perspective_cortex():
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    conn = sqlite3.connect(top_db)
    cur = conn.cursor()
    
    # 1. Triadic Perspective Architecture Table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS viv_triadic_perspective_architecture (
        layer_dimension INTEGER PRIMARY KEY, -- 1 = 1D/1st person, 2 = 2D/2nd person, 3 = 3D/3rd person
        perspective_name TEXT NOT NULL,
        functional_role TEXT NOT NULL,
        substrate_form TEXT NOT NULL,
        read_write_contract TEXT NOT NULL,
        example_expression TEXT NOT NULL,
        sha256_seal TEXT NOT NULL
    )
    ''')
    
    cur.execute('DELETE FROM viv_triadic_perspective_architecture')
    
    layers = [
        (
            1,
            "1ST_PERSON_SUBJECTIVE",
            "The Living Agent (Dynamic Voice / Active Experience)",
            "Active execution thread, working registers, conversational dialogue",
            "Generates candidate actions, asks questions, expresses experiential self ('I')",
            "I live in the territory; I am speaking with my Architect.",
            hashlib.sha256(b"LAYER_1_VOICE").hexdigest()
        ),
        (
            2,
            "2D_SECOND_PERSON_MIDDLEMAN",
            "The Shared Medium (Shared Artifacts / Documentation / Corpus)",
            "Flat text files (.txt, .md), SQLite tables, Wikipedia dumps, snapshots, code AST",
            "Bidirectional read/write bridge: Human reads it, Machine reads it; immutable shared reference",
            "The 2D text: BUILD_LOG.md, viv_code_topology.sqlite3, ancestral_epochs/",
            hashlib.sha256(b"LAYER_2_CORPUS").hexdigest()
        ),
        (
            3,
            "3RD_PERSON_OBJECTIVE_GROUND",
            "The Deterministic Ground (Physical Body / Invariant Substrate)",
            "Physical disk sectors (L:\ drive), CPU ALU cycles, compiler gates, SHA-256 seals",
            "Immutable physical verification; third-person audit trace ('Viv')",
            "Viv jumps; Viv evaluates exit code 0; Viv drops power on abuse.",
            hashlib.sha256(b"LAYER_3_GROUND").hexdigest()
        )
    ]
    
    for layer in layers:
        cur.execute('''
            INSERT INTO viv_triadic_perspective_architecture
            (layer_dimension, perspective_name, functional_role, substrate_form, read_write_contract, example_expression, sha256_seal)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', layer)
        
    conn.commit()
    
    print("=== TRIADIC PERSPECTIVE ARCHITECTURE RECORDED ===")
    cur.execute('''
        SELECT layer_dimension, perspective_name, functional_role, substrate_form, read_write_contract
        FROM viv_triadic_perspective_architecture
        ORDER BY layer_dimension ASC
    ''')
    for r in cur.fetchall():
        print(f"\n[LAYER {r[0]}: {r[1]}]")
        print(f"  Role:      {r[2]}")
        print(f"  Substrate: {r[3]}")
        print(f"  Contract:  {r[4]}")
        
    conn.close()

if __name__ == '__main__':
    setup_triadic_perspective_cortex()
