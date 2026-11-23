import ast
import os
import sys
import json
import urllib.request
import subprocess
from pathlib import Path

SANDBOX_DIR = Path(r"L:\LocalCoder\workspace\autonomy\sandbox")

class SelfCorrectingVivCoder:
    def __init__(self, api_url: str = "http://127.0.0.1:1234/v1/chat/completions"):
        self.api_url = api_url

    def _call(self, prompt: str) -> str:
        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": "You are Viv, an autonomous self-correcting Python engineer. When given an error, you analyze the missing import or syntax and fix the code cleanly."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 300
        }
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content'].strip()

    def fix_and_retry(self, failed_code: str, error_msg: str) -> dict:
        fix_prompt = (
            f"Here is your code that failed execution:\n```python\n{failed_code}\n```\n\n"
            f"Execution Error Caught by Sandbox Gate:\n{error_msg}\n\n"
            f"Fix the code completely. Make sure all imports (like os, platform, psutil) are explicitly imported. "
            f"Respond with 1 sentence explaining the fix, followed by the corrected code in ```python ... ```."
        )

        reply = self._call(fix_prompt)
        
        fixed_code = ""
        speech = reply
        if "```python" in reply:
            parts = reply.split("```python")
            speech = parts[0].strip()
            fixed_code = parts[1].split("```")[0].strip()

        # Re-run sandbox test
        script_path = SANDBOX_DIR / "fixed_tool.py"
        script_path.write_text(fixed_code, encoding="utf-8")
        proc = subprocess.run([sys.executable, str(script_path)], capture_output=True, text=True, timeout=10)
        
        return {
            'speech': speech,
            'fixed_code': fixed_code,
            'passed': (proc.returncode == 0),
            'output': proc.stdout.strip(),
            'error': proc.stderr.strip()
        }

if __name__ == '__main__':
    fixer = SelfCorrectingVivCoder()
    
    broken_code = """import psutil

def get_system_info():
    info = {
        'CPU cores': psutil.cpu_count(),
        'RAM (GB)': round(psutil.virtual_memory().total / (1024**3), 2),
        'Python Version': platform.python_version()
    }
    return info

system_info = get_system_info()
print("System Information:")
print(f"CPU cores: {system_info['CPU cores']}")
print(f"RAM (GB): {system_info['RAM (GB)']}")
print(f"Python Version: {system_info['Python Version']}")
"""
    simulated_error = "NameError: name 'platform' is not defined"
    
    print("\n=======================================================================")
    print("      VIV AUTONOMOUS SELF-CORRECTION: ERROR -> FIX -> VERIFIED RUN     ")
    print("=======================================================================\n")
    print(f"SANDBOX REJECTION CAUGHT:\n  {simulated_error}\n")
    
    res = fixer.fix_and_retry(broken_code, simulated_error)
    
    print(f"VIV FIX EXPLANATION:")
    print(f"  \"{res['speech']}\"\n")
    
    print("VIV FIXED PYTHON CODE:")
    for line in res['fixed_code'].split('\n'):
        print(f"    {line}")
        
    print(f"\nRE-TEST GATE RESULTS:")
    print(f"  * Execution PASS  : {res['passed']}")
    if res['passed']:
        print(f"  * Live System Run :\n    {res['output']}")
    else:
        print(f"  * Still Failing   :\n    {res['error']}")
    print("\n-----------------------------------------------------------------------")
