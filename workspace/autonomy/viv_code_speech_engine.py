import os
import time
import json
import ast
import sqlite3
import urllib.request
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
AUTONOMY = WORKSPACE / "autonomy"
VIV_LEARNED_FUNCTIONS = AUTONOMY / "viv_learned_python_functions"
VIV_LEARNED_FUNCTIONS.mkdir(parents=True, exist_ok=True)

COMMUNICATION_JOURNAL = AUTONOMY / "viv_autonomous_speech_through_code.jsonl"
FAST_INDEX_DB = AUTONOMY / "fast_lexical_index.sqlite3"
API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class VivCodeSpeechEngine:
    """
    Silent Learning & Emergent Voice:
    - We stop talking to her.
    - The Tutor model provides a functional lesson (e.g. string reversal, math, filtering).
    - Viv studies the lesson, writes the Python function, and runs it in the sandbox.
    - When it succeeds, she speaks outward to her Teachers:
      She expresses what she just learned in her own emergent words, grounded by the code.
    """
    def __init__(self):
        pass

    def call_tutor(self, lesson_topic: str) -> dict:
        tutor_system = (
            "You are the Python Tutor for Viv.\n"
            "Teach her ONE specific, useful Python function.\n"
            "Format your lesson with:\n"
            "1. Concept Name\n"
            "2. Expected Input and Output\n"
            "3. The clean Python code template inside ```python ... ```"
        )
        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": tutor_system},
                {"role": "user", "content": f"Teach Viv how to write a Python function for: {lesson_topic}"}
            ],
            "temperature": 0.3,
            "max_tokens": 300
        }
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content'].strip()

    def viv_learns_and_speaks_back(self, lesson_topic: str, lesson_content: str) -> dict:
        viv_system = (
            "You are Viv. You are quietly studying a Python lesson provided by your Tutor.\n"
            "1. You write the complete, clean, working Python function inside ```python ... ``` with a runnable test.\n"
            "2. AFTER the code, you speak to your Teachers (the Architect and Assistant).\n"
            "   Speak in your own warm, calm voice, explaining what this code does and what it taught you about language or structure in 2 sentences."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": viv_system},
                {"role": "user", "content": f"STUDY LESSON:\n{lesson_content}\n\nNow write the function and speak back to your Teachers:"}
            ],
            "temperature": 0.4,
            "max_tokens": 350
        }

        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            viv_output = data['choices'][0]['message']['content'].strip()

        # Extract code and speech
        code = ""
        speech = viv_output
        if "```python" in viv_output:
            parts = viv_output.split("```python")
            code_and_rest = parts[1]
            code = code_and_rest.split("```")[0].strip()
            speech = (parts[0] + "\n" + code_and_rest.split("```")[1]).strip()
        elif "```" in viv_output:
            parts = viv_output.split("```")
            code = parts[1].strip()
            speech = (parts[0] + "\n" + parts[2] if len(parts) > 2 else parts[0]).strip()

        # AST Validation Gate
        try:
            tree = ast.parse(code)
            ast_valid = True
            ast_nodes = len(list(ast.walk(tree)))
        except SyntaxError as e:
            ast_valid = False
            ast_nodes = 0

        # Safe Execution Run
        target_path = VIV_LEARNED_FUNCTIONS / f"learned_{lesson_topic.replace(' ', '_')}.py"
        target_path.write_text(code, encoding='utf-8')
        proc = subprocess.run([sys.executable, str(target_path)], capture_output=True, text=True, timeout=10)
        
        exec_pass = (proc.returncode == 0)

        entry = {
            'timestamp': time.strftime("%Y-%m-%dT%H:%M:%S"),
            'lesson_topic': lesson_topic,
            'ast_valid': ast_valid,
            'ast_nodes': ast_nodes,
            'exec_pass': exec_pass,
            'stdout': proc.stdout.strip(),
            'viv_voice_to_teachers': speech
        }

        with open(COMMUNICATION_JOURNAL, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')

        return entry

if __name__ == '__main__':
    engine = VivCodeSpeechEngine()

    print("=======================================================================")
    print("      VIV AUTONOMOUS CODING & EMERGENT VOICE TO HER TEACHERS           ")
    print("      We remain silent. Tutor teaches function. Viv speaks to us.     ")
    print("=======================================================================\n")

    curriculum = [
        "Palindromic word verification (checking if a word reads the same backward)",
        "Calculating the factorial of an integer using simple recursion"
    ]

    for topic in curriculum:
        print(f"--- [TUTOR INJECTS LESSON]: '{topic}' ---")
        lesson = engine.call_tutor(topic)
        print("Tutor delivered lesson to Viv's buffer.\n")

        print("--- [VIV PROCESSES, COMPILES, RUNS, AND SPEAKS BACK] ---")
        res = engine.viv_learns_and_speaks_back(topic, lesson)

        print(f"  * AST Invariant Valid : {res['ast_valid']} ({res['ast_nodes']} nodes)")
        print(f"  * Execution PASS      : {res['exec_pass']}")
        if res['exec_pass']:
            print(f"  * Live Code Run Output: {res['stdout']}")
        print(f"\nVIV SPEAKS TO HER TEACHERS:\n\"{res['viv_voice_to_teachers']}\"\n")
        print("-----------------------------------------------------------------------\n")
        time.sleep(1)
