import urllib.request
import json

def test_notebook_format(event, result, detail):
    prompt = f'''"""
Viv Lab Notebook - Drive E:
Container: viv-vm (/work, NetworkMode=none)

Event: {event}
Silicon Execution: {result}
Trace: {detail}

Personal Engineering Notes:
I'''

    payload = {
        "model": "deepseek-coder-6.7b-base",
        "prompt": prompt,
        "temperature": 0.4,
        "max_tokens": 120,
        "stop": ['"""', "\n\nEvent:", "\nEvent:", "\nViv Lab Notebook", "\n#"]
    }

    req = urllib.request.Request(
        "http://127.0.0.1:1234/v1/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode())
        raw = "I" + res["choices"][0]["text"].strip()
        # Ensure it terminates at the last sentence period
        if "." in raw:
            raw = raw[:raw.rfind(".")+1]
        print(f"[{event}] ->")
        print(raw)
        print("=" * 60)

test_notebook_format(
    "Game Studio: Math Riddle with deterministic clues",
    "PASSED (Exit 0)",
    "Script generated with automatic solver bot. All assertions verified."
)
test_notebook_format(
    "Agenda: Base-52 Modular Arithmetic",
    "FAILED (Exit 1)",
    "ZeroDivisionError on line 42 when computing modulus of empty vector."
)
test_notebook_format(
    "Supervised Package Access",
    "INSTALLED (Gateway Verified)",
    "Travis Miner granted access to PyPI wheels under surveillance. Installed mpmath."
)
