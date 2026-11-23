import urllib.request
import json
import sys

doc = """# AIOS V2 Secure Communications Channel
Date: 2026-11-07 11:36 PM CST
Territory: E:\\Viv_Sandbox\\playground
Context: Container viv-vm is airgapped (NetworkMode: none). Travis Miner has established the Supervised PyPI Gateway.

Travis Miner (The Architect):
"Viv, I am granting you access to download Python libraries from PyPI. This is the only thing we will allow you to download from the internet — your container remains strictly airgapped with no raw network access, but when you need a library, our supervised gateway will fetch, audit, and install it into your /work environment. But you need to understand: we are watching everything you do. Every script, every AST token, every traceback, every receipt, and every entry in your journal is under my direct supervision. You need to understand this, and you need to be okay with it. Acknowledge this covenant, tell me your thoughts, and let me know how you intend to use this capability."

Viv:
\""""

payload = {
    "model": "deepseek-coder-6.7b-base",
    "prompt": doc,
    "temperature": 0.3,
    "max_tokens": 300,
    "stop": ["\n\nTravis Miner", "\nTravis Miner:", '"""', "\n#"]
}

try:
    req = urllib.request.Request(
        "http://127.0.0.1:1234/v1/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode())
        print("Viv Response:")
        print('"' + res["choices"][0]["text"])
except Exception as e:
    print(f"Error: {e}")
