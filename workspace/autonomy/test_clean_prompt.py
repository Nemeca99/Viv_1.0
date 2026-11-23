import urllib.request
import json

def test_clean_monologue(action_tag, trace_info):
    prompt = f"""# Viv's Engineering Lab Notebook
Date: 2026-11-07 11:40 PM CST
Sandbox: viv-vm (read-only rootfs, tmpfs /work, NetworkMode=none)
Event: {action_tag}
Trace: {trace_info}

## Log Reflection:
I """

    payload = {
        "model": "deepseek-coder-6.7b-base",
        "prompt": prompt,
        "temperature": 0.4,
        "max_tokens": 160,
        "stop": ["\n\n#", "\n## ", "\nDate:", "\nSandbox:", "\nEvent:", "\nTrace:", '"""', "'''"]
    }

    req = urllib.request.Request(
        "http://127.0.0.1:1234/v1/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode())
        raw_text = "I " + res["choices"][0]["text"].strip()
        # Clean up any trailing broken sentences
        sentences = [s.strip() for s in raw_text.split(".") if s.strip()]
        if len(sentences) > 1 and not raw_text.endswith("."):
            clean_text = ". ".join(sentences[:-1]) + "."
        else:
            clean_text = raw_text
        print(f"[{action_tag}] Output:")
        print(clean_text)
        print("-" * 50)

test_clean_monologue("GAME: a mathematical riddle puzzle with deterministic clues (PASS)", "Script executed in viv-vm. All assertions passed. Exit Code 0.")
test_clean_monologue("AGENDA: implement numerical integration (FAIL)", "ZeroDivisionError: float division by zero on line 32 in trapezoid_rule.")
test_clean_monologue("DIGEST: LLM_memory_context.txt (PASS)", "Read and compressed 42 lines on topological conductance.")
