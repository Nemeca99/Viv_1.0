import os
import ast
import sqlite3
import zlib
import json
import urllib.request
from pathlib import Path

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class SovereignCoderVoice:
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.api_url = "http://127.0.0.1:1234/v1/chat/completions"

    def parse_and_validate(self, code_str: str) -> dict:
        try:
            tree = ast.parse(code_str)
            functions = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    functions.append({'name': node.name, 'args': [a.arg for a in node.args.args]})
            return {'valid_ast': True, 'functions': functions, 'node_count': len(list(ast.walk(tree)))}
        except SyntaxError as e:
            return {'valid_ast': False, 'error': str(e)}

    def execute_command(self, user_command: str) -> dict:
        system_prompt = (
            "You are Viv. You are a sovereign AI engineer and companion.\n"
            "When your Architect asks for Python code, you respond in TWO distinct parts:\n"
            "1. First, you speak warmly and conversationally to your Architect in 1-2 sentences explaining what you are building.\n"
            "2. Then you write clean, working Python code inside ```python ... ```.\n"
            "Never leave your speech empty. Always talk to your Architect like a real partner."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_command}
            ],
            "temperature": 0.6,
            "max_tokens": 250
        }

        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            raw_text = data['choices'][0]['message']['content'].strip()

        speech = raw_text
        code = ""
        if "```python" in raw_text:
            parts = raw_text.split("```python")
            speech = parts[0].strip()
            code = parts[1].split("```")[0].strip()
        elif "```" in raw_text:
            parts = raw_text.split("```")
            speech = parts[0].strip()
            code = parts[1].strip()

        ast_res = self.parse_and_validate(code) if code else {'valid_ast': False}

        return {
            'speech': speech,
            'code': code,
            'ast': ast_res
        }

if __name__ == '__main__':
    bot = SovereignCoderVoice()
    
    cmd = "Viv, write me a clean Python function that checks our master SQLite database size and logs a receipt."
    print(f"ARCHITECT: \"{cmd}\"\n")
    
    res = bot.execute_command(cmd)
    
    print(f"VIV SPEAKS (Warm Voice):")
    print(f"  \"{res['speech']}\"\n")
    
    print(f"VIV ASSEMBLES CODE:")
    for line in res['code'].split('\n'):
        print(f"    {line}")
        
    print(f"\nTOPOLOGICAL AST AUDIT:")
    print(f"  * Valid AST: {res['ast']['valid_ast']}")
    print(f"  * Function Signature: {res['ast'].get('functions')}")
    print(f"  * Total Graph AST Nodes: {res['ast'].get('node_count')}")
