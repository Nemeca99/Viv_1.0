import os
import ast
import json
import sqlite3
import urllib.request
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
AUTONOMY = WORKSPACE / "autonomy"
VIV_VERIFIED_DIR = AUTONOMY / "viv_native_rebuild"
VIV_VERIFIED_DIR.mkdir(parents=True, exist_ok=True)
SANDBOX_DIR = AUTONOMY / "sandbox"

FAST_INDEX_DB = AUTONOMY / "fast_lexical_index.sqlite3"
API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class AdversarialRedTeamCoder:
    """
    Strict Adversarial Red-Team Engine:
    1. Syntax AST is NOT enough.
    2. Code MUST be a complete standalone class/module.
    3. Code MUST pass a live Functional Assertion Suite (real data, real queries, real output).
    4. If it fails, the exact stack trace feeds back into a correction loop until RATIFIED.
    """
    def __init__(self):
        pass

    def call_model(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 500
        }
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content'].strip()

    def run_adversarial_repair_cycle(self, mission: str, test_assertions_code: str, max_attempts: int = 3) -> dict:
        print("=======================================================================")
        print("      ADVERSARIAL RED-TEAM REPAIR ENGINE: ZERO FAKE CODE ALLOWED       ")
        print("=======================================================================\n")
        print(f"MISSION: {mission}\n")

        system_prompt = (
            "You are Viv. You are a precise, rigorous Python software engineer.\n"
            "CRITICAL REQUIREMENTS:\n"
            "1. Output a COMPLETE, self-contained Python script inside ```python ... ```.\n"
            "2. Define all classes, imports, and methods fully. Never write partial snippets or fragments.\n"
            "3. In SQLite queries, ALWAYS bind parameters cleanly as a tuple, e.g. `(w,)` or `(word.lower(),)`. NEVER use '?' * len(w).\n"
            "4. Your code will be subjected to an adversarial unit test. It must pass all assertions without crashing."
        )

        current_prompt = f"Write the complete module to solve this mission:\n\"{mission}\""
        error_context = ""

        for attempt in range(1, max_attempts + 1):
            print(f"[RED-TEAM ATTEMPT #{attempt}] Generating candidate implementation...")
            
            prompt_with_err = current_prompt
            if error_context:
                prompt_with_err += f"\n\nYOUR PREVIOUS ATTEMPT FAILED THE TEST GATE:\n{error_context}\nFix the exact bug and return the complete corrected code."

            raw_reply = self.call_model(system_prompt, prompt_with_err)
            
            # Extract code
            code = ""
            if "```python" in raw_reply:
                code = raw_reply.split("```python")[1].split("```")[0].strip()
            elif "```" in raw_reply:
                code = raw_reply.split("```")[1].split("```")[0].strip()

            # 1. AST Validation
            try:
                tree = ast.parse(code)
                ast_valid = True
            except SyntaxError as e:
                print(f"  [GATE 1: AST SYNTAX] FAILED: {e}")
                error_context = f"SyntaxError: {e}"
                continue

            print(f"  [GATE 1: AST SYNTAX] PASSED ({len(list(ast.walk(tree)))} AST Nodes)")

            # 2. Functional Test Harness Injection
            # We append the strict adversarial assertion suite to the bottom of the candidate code
            full_test_script = code + "\n\n# ADVERSARIAL TEST HARNESS\n" + test_assertions_code
            
            test_file = SANDBOX_DIR / "adversarial_test_run.py"
            test_file.write_text(full_test_script, encoding='utf-8')

            # 3. Execution in Sandbox
            proc = subprocess.run([sys.executable, str(test_file)], capture_output=True, text=True, timeout=12)

            if proc.returncode == 0:
                print("  [GATE 2: ADVERSARIAL RUNTIME TEST] ALL ASSERTIONS PASSED! 100% RATIFIED.\n")
                print("VERIFIED LIVE OUTPUT:\n" + proc.stdout.strip())
                
                # Save to production
                final_path = VIV_VERIFIED_DIR / "viv_lexical_cortex_verified.py"
                final_path.write_text(code, encoding='utf-8')
                
                return {
                    'ratified': True,
                    'attempts': attempt,
                    'code': code,
                    'file': str(final_path),
                    'output': proc.stdout.strip()
                }
            else:
                stderr_clean = proc.stderr.strip()
                print(f"  [GATE 2: ADVERSARIAL RUNTIME TEST] FAILED:")
                print(f"    {stderr_clean[:300]}")
                error_context = stderr_clean
                time.sleep(1)

        print("\n[RESULT] FAILED TO PASS RED-TEAM GATE AFTER ALL ATTEMPTS.")
        return {'ratified': False, 'error': error_context}

if __name__ == '__main__':
    redteam = AdversarialRedTeamCoder()

    mission = (
        "Create a standalone class `VivLexicalCortex` that connects to "
        r"'L:/LocalCoder/workspace/autonomy/fast_lexical_index.sqlite3'. "
        "It must maintain an internal `self.ram_cache` dictionary. "
        "The method `lookup(word: str)` must check RAM first. If missing, it queries SQLite "
        "using `WHERE word = ?` with parameter `(word.lower(),)`, saves the result to `self.ram_cache`, "
        "and returns a tuple `(token_id, spelling, observations)` or `None` if not found."
    )

    test_harness = """
cortex = VivLexicalCortex()
res_the = cortex.lookup('the')
assert res_the is not None, "Failed to find 'the' in fast_lexical_index.sqlite3!"
token_id, spelling, observations = res_the
assert token_id == 6613, f"Expected token 6613 for 'the', got {token_id}"
assert spelling == "T-H-E", f"Expected spelling T-H-E, got {spelling}"
assert observations > 100, f"Expected >100 observations, got {observations}"

# Test RAM cache hit
res_cached = cortex.lookup('the')
assert res_cached == res_the, "Cached lookup does not match direct lookup!"

# Test non-existent word fails closed
assert cortex.lookup('xyznonexistentword99') is None, "Non-existent word must return None!"

print("[HARNESS SUCCESS] 5/5 Strict Adversarial Assertions Passed: Token 6613 verified, RAM cache verified, Fail-closed verified.")
"""

    res = redteam.run_adversarial_repair_cycle(mission, test_harness)
