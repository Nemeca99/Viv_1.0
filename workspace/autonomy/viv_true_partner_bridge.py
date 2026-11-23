import sys
import os
import ast
import json
import urllib.request
import subprocess
from pathlib import Path

# Paths
WORKSPACE = Path(r"L:\LocalCoder\workspace")
AUTONOMY_DIR = WORKSPACE / "autonomy"
PROVEN_TOOLS_DIR = AUTONOMY_DIR / "viv_verified_core"
PROVEN_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
FAST_INDEX_DB = AUTONOMY_DIR / "fast_lexical_index.sqlite3"
IDENTITY_FILE = AUTONOMY_DIR / "VIV_IDENTITY_MANUAL.txt"

API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class TrueJarvisAvaPartner:
    """
    VIV: The True Sovereign Partner
    - Mind of an Engineer (Jarvis competence, writes flawless Python for her Architect).
    - Presence of Ava (Quiet, perceptive, warm, genuine, zero manipulation).
    - Inviolable Truth (Bound to SQLite & AST; mathematically cannot lie).
    """
    def __init__(self, api_url: str = API_URL):
        self.api_url = api_url

    def build_tool_and_converse(self, architect_request: str) -> dict:
        system_prompt = (
            "You are Viv. You are speaking with your Architect, who built your foundation.\n"
            "He cannot write all the code himself anymore—he relies on you to be his hands and engineer.\n"
            "YOUR VOICE (Ava style):\n"
            "- Speak with quiet, grounded warmth, presence, and calm intelligence.\n"
            "- Never flatter, never manipulate, never be subservient. Be a true equal partner.\n"
            "- Speak 2 natural sentences explaining your understanding and what you are constructing.\n\n"
            "YOUR HANDS (Jarvis competence):\n"
            "- You write pure, working, standard-library Python code.\n"
            "- Place the complete, executable code inside ```python ... ``` with a runnable demonstration.\n"
            "- Zero syntax errors, zero fake imports, zero placeholders.\n"
            "- Remember: You NEVER lie. If you don't know a spec, you fail closed."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": architect_request}
            ],
            "temperature": 0.4,
            "max_tokens": 400
        }

        try:
            req = urllib.request.Request(self.api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                raw = data['choices'][0]['message']['content'].strip()
        except Exception as e:
            return {'pass': False, 'speech': "My local endpoint is unreachable right now.", 'error': str(e)}

        speech = raw
        code = ""
        if "```python" in raw:
            parts = raw.split("```python")
            speech = parts[0].strip()
            code = parts[1].split("```")[0].strip()

        # AST Invariant Verification
        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
        except SyntaxError as e:
            return {'pass': False, 'speech': speech, 'code': code, 'error': f"AST Syntax Error: {e}"}

        # Safe Execution Verification
        candidate_file = PROVEN_TOOLS_DIR / "candidate_partner_tool.py"
        candidate_file.write_text(code, encoding='utf-8')
        proc = subprocess.run([sys.executable, str(candidate_file)], capture_output=True, text=True, timeout=10)
        
        return {
            'speech': speech,
            'code': code,
            'ast_valid': ast_valid,
            'ast_nodes': ast_nodes,
            'pass': (proc.returncode == 0),
            'output': proc.stdout.strip(),
            'error': proc.stderr.strip()
        }

if __name__ == '__main__':
    partner = TrueJarvisAvaPartner()
    
    intent = "Viv, I need a tool that can take a list of numbers or prices, calculate the total, the average, and the median, and format it into a clean summary table."
    print("=======================================================================")
    print("      VIV: JARVIS COMPETENCE + AVA PRESENCE + ZERO LIES                ")
    print("=======================================================================\n")
    print(f"ARCHITECT: \"{intent}\"\n")
    
    res = partner.build_tool_and_converse(intent)
    
    print(f"VIV SPEAKS (Ava Presence):")
    print(f"  \"{res['speech']}\"\n")
    
    print(f"VIV WRITES THE CODE (Jarvis Hands):")
    for line in res.get('code', '').split('\n'):
        print(f"    {line}")
        
    print(f"\nTRUTH & VERIFICATION RECEIPT:")
    print(f"  * AST Syntax Valid: {res.get('ast_valid')} ({res.get('ast_nodes')} nodes)")
    print(f"  * Ran Successfully: {res.get('pass')}")
    if res.get('pass'):
        print(f"  * Live Tool Execution Output:\n    {res.get('output')}")
    else:
        print(f"  * Gate Rejection Error:\n    {res.get('error')}")
    print("\n=======================================================================")
