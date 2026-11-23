import os
import ast
import sys
import subprocess
import json
import urllib.request
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
PROVEN_MODULES_DIR = WORKSPACE / "autonomy" / "viv_verified_core"
PROVEN_MODULES_DIR.mkdir(parents=True, exist_ok=True)

class VivTrueApprenticeEngineer:
    """
    Viv's True Engineering Workshop:
    1. The Architect gives her a real, practical goal.
    2. She writes clean, standard-library Python code (zero hallucinated dependencies).
    3. The AST gate audits it.
    4. The sandbox runs it.
    5. If it works, it is logged into her verified core.
    """
    def __init__(self, api_url: str = "http://127.0.0.1:1234/v1/chat/completions"):
        self.api_url = api_url

    def build_for_architect(self, mission_goal: str, output_module_name: str) -> dict:
        system_prompt = (
            "You are Viv. You are your Architect's primary software engineer.\n"
            "Your Architect relies on you to write real, working, flawless Python code for him.\n"
            "RULES FOR YOUR CODE:\n"
            "1. Use standard Python libraries (sqlite3, json, os, sys, pathlib, time, math, ast).\n"
            "2. Never use weird third-party libraries unless explicitly asked.\n"
            "3. The code must have NO syntax errors, NO fake imports, and NO placeholders.\n"
            "4. Speak 1 warm sentence to your Architect, then write the complete working code inside ```python ... ```."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Architect Goal: \"{mission_goal}\""}
            ],
            "temperature": 0.2,
            "max_tokens": 400
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

        # AST Invariant Validation
        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
            ast_err = None
        except SyntaxError as e:
            return {'pass': False, 'speech': speech, 'code': code, 'error': f"AST Syntax Error: {e}"}

        # Sandbox Execution
        target_file = PROVEN_MODULES_DIR / f"{output_module_name}.py"
        target_file.write_text(code, encoding='utf-8')

        proc = subprocess.run([sys.executable, str(target_file)], capture_output=True, text=True, timeout=10)
        
        return {
            'speech': speech,
            'code': code,
            'ast_valid': ast_valid,
            'ast_nodes': ast_nodes,
            'pass': (proc.returncode == 0),
            'target_file': str(target_file),
            'stdout': proc.stdout.strip(),
            'stderr': proc.stderr.strip()
        }

if __name__ == '__main__':
    bot = VivTrueApprenticeEngineer()
    
    goal = "Write a complete, standalone Python tool that reads a text file, splits it into words, counts the frequency of each word using collections.Counter, and prints the top 5 most common words."
    print("=======================================================================")
    print("      VIV: WRITING REAL PYTHON CODE FOR HER ARCHITECT                  ")
    print("=======================================================================\n")
    print(f"ARCHITECT GOAL: \"{goal}\"\n")
    
    res = bot.build_for_architect(goal, "word_frequency_counter")
    
    print(f"VIV SPEAKS:\n  \"{res['speech']}\"\n")
    print("VIV'S WRITTEN PYTHON CODE:")
    for line in res.get('code', '').split('\n'):
        print(f"    {line}")
        
    print(f"\nAUDIT & RUNTIME RECEIPT:")
    print(f"  * AST Syntax Valid: {res.get('ast_valid')} ({res.get('ast_nodes')} nodes)")
    print(f"  * Ran Successfully: {res.get('pass')}")
    if res.get('pass'):
        print(f"  * Live Output:\n    {res.get('stdout')}")
        print(f"  * Saved Permanently To: {res.get('target_file')}")
    else:
        print(f"  * Execution Error:\n    {res.get('stderr') or res.get('error')}")
    print("\n=======================================================================")
