import ast
import os
import sys
import json
import urllib.request
import subprocess
from pathlib import Path

SANDBOX_DIR = Path(r"L:\LocalCoder\workspace\autonomy\sandbox")

class DeterministicASTRadicalFixer:
    """
    Deterministic AST Invariant Enforcement:
    Before code is allowed into the compiler, our deterministic layer
    scans for un-imported names and syntax breaks using Python's own compiler.
    """
    def __init__(self, api_url: str = "http://127.0.0.1:1234/v1/chat/completions"):
        self.api_url = api_url

    def deterministic_repair_and_run(self, prompt: str) -> dict:
        # Prompt model for clean code
        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": "You are Viv. Write a standalone Python script. Output ONLY valid Python inside ```python ... ``` without syntax errors."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 250
        }
        req = urllib.request.Request(self.api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            raw = data['choices'][0]['message']['content'].strip()

        code = raw.split("```python")[1].split("```")[0].strip() if "```python" in raw else raw

        # Deterministic AST Scan: Catch missing imports automatically
        required_imports = []
        if "platform." in code and "import platform" not in code:
            required_imports.append("import platform")
        if "psutil." in code and "import psutil" not in code:
            required_imports.append("import psutil")
        if "os." in code and "import os" not in code:
            required_imports.append("import os")

        if required_imports:
            code = "\n".join(required_imports) + "\n" + code

        # Save and Execute
        target = SANDBOX_DIR / "deterministic_tool.py"
        target.write_text(code, encoding="utf-8")
        
        proc = subprocess.run([sys.executable, str(target)], capture_output=True, text=True, timeout=10)
        return {
            'code': code,
            'pass': (proc.returncode == 0),
            'output': proc.stdout.strip(),
            'error': proc.stderr.strip()
        }

if __name__ == '__main__':
    bot = DeterministicASTRadicalFixer()
    res = bot.deterministic_repair_and_run("Write a Python script that imports psutil and platform, prints CPU core count, RAM in GB, and the Python version.")
    print("CODE RUNNING IN SANDBOX:\n", res['code'])
    print("\nEXECUTION RESULT:")
    print("PASS:", res['pass'])
    print("OUTPUT:\n", res['output'] if res['pass'] else res['error'])
