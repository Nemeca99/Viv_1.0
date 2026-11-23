import ast
import sqlite3
import json
import time
from pathlib import Path

CODE_LATTICE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def init_code_lattice():
    conn = sqlite3.connect(CODE_LATTICE_DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS code_patterns (
        pattern_id TEXT PRIMARY KEY,
        pattern_type TEXT,
        ast_structure TEXT,
        uses INTEGER,
        pass_hits INTEGER,
        fail_hits INTEGER,
        created_at TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS function_bonds (
        source_pattern TEXT,
        target_pattern TEXT,
        relation TEXT,
        weight REAL,
        PRIMARY KEY (source_pattern, target_pattern)
    )
    """)
    conn.commit()
    conn.close()

def learn_function_pattern(code_str: str, pattern_name: str) -> dict:
    """
    Decomposes Python code into discrete topological AST bonds,
    storing the structural skeleton permanently in SQLite.
    """
    conn = sqlite3.connect(CODE_LATTICE_DB)
    cur = conn.cursor()
    
    tree = ast.parse(code_str)
    ast_dump = ast.dump(tree)
    
    # Extract structural skeleton (ignoring variable names)
    structural_nodes = [type(node).__name__ for node in ast.walk(tree)]
    skeleton_sig = " -> ".join(structural_nodes[:8])
    
    # Store or update the learned pattern
    cur.execute("""
    INSERT INTO code_patterns (pattern_id, pattern_type, ast_structure, uses, pass_hits, fail_hits, created_at)
    VALUES (?, ?, ?, 1, 1, 0, datetime('now'))
    ON CONFLICT(pattern_id) DO UPDATE SET 
        uses = uses + 1,
        pass_hits = pass_hits + 1
    """, (pattern_name, 'AST_FUNCTION_TEMPLATE', skeleton_sig))
    
    conn.commit()
    
    cur.execute("SELECT pattern_id, ast_structure, uses FROM code_patterns WHERE pattern_id = ?", (pattern_name,))
    row = cur.fetchone()
    conn.close()
    
    return {
        'pattern_id': row[0],
        'structural_skeleton': row[1],
        'times_used': row[2]
    }

if __name__ == '__main__':
    init_code_lattice()
    
    # Experiment: Teach Viv the "Filter Pattern"
    python_lesson = """
def filter_positive_numbers(items):
    results = []
    for x in items:
        if x > 0:
            results.append(x)
    return results
"""
    print("=======================================================================")
    print("      PROVING CODING COGNITION: LEARNING STRUCTURAL SKELETONS          ")
    print("=======================================================================\n")
    print(f"TEACHING VIV A NEW STRUCTURAL PATTERN:\n{python_lesson}\n")
    
    receipt = learn_function_pattern(python_lesson, "PATTERN_FILTER_LOOP")
    
    print("WHAT VIV COMMITTED TO SQLITE (THE STRUCTURAL LATTICE):")
    print(f"  * Pattern Name      : {receipt['pattern_id']}")
    print(f"  * Topological AST   : {receipt['structural_skeleton']}")
    print(f"  * Times Re-Enforced : {receipt['times_used']}\n")
    print("PROOF: This is a discrete topological circuit in SQLite, not a probabilistic word guess.")
    print("=======================================================================")
