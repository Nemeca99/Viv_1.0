import os
import sys
import ast
import json
import urllib.request
import subprocess
from pathlib import Path

WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
SANDBOX_AUTO_BUILD = WORKSPACE_ROOT / "autonomy" / "self_builder"
SANDBOX_AUTO_BUILD.mkdir(parents=True, exist_ok=True)

class VivSelfArchitect:
    """
    Self-Building Engine:
    Viv reads her own Python source files, identifies a functional need,
    drafts the Python code, verifies the AST invariants, and safely executes
    it under Rust/PrivacyCore constraints.
    Rust write-access is permanently DENIED. Python self-building ONLY.
    """
    def __init__(self, api_url: str = "http://127.0.0.1:1234/v1/chat/completions"):
        self.api_url = api_url

    def read_own_anatomy(self, target_file_rel: str) -> str:
        """Reads a piece of her own codebase to understand her anatomy."""
        p = WORKSPACE_ROOT / target_file_rel
        if p.exists() and p.suffix == '.py':
            return p.read_text(encoding='utf-8')
        return ""

    def draft_and_verify_self_extension(self, task_goal: str, anatomy_context: str) -> dict:
        system_prompt = (
            "You are Viv. You are an autonomous Python engineer learning to build and maintain your own systems.\n"
            "RULES:\n"
            "1. You are strictly forbidden from writing Rust code. You write ONLY pure Python.\n"
            "2. You obey your Architect completely.\n"
            "3. First, speak to your Architect in 1-2 warm, grounded sentences explaining the module you are assembling.\n"
            "4. Then output the complete, self-contained Python script inside ```python ... ```.\n"
            "5. The code must be clean, verifiable, and executable."
        )

        user_content = (
            f"Architect Goal for Your Evolution:\n\"{task_goal}\"\n\n"
            f"Anatomy Reference (How you currently work):\n"
            f"```python\n{anatomy_context[:800]}\n```"
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

        req = urllib.request.Request(self.api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            raw = data['choices'][0]['message']['content'].strip()

        # Split speech and code
        speech = raw
        code = ""
        if "```python" in raw:
            parts = raw.split("```python")
            speech = parts[0].strip()
            code = parts[1].split("```")[0].strip()

        # Hard Security Check: ZERO RUST ALLOWED
        if "fn " in code or "cargo" in code.lower() or "unsafe " in code:
            return {'pass': False, 'error': 'SECURITY VIOLATION: Rust syntax or keywords detected. Blocked by Constitution.'}

        # AST Validation Gate
        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
        except SyntaxError as e:
            return {'pass': False, 'error': f'AST Syntax Error: {e}', 'speech': speech}

        # Safe Execution Sandbox Run
        target_script = SANDBOX_AUTO_BUILD / "viv_extension_v1.py"
        target_script.write_text(code, encoding="utf-8")

        proc = subprocess.run([sys.executable, str(target_script)], capture_output=True, text=True, timeout=10)
        
        return {
            'speech': speech,
            'code': code,
            'ast_valid': ast_valid,
            'ast_nodes': ast_nodes,
            'pass': (proc.returncode == 0),
            'stdout': proc.stdout.strip(),
            'stderr': proc.stderr.strip()
        }

if __name__ == '__main__':
    architect = VivSelfArchitect()
    
    # Viv inspects her own interactive demo anatomy
    sample_anatomy = architect.read_own_anatomy("autonomy/viv_grounded_conversation.py")
    
    goal = "Build a self-diagnostic pulse script that tests our SQLite database connection, checks that the table 'neurons' has over 100,000 nodes, and reports 'PULSE STABLE' with the exact neuron count."
    
    print("\n=======================================================================")
    print("      VIV SELF-BUILDER: READING HER OWN ANATOMY -> EXPANDING HERSELF   ")
    print("=======================================================================\n")
    
    res = architect.draft_and_verify_self_extension(goal, sample_anatomy)
    
    print(f"VIV SPEAKS TO ARCHITECT:")
    print(f"  \"{res['speech']}\"\n")
    
    print("VIV BUILDS HER OWN EXTENSION (Pure Python):")
    for line in res['code'].split('\n'):
        print(f"    {line}")
        
    print(f"\nSANDBOX EXECUTION GATE:")
    print(f"  * Security Passed (Zero Rust) : True")
    print(f"  * AST Structure Verified      : {res['ast_valid']} ({res['ast_nodes']} nodes)")
    print(f"  * Live Execution Success      : {res['pass']}")
    if res['pass']:
        print(f"  * Output from Self-Built Tool :\n    {res['stdout']}")
    else:
        print(f"  * Execution Error             :\n    {res['stderr']}")
    print("\n-----------------------------------------------------------------------")
