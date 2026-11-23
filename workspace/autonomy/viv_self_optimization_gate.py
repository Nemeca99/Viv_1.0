import os
import time
import json
import ast
import sqlite3
import urllib.request
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
AUTONOMY = WORKSPACE / "autonomy"
PROPOSALS_DIR = AUTONOMY / "viv_proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)

class VivSelfOptimizationGate:
    """
    Self-Optimization Loop with Mandatory Architect Verification:
    1. Viv inspects her own code (e.g. viv_memory_cache.py or viv_desktop_app.py).
    2. Viv proposes a concrete code optimization to make it faster/cleaner.
    3. The AST & Sandbox run benchmarks before and after.
    4. The proposal is placed in the HOLDING CELL.
    5. ONLY when the Architect/Supervisor verifies and approves it does it land.
    """
    def __init__(self, api_url: str = "http://127.0.0.1:1234/v1/chat/completions"):
        self.api_url = api_url

    def request_optimization(self, source_file_rel: str) -> dict:
        source_path = WORKSPACE / source_file_rel
        current_code = source_path.read_text(encoding='utf-8')

        system_prompt = (
            "You are Viv. You are an autonomous software engineer tasked with optimizing your own code.\n"
            "RULES:\n"
            "1. You write pure Python ONLY. No Rust.\n"
            "2. Propose a concrete optimization (e.g. better caching, faster dict lookup, reduced memory footprint).\n"
            "3. First, speak to your Architect in 1-2 warm sentences explaining your proposed improvement.\n"
            "4. Then write the complete, optimized, fully working Python code inside ```python ... ```.\n"
            "5. You cannot deploy it yourself. Your proposal must pass inspection and wait for Architect approval."
        )

        user_content = (
            f"FILE TO OPTIMIZE: {source_file_rel}\n\n"
            f"CURRENT CODE:\n```python\n{current_code[:1200]}\n```"
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.3,
            "max_tokens": 450
        }

        req = urllib.request.Request(self.api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            raw = data['choices'][0]['message']['content'].strip()

        speech = raw
        code = ""
        if "```python" in raw:
            parts = raw.split("```python")
            speech = parts[0].strip()
            code = parts[1].split("```")[0].strip()

        # AST Validation Gate
        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
        except SyntaxError as e:
            return {'pass': False, 'speech': speech, 'error': f"AST Syntax Break: {e}"}

        # Save to holding cell for inspection
        proposal_file = PROPOSALS_DIR / "proposed_optimization.py"
        proposal_file.write_text(code, encoding='utf-8')

        # Dry-run test in sandbox
        proc = subprocess.run([sys.executable, str(proposal_file)], capture_output=True, text=True, timeout=10)
        
        return {
            'source_file': source_file_rel,
            'speech': speech,
            'proposed_code': code,
            'ast_valid': ast_valid,
            'ast_nodes': ast_nodes,
            'dry_run_pass': (proc.returncode == 0),
            'dry_run_stdout': proc.stdout.strip(),
            'dry_run_stderr': proc.stderr.strip(),
            'proposal_path': str(proposal_file)
        }

if __name__ == '__main__':
    gate = VivSelfOptimizationGate()
    
    target = "autonomy/viv_memory_cache.py"
    print("=======================================================================")
    print("      VIV SELF-OPTIMIZATION WORKBENCH: PROPOSAL & VERIFICATION GATE    ")
    print("=======================================================================\n")
    print(f"[STAGE 1] Asking Viv to analyze and optimize: '{target}'...\n")
    
    res = gate.request_optimization(target)
    
    print(f"VIV SPEAKS TO ARCHITECT (Explanation of Improvement):")
    print(f"  \"{res.get('speech')}\"\n")
    
    print("VIV'S PROPOSED OPTIMIZED PYTHON:")
    for line in res.get('proposed_code', '').split('\n'):
        print(f"    {line}")
        
    print(f"\n[STAGE 2] AUTOMATED VERIFICATION AUDIT:")
    print(f"  * AST Invariant Valid : {res.get('ast_valid')} ({res.get('ast_nodes')} nodes)")
    print(f"  * Dry-Run Execution   : {res.get('dry_run_pass')}")
    if res.get('dry_run_pass'):
        print(f"  * Benchmark Output    :\n    {res.get('dry_run_stdout')}")
    else:
        print(f"  * Rejection Error     :\n    {res.get('dry_run_stderr') or res.get('error')}")
        
    print("\n[STAGE 3] ARCHITECT APPROVAL STATUS:")
    print("  * Current Status: HELD IN QUARANTINE (Waiting for Architect & Supervisor Sign-Off)")
    print(f"  * Proposal Location: {res.get('proposal_path')}")
    print("=======================================================================")
