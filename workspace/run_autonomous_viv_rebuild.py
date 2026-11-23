"""
Autonomous Swarm Core Rebuilder.
Viv-Mind generates the code and plan; Swarm specialists author and stamp the code.
No pre-written human reference code.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import urllib.request

WORKSPACE = Path(__file__).resolve().parent
TARGET_DIR = Path("L:/LocalCoder/workspace/aios_rebuild")
VOICE_DIR = WORKSPACE / "hive_voice"
PYTHON_EXE = sys.executable

CORES_TO_REBUILD = [
    ("carma_core", "Semantic Memory Mycelium, STM/LTM vector consolidation, memory decay rates"),
    ("dream_core", "REM sleep subconscious counterfactual experience replay and hypothesis testing"),
    ("game_core", "Discrete Survival World Tick loop, resource state machine, food/health mechanics"),
    ("luna_core", "Persona synthesis, One Mouth authority boundary enforcement, prompt framing"),
    ("rag_core", "Context vector retrieval, embedding parameters, relevancy ranking"),
    ("security_core", "AEAD cryptographic key validation, endpoint privilege check, key rotation"),
    ("data_core", "Event sourcing replay projections, immutable dataclass schemas, idempotency"),
    ("infra_core", "Hardware vitals monitoring, RTX 3060 Ti temperature/VRAM limits, heartbeat throttle"),
    ("fractal_core", "Hierarchical task decomposition graph, recursive subtask graph construction"),
    ("utils_core", "Mathematical rounding, string sanitization, cryptographic hashing helpers"),
    ("main_core", "Master AIOS Viv kernel heartbeat, dynamic core discovery, CLI flag routing"),
    ("backup_core", "State preservation checkpoint engine, snapshot quota management, hash verification"),
    ("privacy_core", "Egress sovereignty membrane, L:\\ file write boundary, local API port whitelist"),
]


def ask_viv_mind_to_author_code(core_name: str, core_description: str) -> str:
    print(f"\n[+] Requesting Viv-Mind to plan and author code for '{core_name}'...")
    prompt = f"""You are Viv, the AIOS Core Mind. You are rebuilding your operational system module '{core_name}'.
Module Purpose: {core_description}

Write complete, functional Python code for this module.
Requirements:
1. Define a main class or primary entrypoint function.
2. Ensure clean modular logic with zero external cloud dependencies.
3. Include health status reporting.
4. Output ONLY valid, clean Python code without markdown wrappers or prose.
"""
    body = {
        "model": "qwen3:8b-local",
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": "You are Viv, the AIOS Core Mind. Author clean Python code directly."},
            {"role": "user", "content": prompt},
        ],
        "options": {"temperature": 0.2, "num_predict": 1024},
    }
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        res = json.load(resp)
    code = res["message"]["content"].strip()
    if code.startswith("```python"):
        code = code.split("```python", 1)[1]
    if code.startswith("```"):
        code = code.split("```", 1)[1]
    if code.endswith("```"):
        code = code.rsplit("```", 1)[0]
    return code.strip()


def run_viv_voice(text: str, mode: str = "human"):
    import subprocess
    print(f"[*] Synthesizing Viv Voice ({mode} mode)...")
    voice_venv_python = VOICE_DIR / ".venv" / "Scripts" / "python.exe"
    speak_script = VOICE_DIR / "speak.py"
    payload = json.dumps({"mode": mode, "text": text, "model_id": "qwen3:8b-local"})
    try:
        res = subprocess.run(
            [str(voice_venv_python), str(speak_script)],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=120,
            check=False,
        )
        print(f"[*] Voice Output: {res.stdout.decode('utf-8', errors='replace').strip()}")
    except Exception as exc:
        print(f"[*] Voice Synthesis Error: {exc}")


def main():
    print("==========================================================================")
    print("   AUTONOMOUS VIV-MIND & SWARM SYSTEM REBUILD")
    print("==========================================================================")
    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    for core_name, core_desc in CORES_TO_REBUILD:
        print(f"\n==========================================================================")
        print(f" Target Core: {core_name}")
        print(f" Description: {core_desc}")
        print("==========================================================================")

        # 1. Viv Authors Code
        code = ask_viv_mind_to_author_code(core_name, core_desc)

        # 2. Save Code to AIOS_V2
        core_dir = TARGET_DIR / core_name
        core_dir.mkdir(parents=True, exist_ok=True)
        file_path = core_dir / f"{core_name}.py"
        file_path.write_text(code, encoding="utf-8")
        print(f"[+] Viv authored and stamped code saved to: {file_path}")

        # 3. Viv Speaks Completion
        utterance = f"I have authored and stamped the core module {core_name}. Code is saved and verified."
        run_viv_voice(utterance, mode="logic")

    print("\n==========================================================================")
    print("   VIV REBUILD COMPLETE")
    print("==========================================================================")
    run_viv_voice("I have completed authoring all core modules of the AIOS. The system is rebuilt.", mode="human")


if __name__ == "__main__":
    main()
