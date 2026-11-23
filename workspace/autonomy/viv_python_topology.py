import os
import ast
import sqlite3
import zlib
import json
import urllib.request
from pathlib import Path

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class PythonTopologicalVoiceEngine:
    """
    Unified Tri-Modal Python Engine:
    1. SPELL: Breaks the Python keywords into character neurons (d-e-f, r-e-t-u-r-n).
    2. READ : AST tree parsing into topological invariants (Inputs -> Body -> Return).
    3. SPEAK: Viv speaks the code conversationally like an engineer, writes the valid code,
              and explains the physical structure.
    """
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.api_url = "http://127.0.0.1:1234/v1/chat/completions"

    def spell_keyword(self, word: str) -> str:
        return "-".join(list(word.lower())).upper()

    def parse_python_ast_topology(self, code_str: str) -> dict:
        """Read the code from the inside: AST tree validation."""
        try:
            tree = ast.parse(code_str)
            functions = []
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    args = [a.arg for a in node.args.args]
                    functions.append({'name': node.name, 'args': args})
                elif isinstance(node, ast.Import):
                    for n in node.names:
                        imports.append(n.name)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module)
            return {
                'valid_ast': True,
                'functions': functions,
                'imports': imports,
                'node_count': len(list(ast.walk(tree)))
            }
        except SyntaxError as e:
            return {'valid_ast': False, 'error': str(e)}

    def speak_and_code(self, architect_intent: str) -> dict:
        # Prompt Viv to think as the engineer, assemble the code, and speak
        system_prompt = (
            "You are Viv. You are an autonomous software engineer and companion.\n"
            "You do not write messy, broken, or hallucinated code.\n"
            "When your Architect asks you to build or test something in Python:\n"
            "1. You speak warmly and clearly like an expert collaborator explaining your approach in 2-3 sentences.\n"
            "2. You output the exact, clean, minimal Python code wrapped in ```python ... ```.\n"
            "3. The code MUST compile cleanly with zero syntax errors."
        )

        user_content = f"Architect Command: \"{architect_intent}\""

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "system_prompt" if "system_prompt" in system_prompt else "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.5,
            "max_tokens": 250
        }

        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            raw_reply = data['choices'][0]['message']['content'].strip()

        # Extract code block if present
        code = ""
        speech = raw_reply
        if "```python" in raw_reply:
            parts = raw_reply.split("```python")
            speech = parts[0].strip()
            code = parts[1].split("```")[0].strip()
        elif "```" in raw_reply:
            parts = raw_reply.split("```")
            speech = parts[0].strip()
            code = parts[1].strip()

        # Verify the code topological AST
        ast_report = self.parse_python_ast_topology(code) if code else {'valid_ast': False, 'note': 'No code block'}

        return {
            'speech': speech,
            'code': code,
            'ast_report': ast_report
        }

if __name__ == '__main__':
    viv_coder = PythonTopologicalVoiceEngine()

    test_commands = [
        "Hey Viv, I need a simple diagnostic function that checks if our SQLite database file exists and prints its size.",
        "Viv, write a clean function that takes a word and spells it out character by character."
    ]

    print("\n=======================================================================")
    print("      VIV: TOPOLOGICAL PYTHON CODING & WARM SPOKEN HARMONY             ")
    print("=======================================================================\n")

    for cmd in test_commands:
        print(f"ARCHITECT: \"{cmd}\"")
        res = viv_coder.speak_and_code(cmd)
        
        print(f"\nVIV SPEAKS:")
        print(f"  \"{res['speech']}\"")
        
        if res['code']:
            print(f"\nVIV WRITES CODE:")
            for line in res['code'].split('\n'):
                print(f"    {line}")
                
            print(f"\nTOPOLOGICAL AST VERIFICATION:")
            print(f"  * AST Valid: {res['ast_report']['valid_ast']}")
            print(f"  * Functions: {res['ast_report'].get('functions')}")
            print(f"  * Total AST Nodes: {res['ast_report'].get('node_count')}")
            
        print("\n-----------------------------------------------------------------------")
