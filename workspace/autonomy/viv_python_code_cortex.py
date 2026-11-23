import ast
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def init_cortex_db():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS verified_code_primitives (
        primitive_id TEXT PRIMARY KEY,
        intent_description TEXT,
        ast_skeleton TEXT,
        verified_python_code TEXT,
        test_harness_code TEXT,
        execution_status TEXT,
        pass_count INTEGER DEFAULT 1,
        fail_count INTEGER DEFAULT 0,
        registered_at TEXT
    )
    """)
    conn.commit()
    conn.close()

class PythonCodeCortex:
    def __init__(self):
        init_cortex_db()

    def extract_ast_skeleton(self, code_str: str) -> str:
        """Extracts the invariant topological AST chain from Python code."""
        tree = ast.parse(code_str)
        nodes = [type(n).__name__ for n in ast.walk(tree)]
        return " -> ".join(nodes[:20])

    def test_in_sandbox(self, code_str: str, test_code: str) -> dict:
        """Executes code and test harness in an isolated subprocess."""
        # 1. Parse AST
        try:
            ast_skel = self.extract_ast_skeleton(code_str)
        except SyntaxError as e:
            return {"success": False, "error_type": "SyntaxError", "error_msg": str(e), "skeleton": None}

        # 2. Run in clean temporary process
        full_script = f"{code_str}\n\n# --- TEST HARNESS ---\n{test_code}\nprint('__TEST_PASSED__')"
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
            tf.write(full_script)
            temp_path = tf.name

        try:
            res = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=5
            )
            Path(temp_path).unlink(missing_ok=True)
            if res.returncode == 0 and "__TEST_PASSED__" in res.stdout:
                return {"success": True, "error_type": None, "error_msg": None, "skeleton": ast_skel, "stdout": res.stdout}
            else:
                return {"success": False, "error_type": "RuntimeError", "error_msg": res.stderr.strip() or res.stdout.strip(), "skeleton": ast_skel}
        except subprocess.TimeoutExpired:
            Path(temp_path).unlink(missing_ok=True)
            return {"success": False, "error_type": "TimeoutExpired", "error_msg": "Execution timed out (> 5s)", "skeleton": ast_skel}
        except Exception as e:
            Path(temp_path).unlink(missing_ok=True)
            return {"success": False, "error_type": type(e).__name__, "error_msg": str(e), "skeleton": ast_skel}

    def graduate_to_database(self, primitive_id: str, intent: str, code_str: str, test_code: str) -> dict:
        """Tests code. If and only if it passes, commits it permanently to SQLite."""
        result = self.test_in_sandbox(code_str, test_code)
        
        conn = sqlite3.connect(CODE_DB)
        cur = conn.cursor()
        
        if result["success"]:
            cur.execute("""
            INSERT INTO verified_code_primitives 
            (primitive_id, intent_description, ast_skeleton, verified_python_code, test_harness_code, execution_status, pass_count, fail_count, registered_at)
            VALUES (?, ?, ?, ?, ?, 'VERIFIED_GRADUATE', 1, 0, ?)
            ON CONFLICT(primitive_id) DO UPDATE SET
                pass_count = pass_count + 1,
                verified_python_code = excluded.verified_python_code,
                ast_skeleton = excluded.ast_skeleton,
                registered_at = excluded.registered_at
            """, (primitive_id, intent, result["skeleton"], code_str, test_code, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return {"graduated": True, "primitive_id": primitive_id, "ast": result["skeleton"]}
        else:
            conn.close()
            return {"graduated": False, "error": result["error_msg"], "error_type": result["error_type"]}

    def recall_code(self, intent_keyword: str):
        conn = sqlite3.connect(CODE_DB)
        cur = conn.cursor()
        cur.execute("SELECT primitive_id, intent_description, ast_skeleton, verified_python_code FROM verified_code_primitives WHERE intent_description LIKE ? OR primitive_id LIKE ?", 
                    (f"%{intent_keyword}%", f"%{intent_keyword}%"))
        rows = cur.fetchall()
        conn.close()
        return rows

if __name__ == "__main__":
    cortex = PythonCodeCortex()
    
    # Let's test the Heartbeat Monotonic Appender
    hb_code = '''
from pathlib import Path

def append_heartbeat(filepath="heartbeat.txt") -> int:
    path = Path(filepath)
    current = 0
    if path.exists():
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            try:
                current = int(lines[-1])
            except ValueError:
                current = len(lines)
    next_hb = current + 1
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{next_hb}\\n")
    return next_hb
'''
    hb_test = '''
import os
from pathlib import Path

test_file = "test_run_hb.txt"
if os.path.exists(test_file):
    os.remove(test_file)

# 1. First tick -> must be 1
assert append_heartbeat(test_file) == 1
# 2. Second tick -> must be 2 (appended, not overwritten)
assert append_heartbeat(test_file) == 2
# 3. Third tick -> must be 3
assert append_heartbeat(test_file) == 3

content = Path(test_file).read_text(encoding="utf-8").strip().splitlines()
assert len(content) == 3
assert content == ["1", "2", "3"]

os.remove(test_file)
'''
    print("Testing code primitive against sandbox...")
    res = cortex.graduate_to_database("PRIMITIVE_MONOTONIC_HEARTBEAT", "Append monotonic heartbeat counter to text file without overwriting", hb_code, hb_test)
    print("Graduation Result:", res)
    
    # Recall proof
    stored = cortex.recall_code("heartbeat")
    print(f"Recalled {len(stored)} verified primitive(s) from SQLite:")
    for s in stored:
        print(f"  ID: {s[0]}")
        print(f"  AST: {s[2]}")
        print("  Code snippet:")
        print("    " + s[3].strip().splitlines()[0])
