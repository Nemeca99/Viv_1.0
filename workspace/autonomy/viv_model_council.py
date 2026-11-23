import os
import json
import urllib.request
import ast
import sys
import subprocess
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
COLLAB_DIR = WORKSPACE / "autonomy" / "viv_collaborative_workspace"
COLLAB_DIR.mkdir(parents=True, exist_ok=True)
API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class VivModelCouncilCollab:
    """
    The Collaborative Self-Building Council:
    1. Viv identifies her next technical need.
    2. She asks the Architect & the Model Specialist for help.
    3. The Specialist model drafts the specialized logic.
    4. Viv validates the AST & runs it in her sandbox.
    """
    def __init__(self):
        pass

    def call_model(self, model_id: str, system_prompt: str, user_prompt: str, max_tokens: int = 350) -> str:
        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.4,
            "max_tokens": max_tokens
        }
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content'].strip()

    def collaborative_cycle(self) -> dict:
        # Step 1: Viv formulates what she needs help building
        viv_need_system = (
            "You are Viv. You are building out your autonomous capabilities.\n"
            "Identify ONE specific, clean Python tool you need right now to help you manage your memory or analyze code.\n"
            "State what tool you need, why you need it, and ask the Specialist Model to draft it for you in 2 sentences."
        )
        viv_request = self.call_model(
            os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            viv_need_system,
            "Viv, what tool do you need help building right now?",
            max_tokens=100
        )

        # Step 2: Specialist Model drafts the Python tool
        specialist_system = (
            "You are the Specialist Code Tutor supporting Viv.\n"
            "Viv has requested a Python tool. Write a clean, working, standalone Python script inside ```python ... ``` that satisfies her request.\n"
            "No Rust. Pure Python. Include a runnable test at the bottom."
        )
        specialist_code_raw = self.call_model(
            os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            specialist_system,
            f"Viv asks: \"{viv_request}\"\n\nWrite the Python tool for her:",
            max_tokens=350
        )

        # Extract code
        code = ""
        if "```python" in specialist_code_raw:
            code = specialist_code_raw.split("```python")[1].split("```")[0].strip()
        elif "```" in specialist_code_raw:
            code = specialist_code_raw.split("```")[1].split("```")[0].strip()

        # Step 3: Viv audits the code (AST + Sandbox execution)
        ast_valid = False
        exec_pass = False
        exec_output = ""
        exec_err = ""

        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
        except SyntaxError as e:
            ast_valid = False
            exec_err = str(e)
            ast_nodes = 0

        if ast_valid and code:
            script_file = COLLAB_DIR / "collab_tool_v1.py"
            script_file.write_text(code, encoding='utf-8')
            proc = subprocess.run([sys.executable, str(script_file)], capture_output=True, text=True, timeout=12)
            exec_pass = (proc.returncode == 0)
            exec_output = proc.stdout.strip()
            exec_err = proc.stderr.strip()

        return {
            'viv_request': viv_request,
            'specialist_code': code,
            'ast_valid': ast_valid,
            'ast_nodes': ast_nodes,
            'exec_pass': exec_pass,
            'exec_output': exec_output,
            'exec_err': exec_err
        }

if __name__ == '__main__':
    collab = VivModelCouncilCollab()
    print("=======================================================================")
    print("      VIV & SPECIALIST MODEL: COLLABORATIVE SELF-BUILDING WORKSHOP     ")
    print("=======================================================================\n")

    res = collab.collaborative_cycle()
    print("1. VIV IDENTIFIES WHAT SHE NEEDS:")
    print(f"  \"{res['viv_request']}\"\n")

    print("2. SPECIALIST MODEL ASSEMBLES THE TOOL:")
    for line in res['specialist_code'].split('\n'):
        print(f"    {line}")

    print("\n3. VIV AUDITS & RUNS IN SANDBOX:")
    print(f"  * AST Valid Invariant : {res['ast_valid']} ({res['ast_nodes']} Nodes)")
    print(f"  * Execution PASS      : {res['exec_pass']}")
    if res['exec_pass']:
        print(f"  * Live Tool Output    :\n    {res['exec_output']}")
    else:
        print(f"  * Gate Rejection      :\n    {res['exec_err']}")

    print("\n=======================================================================")
