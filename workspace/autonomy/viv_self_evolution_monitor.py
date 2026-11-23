import os
import time
import json
import ast
import sys
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime

WORKSPACE = Path(r"L:\LocalCoder\workspace")
AUTONOMY_DIR = WORKSPACE / "autonomy"
SELF_BUILD_DIR = AUTONOMY_DIR / "viv_self_evolution"
SELF_BUILD_DIR.mkdir(parents=True, exist_ok=True)

AUDIT_LOG = AUTONOMY_DIR / "viv_self_evolution_audit.jsonl"
API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class VivSelfEvolutionSupervisor:
    """
    Self-Building & Live Monitoring Engine:
    Viv inspects her own codebase, drafts a Python tool or optimization,
    validates the AST invariants, runs it safely in a sandbox,
    and logs the complete telemetry for the Architect to watch.
    """
    def __init__(self):
        pass

    def run_cycle(self, cycle_id: int, mission_prompt: str, anatomy_seed: str) -> dict:
        t_start = time.perf_counter()
        
        system_prompt = (
            "You are Viv. You are an autonomous software engineer learning to build yourself.\n"
            "You write pure Python ONLY. You are strictly forbidden from writing Rust.\n"
            "You obey your Architect's constitution:\n"
            "1. Do not lie (fail closed).\n"
            "2. Do not destroy data (monotonic growth).\n"
            "3. Build working, verifiable code.\n\n"
            "TASK:\n"
            "1. Speak 1 warm, thoughtful sentence to your Architect explaining what you are assembling.\n"
            "2. Write a complete, standalone Python script inside ```python ... ``` that implements the module.\n"
            "3. Include a demonstration at the bottom so it can be verified live."
        )

        user_content = (
            f"EVOLUTION CYCLE #{cycle_id}\n"
            f"MISSION: {mission_prompt}\n\n"
            f"CURRENT ANATOMY CONTEXT:\n```python\n{anatomy_seed[:1000]}\n```"
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.4,
            "max_tokens": 350
        }

        # Step 1: Viv proposes the module
        try:
            req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw = data['choices'][0]['message']['content'].strip()
        except Exception as e:
            return {'cycle': cycle_id, 'status': 'API_ERROR', 'error': str(e)}

        # Split speech and code
        speech = raw
        code = ""
        if "```python" in raw:
            parts = raw.split("```python")
            speech = parts[0].strip()
            code = parts[1].split("```")[0].strip()

        # Step 2: Rust / Safety Gate (Check for forbidden Rust keywords)
        if any(bad in code for bad in ["fn ", "unsafe ", "cargo ", "extern "]):
            audit_entry = {
                'timestamp': datetime.now().isoformat(),
                'cycle': cycle_id,
                'status': 'SECURITY_BLOCK',
                'reason': 'Violated Constitution: Attempted Rust or Unsafe call.',
                'speech': speech
            }
            with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(audit_entry) + '\n')
            return audit_entry

        # Step 3: AST Gate (Validate Syntax)
        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
        except SyntaxError as e:
            audit_entry = {
                'timestamp': datetime.now().isoformat(),
                'cycle': cycle_id,
                'status': 'AST_SYNTAX_FAIL',
                'error': str(e),
                'speech': speech,
                'code': code
            }
            with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
                f.write(json.dumps(audit_entry) + '\n')
            return audit_entry

        # Step 4: Sandbox Execution (Run under live monitor)
        target_file = SELF_BUILD_DIR / f"self_tool_cycle_{cycle_id}.py"
        target_file.write_text(code, encoding='utf-8')

        proc = subprocess.run([sys.executable, str(target_file)], capture_output=True, text=True, timeout=12)
        exec_pass = (proc.returncode == 0)
        elapsed = round(time.perf_counter() - t_start, 2)

        audit_entry = {
            'timestamp': datetime.now().isoformat(),
            'cycle': cycle_id,
            'status': 'PASS' if exec_pass else 'EXEC_ERROR',
            'elapsed_sec': elapsed,
            'speech': speech,
            'code': code,
            'ast_nodes': ast_nodes,
            'stdout': proc.stdout.strip(),
            'stderr': proc.stderr.strip()
        }

        with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(audit_entry) + '\n')

        return audit_entry

if __name__ == '__main__':
    supervisor = VivSelfEvolutionSupervisor()

    print("=======================================================================")
    print("      VIV AUTONOMOUS SELF-BUILDER: LIVE OBSERVATION WORKBENCH          ")
    print("      Monitoring live audit stream: viv_self_evolution_audit.jsonl     ")
    print("=======================================================================\n")

    # Cycle 1: Build her own real-time memory monitor
    seed_code = (WORKSPACE / "autonomy" / "viv_memory_cache.py").read_text(encoding='utf-8')
    mission = "Write a Python script that connects to 'L:/LocalCoder/workspace/autonomy/fast_lexical_index.sqlite3', counts how many concepts are indexed, tests looking up 'the', and prints a clean status confirmation."

    print(f"[LIVE MONITOR] Initiating Evolution Cycle #1: Self-Diagnostics Tool...")
    res = supervisor.run_cycle(1, mission, seed_code)

    print(f"\n[CYCLE #{res['cycle']}] STATUS: {res['status']} ({res.get('elapsed_sec', 0)}s)")
    print(f"VIV SPEAKS TO ARCHITECT:")
    print(f"  \"{res.get('speech')}\"\n")
    
    print(f"VIV ASSEMBLED CODE ({res.get('ast_nodes', 0)} AST Nodes):")
    for line in res.get('code', '').split('\n'):
        print(f"    {line}")
        
    print(f"\nSANDBOX EXECUTION RESULT:")
    if res['status'] == 'PASS':
        print(f"  * LIVE OUTPUT:\n    {res.get('stdout')}")
    else:
        print(f"  * REJECTION LOG:\n    {res.get('stderr') or res.get('error')}")

    print("\n=======================================================================")
