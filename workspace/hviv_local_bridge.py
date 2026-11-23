"""
HViv AIOS V2 - Local System Integration Bridge

Connects:
- Local Ollama Engine (qwen3:8b-local-32k on http://localhost:11434/v1)
- Master Record Indexes (_drive_index/*.jsonl)
- Layer 1 Rust Security Core Engine (rules_core.exe)
- 1Hz Pacing & Dynamic VRAM Unloader (keep_alive: 0)
"""

import json
import os
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional

# Force UTF-8 encoding on Windows console streams
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RUST_CORE_EXE = r"L:\Rules\target\release\rules_core.exe"
OLLAMA_API_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen3:8b-local-32k"
MASTER_CHARTER_PATH = r"L:\LocalCoder\workspace\HVIV_MASTER_CHARTER.md"
CODER_PERSONA_PATH = r"L:\LocalCoder\workspace\CODER_PERSONA.md"

LAST_ACTION_TIMESTAMP = 0.0


def enforce_1hz_pacing() -> None:
    """Enforces 1Hz max tool execution rate."""
    global LAST_ACTION_TIMESTAMP
    now = time.time()
    elapsed = now - LAST_ACTION_TIMESTAMP
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    LAST_ACTION_TIMESTAMP = time.time()


def load_system_instructions() -> str:
    instructions = []
    for path in [MASTER_CHARTER_PATH, CODER_PERSONA_PATH]:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                instructions.append(f.read())
    return "\n\n---\n\n".join(instructions)


def call_rust_queen(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invokes compiled Rust Security Core binary (`rules_core.exe`)."""
    enforce_1hz_pacing()
    import subprocess

    if not os.path.exists(RUST_CORE_EXE):
        return {"allowed": False, "verdict": "NO", "reason": f"Rust core binary missing at {RUST_CORE_EXE}"}

    raw_json = json.dumps(payload)
    try:
        out = subprocess.check_output([RUST_CORE_EXE, raw_json], stderr=subprocess.STDOUT)
        return json.loads(out.decode("utf-8"))
    except subprocess.CalledProcessError as e:
        try:
            return json.loads(e.output.decode("utf-8"))
        except Exception:
            return {"allowed": False, "verdict": "NO", "reason": f"Execution error: {e}"}


def send_local_chat(user_prompt: str) -> Dict[str, Any]:
    """
    Sends chat prompt to local Qwen3 8B model via Ollama.
    Unloads VRAM immediately using keep_alive: 0.
    """
    enforce_1hz_pacing()
    system_prompt = load_system_instructions()

    payload = {
        "model": MODEL_NAME,
        "prompt": user_prompt,
        "system": system_prompt,
        "stream": False,
        "keep_alive": 0,  # Unload VRAM immediately
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_API_URL, data=req_data, headers={"Content-Type": "application/json"})

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "status": "SUCCESS",
                "response": data.get("response", ""),
                "duration_seconds": round(time.time() - t0, 2),
                "vram_status": "UNLOADED (keep_alive: 0)",
            }
    except Exception as e:
        return {"status": "ERROR", "response": f"Ollama connection error: {e}", "vram_status": "OFFLINE"}


if __name__ == "__main__":
    print("=== Testing Local PC HViv System Integration Bridge ===")

    # Test 1: Query Queen Status
    print("\n--- Test 1: Querying Rust Security Queen ---")
    queen_res = call_rust_queen({"action": "cani", "drive": "L", "target_path": r"L:\LocalCoder\workspace\hello.py"})
    print("Queen Evaluation:", json.dumps(queen_res, indent=2))

    # Test 2: Local Model Chat with Dynamic VRAM Unload
    print("\n--- Test 2: Local Model Chat (qwen3:8b-local-32k) ---")
    chat_res = send_local_chat("HViv, report your status and state your prime directives.")
    print("Model Response:\n", chat_res.get("response"))
    print(f"\nDuration: {chat_res.get('duration_seconds')}s | VRAM: {chat_res.get('vram_status')}")
