import os
import sys
import re
import time
import sqlite3
import json
import urllib.request
import subprocess
import tempfile
import ast
from datetime import datetime
from pathlib import Path

# Add workspace to path
WORKSPACE_PATH = Path(r"L:\LocalCoder\workspace")
if str(WORKSPACE_PATH) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_PATH))

from autonomy.viv_playground_orchestrator import sanitize_python_code

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
COMPLETIONS_URL = "http://127.0.0.1:1234/v1/completions"

# Force all temp executions strictly to L:\ drive
L_TMP_DIR = WORKSPACE_PATH / "autonomy" / ".tmp"
L_TMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(L_TMP_DIR)

IMPORTS_HEADER = """from __future__ import annotations
import math, sys, re, json, collections
from typing import Optional, List, Dict, Set, Tuple, Any
"""

def clean_code_block(raw_text: str, domain: str) -> str:
    """Extracts strictly fenced code block matching the target domain language."""
    if domain == "PYTHON":
        m = re.search(r"```python\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
        if m:
            raw_text = m.group(1).strip()
        else:
            m_any = re.search(r"```(?:\w+)?\s*(.*?)\s*```", raw_text, re.DOTALL)
            if m_any:
                raw_text = m_any.group(1).strip()
        return sanitize_python_code(raw_text)
    else:  # RUST
        tag = "rust"
        m = re.search(rf"```{tag}\s*(.*?)\s*```", raw_text, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m_any = re.search(r"```(?:\w+)?\s*(.*?)\s*```", raw_text, re.DOTALL)
        if m_any:
            return m_any.group(1).strip()
        lines = raw_text.strip().splitlines()
        while lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

def run_python_trial(code_str: str, test_harness: str) -> dict:
    full_code = f"{code_str}\n\n# --- TEST HARNESS ---\n{test_harness}\nprint('__TEST_PASSED__')"
    with tempfile.NamedTemporaryFile("w", suffix=".py", dir=L_TMP_DIR, delete=False, encoding="utf-8") as tf:
        tf.write(full_code)
        p = tf.name
    try:
        res = subprocess.run([sys.executable, p], capture_output=True, text=True, timeout=8)
        Path(p).unlink(missing_ok=True)
        if res.returncode == 0 and "__TEST_PASSED__" in res.stdout:
            return {"passed": True, "error": None}
        else:
            return {"passed": False, "error": res.stderr.strip() or res.stdout.strip()}
    except Exception as e:
        Path(p).unlink(missing_ok=True)
        return {"passed": False, "error": str(e)}

def run_rust_trial(code_str: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".rs", dir=L_TMP_DIR, delete=False, encoding="utf-8") as tf:
        tf.write(code_str)
        src_p = tf.name
        bin_p = src_p.replace(".rs", ".exe")
    try:
        comp = subprocess.run(["rustc", src_p, "-o", bin_p], capture_output=True, text=True, timeout=10)
        Path(src_p).unlink(missing_ok=True)
        if comp.returncode != 0:
            return {"passed": False, "error": comp.stderr.strip()}
        
        run_res = subprocess.run([bin_p], capture_output=True, text=True, timeout=5)
        Path(bin_p).unlink(missing_ok=True)
        if run_res.returncode == 0 and "FIB_PASS" in run_res.stdout:
            return {"passed": True, "error": None}
        else:
            return {"passed": False, "error": run_res.stderr.strip() or run_res.stdout.strip()}
    except Exception as e:
        Path(src_p).unlink(missing_ok=True)
        if Path(bin_p).exists():
            Path(bin_p).unlink(missing_ok=True)
        return {"passed": False, "error": str(e)}

def extract_header_from_intent(intent: str, domain: str) -> tuple[str, str]:
    if domain == "PYTHON":
        m_fn = re.search(r"(?:Write|Implement)\s+(?:a\s+)?(?:mutually\s+)?(?:recursive\s+)?(?:helper\s+|functions?\s+)([A-Za-z0-9_]+(?:\([^)]*\))?(?:\s*->\s*[A-Za-z0-9_\[\],\s]+?)?)(?:\s+and\b|\s+that\b|\s+which\b|\s+to\b)", intent)
        if m_fn:
            sig = m_fn.group(1).strip()
            if "(" not in sig:
                sig = f"{sig}(*args, **kwargs)"
            return f"def {sig}:\n    \"\"\"{intent.strip()}\"\"\"\n", "def"
        m_cls = re.search(r"(?:Write|Implement)\s+(?:a\s+)?class\s+([A-Za-z0-9_]+)", intent)
        if m_cls:
            cls_name = m_cls.group(1).strip()
            return f"class {cls_name}:\n    \"\"\"{intent.strip()}\"\"\"\n", "class"
    return "", ""

def propose_solution(challenge_prompt: str, domain: str, previous_error: str = None) -> str:
    err_context = (
        f"\n# CRITICAL: Your previous code failed with error:\n# {previous_error}\n# Fix the logic so all assertions pass!\n"
        if previous_error else ""
    )
    
    if domain == "PYTHON":
        primed_prefix, kind = extract_header_from_intent(challenge_prompt, domain)
        prompt = f'''"""
Task: {challenge_prompt}
Write a clean, self-contained Python 3 solution using standard library only.
{err_context}"""
{IMPORTS_HEADER}
{primed_prefix}'''

        payload = {
            "model": "deepseek-coder-6.7b-base",
            "prompt": prompt,
            "temperature": 0.2,
            "max_tokens": 700,
            "stop": ["<|EOT|>", "<|end_of_sentence|>", "\n# ===", "\n\n\n\nclass "]
        }
        req = urllib.request.Request(COMPLETIONS_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
            raw = data["choices"][0]["text"]
            clean_raw = re.split(r"\n(?:if __name__|def test_|def main\b)", raw)[0]
            full_code = f"{IMPORTS_HEADER}\n{primed_prefix}{clean_raw}"
            return sanitize_python_code(full_code)
    else:  # RUST
        sys_prompt = f"Write a working Rust solution for: {challenge_prompt}\nOutput ONLY the code inside ```rust ... ```."
        payload = {
            "model": "deepseek-coder-6.7b-base",
            "messages": [{"role": "user", "content": sys_prompt}],
            "temperature": 0.2,
            "max_tokens": 350
        }
        req = urllib.request.Request(LM_STUDIO_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

def execute_autonomous_curriculum_cycle(retry_failed: bool = False) -> bool:
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()

    if retry_failed:
        cur.execute("UPDATE autonomous_curriculum_queue SET status = 'PENDING', attempts = 0 WHERE status = 'FAILED_MAX_ATTEMPTS'")
        conn.commit()

    cur.execute("SELECT curriculum_id, domain, challenge_intent, test_harness_code, attempts FROM autonomous_curriculum_queue WHERE status = 'PENDING' ORDER BY curriculum_id ASC LIMIT 1")
    row = cur.fetchone()
    
    if not row:
        print("[+] All curriculum challenges graduated! Queue empty.")
        conn.close()
        return False

    cid, domain, intent, harness, attempts = row
    print("=" * 70)
    print(f"[VIV AUTONOMOUS EVOLUTION CYCLE] [{domain}] {cid}")
    print(f"Goal: {intent}")
    print("=" * 70)

    # Max 3 learning attempts before saving negative evidence
    error_msg = None
    success = False
    winning_code = None

    for attempt in range(1, 4):
        print(f"\n[Attempt {attempt}/3] Viv is formulating candidate AST solution...")
        proposal = propose_solution(intent, domain, error_msg)
        
        if domain == "PYTHON":
            code = clean_code_block(proposal, "PYTHON")
            trial = run_python_trial(code, harness)
        else:  # RUST
            code = clean_code_block(proposal, "RUST")
            trial = run_rust_trial(code)

        if trial["passed"]:
            print(f"[PASS] TRIAL PASSED ON ATTEMPT {attempt}!")
            success = True
            winning_code = code
            break
        else:
            print(f"[FAIL] Execution failed: {trial['error'][:60]}...")
            error_msg = trial["error"]

    if success:
        # Graduate to permanent database
        prim_id = f"AUTONOMOUS_{cid}"
        cur.execute("""
        INSERT OR REPLACE INTO verified_code_primitives 
        (primitive_id, intent_description, ast_skeleton, verified_python_code, test_harness_code, execution_status, pass_count, fail_count, registered_at)
        VALUES (?, ?, 'AUTONOMOUS_GRADUATE', ?, ?, 'VERIFIED_GRADUATE', 1, ?, datetime('now'))
        """, (prim_id, intent, winning_code, harness, attempt - 1))

        cur.execute("UPDATE autonomous_curriculum_queue SET status = 'GRADUATED', graduated_primitive_id = ?, attempts = ? WHERE curriculum_id = ?",
                    (prim_id, attempt, cid))
        conn.commit()
        print(f"\n[GRADUATED] '{prim_id}' is now permanently stored in SQLite on SSD.")

        if domain == "PYTHON":
            try:
                from autonomy.viv_code_neuron_engine import VivCodeNeuronLearner
                VivCodeNeuronLearner.learn_and_carve_code(prim_id, winning_code, harness)
                print(f"[NEURONS] Carved code neurons & synapses into viv_code_topology for {prim_id}.")
            except Exception as ne_exc:
                print(f"[WARN] Code neuron extraction: {ne_exc}")
    else:
        # Record negative evidence
        cur.execute("UPDATE autonomous_curriculum_queue SET status = 'FAILED_MAX_ATTEMPTS', attempts = 3 WHERE curriculum_id = ?", (cid,))
        cur.execute("""
        INSERT OR REPLACE INTO negative_evidence_ledger (failure_id, attempted_action, error_signature, violated_boundary, sn_penalty, lesson_learned, registered_at)
        VALUES (?, ?, ?, 'Curriculum Difficulty Boundary', 0.10, 'Failed test harness 3 times. Requires Architect decomposition.', datetime('now'))
        """, (f"FAIL_{cid}", intent, error_msg[:100] if error_msg else "Unknown error"))
        conn.commit()
        print(f"\n[FAILED] Negative evidence recorded in SQLite. Circuit closed gracefully.")

    conn.close()
    return success

def run_continuous_curriculum(max_cycles: int = 10, retry_failed: bool = True):
    print(f"[*] Starting Viv Autonomous Curriculum Runner (max_cycles={max_cycles})...")
    conn = sqlite3.connect(CODE_DB)
    if retry_failed:
        conn.execute("UPDATE autonomous_curriculum_queue SET status = 'PENDING', attempts = 0 WHERE status = 'FAILED_MAX_ATTEMPTS'")
        conn.commit()
    conn.close()

    cycles_completed = 0
    while cycles_completed < max_cycles:
        conn = sqlite3.connect(CODE_DB)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM autonomous_curriculum_queue WHERE status = 'PENDING'")
        pending_count = cur.fetchone()[0]
        conn.close()

        if pending_count == 0:
            print("[+] No pending curriculum items remain. All lessons graduated!")
            break

        print(f"\n>>> Cycle {cycles_completed + 1} | Pending Lessons: {pending_count} <<<")
        success = execute_autonomous_curriculum_cycle(retry_failed=False)
        cycles_completed += 1
        if not success:
            print("[!] Evolution paused on failed curriculum item. Retrying or awaiting Architect guidance.")
            break
        time.sleep(1)

    print(f"\n[+] Curriculum batch complete. Cycles executed: {cycles_completed}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Viv Autonomous Curriculum Evolution Runner")
    parser.add_argument("--loop", action="store_true", help="Run continuously through all pending lessons")
    parser.add_argument("--retry-failed", action="store_true", default=True, help="Reset failed items to PENDING")
    parser.add_argument("--max-cycles", type=int, default=10, help="Max cycles to run in loop mode")
    args = parser.parse_args()

    if args.loop:
        run_continuous_curriculum(max_cycles=args.max_cycles, retry_failed=args.retry_failed)
    else:
        execute_autonomous_curriculum_cycle(retry_failed=args.retry_failed)
