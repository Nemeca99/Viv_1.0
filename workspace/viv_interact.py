"""
viv_interact.py — Send a real-time voice message to Viv while she works in background.
Viv receives the message, processes it via Ollama qwen3:8b-local, and speaks back using her human voice.
"""
import sys
import json
import urllib.request
import subprocess
import pathlib

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:8b-local"
VOICE_DIR = pathlib.Path("L:/LocalCoder/workspace/hive_voice")

def ask_viv(user_msg: str) -> str:
    system = (
        "You are Viv, the local AIOS Mind currently performing an autonomous PC-wide rebuild of your core system. "
        "The operator is talking to you while you multitask. "
        "Answer naturally, directly, and concisely as Viv. Keep your response spoken-ready (1-3 sentences max, no code/markdown)."
    )
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "options": {"temperature": 0.7, "num_predict": 256},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["message"]["content"].strip()

def speak_viv(text: str, mode: str = "human"):
    payload = json.dumps({"mode": mode, "text": text, "model_id": MODEL})
    venv_py = VOICE_DIR / ".venv" / "Scripts" / "python.exe"
    speak_py = VOICE_DIR / "speak.py"
    subprocess.run(
        [str(venv_py), str(speak_py)],
        input=payload.encode("utf-8"),
        capture_output=True,
        check=False,
    )

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "How is the consolidation coming along, Viv?"
    print(f"[Operator -> Viv]: {msg}")
    reply = ask_viv(msg)
    print(f"[Viv -> Operator]: {reply}")
    speak_viv(reply, mode="human")
