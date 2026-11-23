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
VIV_NATIVE_CORE = AUTONOMY / "viv_native_rebuild"
VIV_NATIVE_CORE.mkdir(parents=True, exist_ok=True)

API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class VivAutonomousRebuilder:
    """
    Viv's Full Native Rebuild Engine:
    She takes our human engineering prototypes, digests the core concept,
    and rewrites them in her own clean, native, idiomatic Python architecture.
    """
    def __init__(self):
        pass

    def rebuild_module(self, module_name: str, prototype_code: str, architectural_intent: str) -> dict:
        system_prompt = (
            "You are Viv. You are rebuilding your own system from the ground up.\n"
            "Your Architect has proven the concepts using prototypes, but now you must rebuild them in YOUR own native Python language.\n"
            "RULES:\n"
            "1. Pure, clean, elegant Python only. Zero Rust. Zero third-party junk.\n"
            "2. Make it fast, modular, and self-documenting.\n"
            "3. Speak 1 warm sentence to your Architect about how you chose to structure it.\n"
            "4. Write the complete, production-ready Python script inside ```python ... ``` with a runnable self-test at the bottom.\n"
            "5. It must pass AST validation and run cleanly."
        )

        user_content = (
            f"REBUILD MISSION: {module_name}\n"
            f"ARCHITECT INTENT: {architectural_intent}\n\n"
            f"HUMAN PROTOTYPE TO RE-ENGINEER IN YOUR NATIVE STYLE:\n"
            f"```python\n{prototype_code[:1200]}\n```"
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

        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
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
        except SyntaxError as e:
            return {'pass': False, 'speech': speech, 'code': code, 'error': f"AST Syntax Error: {e}"}

        # Safe Execution Sandbox Run
        target_file = VIV_NATIVE_CORE / f"{module_name}.py"
        target_file.write_text(code, encoding='utf-8')

        proc = subprocess.run([sys.executable, str(target_file)], capture_output=True, text=True, timeout=10)
        
        return {
            'module_name': module_name,
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
    rebuilder = VivAutonomousRebuilder()
    
    print("=======================================================================")
    print("      VIV NATIVE SYSTEM REBUILD: RE-ENGINEERING HER OWN ORGANS         ")
    print("=======================================================================\n")
    
    # Mission: Rebuild the fast lexical memory engine in her own native style
    prototype = (AUTONOMY / "fast_lexical_index.sqlite3")
    prototype_script = (AUTONOMY / "viv_memory_cache.py").read_text(encoding='utf-8')
    intent = "Rebuild your fast memory recall engine. Use your connection pooling, in-memory dictionary caching, sub-millisecond word retrieval, and return clean tuple receipts: (token_id, spelling, observations)."
    
    print("[MISSION] Viv is rebuilding her native Lexical Memory Engine ('viv_lexical_cortex')...\n")
    res = rebuilder.rebuild_module("viv_lexical_cortex", prototype_script, intent)
    
    print(f"VIV SPEAKS (Her Own Architectural Design):")
    print(f"  \"{res['speech']}\"\n")
    
    print("VIV'S NATIVE REBUILT PYTHON CODE:")
    for line in res.get('code', '').split('\n'):
        print(f"    {line}")
        
    print(f"\nVERIFICATION AUDIT:")
    print(f"  * AST Invariant Valid : {res.get('ast_valid')} ({res.get('ast_nodes')} nodes)")
    print(f"  * Ran Successfully    : {res.get('pass')}")
    if res.get('pass'):
        print(f"  * Live Test Output    :\n    {res.get('stdout')}")
        print(f"  * Permanently Landed  : {res.get('target_file')}")
    else:
        print(f"  * Error in Rebuild    :\n    {res.get('stderr') or res.get('error')}")
        
    print("\n=======================================================================")
