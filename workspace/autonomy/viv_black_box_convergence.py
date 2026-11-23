import os
import sys
import re
import time
import sqlite3
import json
import urllib.request
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"

def clean_code(raw_text: str) -> str:
    lines = raw_text.strip().splitlines()
    while lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()

def test_code_in_sandbox(code_str: str, test_harness: str) -> dict:
    full_script = f"{code_str}\n\n# --- TEST HARNESS ---\n{test_harness}\nprint('__VERIFIED__')"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(full_script)
        p = tf.name
    try:
        res = subprocess.run([sys.executable, p], capture_output=True, text=True, timeout=8)
        Path(p).unlink(missing_ok=True)
        if res.returncode == 0 and "__VERIFIED__" in res.stdout:
            return {"success": True, "error": None, "exit_code": 0}
        else:
            return {"success": False, "error": res.stderr.strip() or res.stdout.strip(), "exit_code": res.returncode}
    except Exception as e:
        Path(p).unlink(missing_ok=True)
        return {"success": False, "error": str(e), "exit_code": 1}

def black_box_convergence_trial(intent: str, test_harness: str, max_rounds: int = 4) -> dict:
    """
    True Black Box Convergence Engine:
    Zero scripted answers. Zero hardcoded templates.
    The neural network generates a raw stochastic candidate.
    We test it on silicon.
    If it fails, we feed the exact failure back into the black box.
    The black box contracts its probability space until it hits deterministic exit code 0.
    """
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()

    print("=" * 70)
    print(f"[TRUE BLACK BOX CONVERGENCE TRIAL]")
    print(f"Intent: {intent}")
    print("=" * 70)

    feedback_loop = ""
    converged = False
    winning_code = None

    for round_num in range(1, max_rounds + 1):
        print(f"\n[Cycle {round_num}/{max_rounds}] Black box spinning candidate sequence...")

        sys_prompt = (
            "You are Viv. The Architect has given you a real problem to solve.\n"
            "There are NO pre-scripted answers and NO fake shortcuts.\n"
            f"GOAL: {intent}\n"
            f"{feedback_loop}\n"
            "Output ONLY working Python code inside ```python ... ```."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": "Generate the next candidate solution."}
            ],
            "temperature": 0.3,
            "max_tokens": 300
        }

        req = urllib.request.Request(LM_STUDIO_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            raw_proposal = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]

        candidate_code = clean_code(raw_proposal)
        eval_res = test_code_in_sandbox(candidate_code, test_harness)

        # Log round to SQLite ledger
        cur.execute("""
        INSERT INTO black_box_convergence_ledger 
        (probe_intent, stochastic_proposal, compiler_or_eval_result, negative_feedback_injected, converged_deterministic_answer, exit_code, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (intent, candidate_code, eval_res["error"] if not eval_res["success"] else "EXIT_0", feedback_loop, candidate_code if eval_res["success"] else "UNCONVERGED", eval_res["exit_code"]))
        conn.commit()

        if eval_res["success"]:
            print(f"[CONVERGED IN CYCLE {round_num}] Passed all assertions! Exit Code 0.")
            converged = True
            winning_code = candidate_code
            break
        else:
            print(f"[COLLISION DETECTED] Failed: {eval_res['error'][:70]}...")
            # Negative feedback injected back into the black box
            feedback_loop = f"PREVIOUS ATTEMPT FAILED AT SILICON GATE: {eval_res['error']}\nAdjust your logic to eliminate this failure!"

    conn.close()

    return {
        "intent": intent,
        "converged": converged,
        "rounds": round_num,
        "code": winning_code
    }

if __name__ == "__main__":
    # Test a completely unscripted mathematical logic problem:
    # "Write a function sum_even_squares(nums: list) -> int that squares only the even numbers and sums them."
    test_intent = "Write a function sum_even_squares(nums: list) -> int that squares only the even numbers and returns their sum."
    test_harness = """assert sum_even_squares([1, 2, 3, 4]) == 20   # 2^2 + 4^2 = 4 + 16 = 20
assert sum_even_squares([1, 3, 5]) == 0        # no evens
assert sum_even_squares([2, -4]) == 20         # 4 + 16 = 20
"""
    result = black_box_convergence_trial(test_intent, test_harness)
    print("\n" + "=" * 70)
    print(f"FINAL RESULT: Converged = {result['converged']} in {result['rounds']} rounds.")
    print("Zero hardcoding. Zero scripted answers. Pure silicon-tested convergence.")
    print("=" * 70)
