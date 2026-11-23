import urllib.request
import json

prompt = '''"""
Module: cellular_automaton.py
Task: Implement a 1D Cellular Automaton with Rule 30
Goal: Compute 10 steps of Rule 30 on a 31-cell tape, verify the state with assertions.
Environment: Python 3.12, headless container sandbox.
"""

def rule30_step(cells):
'''

payload = {
    'model': 'deepseek-coder-6.7b-base',
    'prompt': prompt,
    'temperature': 0.2,
    'max_tokens': 350,
    'stop': ['\n\n"""', '\n"""', '# End of file']
}

req = urllib.request.Request(
    'http://127.0.0.1:1234/v1/completions',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode())
    full_code = 'def rule30_step(cells):\n' + res['choices'][0]['text']
    print('Code generated:')
    print(full_code)
