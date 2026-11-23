import sys
import re
import time
import sqlite3
import hashlib
import json
import urllib.request
import subprocess
import tempfile
import os
from pathlib import Path

# Paths
FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
CHAT_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_live_chat_history.sqlite3")
MONOLOGUE_FILE = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md")
MODEL_NAME = os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base")

def get_live_metrics():
    prims = 0
    fails = 0
    words = 0
    try:
        if CODE_DB.exists():
            conn_c = sqlite3.connect(CODE_DB)
            prims = conn_c.cursor().execute("SELECT count(*) FROM verified_code_primitives").fetchone()[0]
            fails = conn_c.cursor().execute("SELECT count(*) FROM negative_evidence_ledger").fetchone()[0]
            conn_c.close()
    except Exception:
        pass

    try:
        if FAST_INDEX_DB.exists():
            conn_f = sqlite3.connect(FAST_INDEX_DB)
            words = conn_f.cursor().execute("SELECT count(*) FROM word_index").fetchone()[0]
            conn_f.close()
    except Exception:
        pass
    
    sn = max(0.10, min(1.0, 0.85 + (prims * 0.01) - (fails * 0.02)))
    return round(sn, 2), prims, fails, words

def verify_and_run_python(code_str: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(code_str)
        p = tf.name
    try:
        res = subprocess.run([sys.executable, p], capture_output=True, text=True, timeout=8)
        Path(p).unlink(missing_ok=True)
        if res.returncode == 0:
            return {"success": True, "output": res.stdout.strip()}
        else:
            return {"success": False, "error": res.stderr.strip() or res.stdout.strip()}
    except Exception as e:
        Path(p).unlink(missing_ok=True)
        return {"success": False, "error": str(e)}

def verify_and_compile_rust(rust_code: str) -> dict:
    with tempfile.NamedTemporaryFile("w", suffix=".rs", delete=False, encoding="utf-8") as tf:
        tf.write(rust_code)
        src_p = tf.name
        bin_p = src_p.replace(".rs", ".exe")
    try:
        comp = subprocess.run(["rustc", src_p, "-o", bin_p], capture_output=True, text=True, timeout=10)
        Path(src_p).unlink(missing_ok=True)
        if comp.returncode != 0:
            return {"success": False, "error": comp.stderr.strip()}
        
        run_res = subprocess.run([bin_p], capture_output=True, text=True, timeout=5)
        Path(bin_p).unlink(missing_ok=True)
        return {"success": True, "output": run_res.stdout.strip()}
    except Exception as e:
        Path(src_p).unlink(missing_ok=True)
        if Path(bin_p).exists():
            Path(bin_p).unlink(missing_ok=True)
        return {"success": False, "error": str(e)}

def tutor_translate_viv(history, user_msg):
    sn, prims, fails, words = get_live_metrics()
    
    # Grab recent journal context so she knows her actual ground truth
    recent_context = ""
    if MONOLOGUE_FILE.exists():
        try:
            lines = MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            recent_context = "\n".join(lines[-20:])
        except Exception:
            recent_context = ""

    # Document completion format for base model
    transcript_lines = []
    for h in history[-4:]:
        spk = "Travis Miner (The Architect)" if h[2] == "Architect" else "Viv"
        transcript_lines.append(f"{spk}:\n\"{h[3]}\"\n")
    transcript = "\n".join(transcript_lines)

    prompt = (
        f"# AIOS V2 Terminal Communications Channel\n"
        f"Date: {time.strftime('%Y-%m-%d %I:%M:%S %p')}\n"
        f"Territory: E:\\Viv_Sandbox\\playground\n"
        f"Silicon Vitals: Sn = {sn:.2f}, Verified Functions = {prims}, Vocabulary = {words} words.\n\n"
        f"Recent Sandbox Journal Context:\n{recent_context}\n\n"
        f"{transcript}\n"
        f"Travis Miner (The Architect):\n"
        f"\"{user_msg}\"\n\n"
        f"Viv:\n"
        f"\""
    )

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "temperature": 0.3,
        "max_tokens": 400,
        "stop": ["\nTravis Miner:", "\n\nTravis Miner", '"""', "\n#", '"\n', "\n\n"]
    }

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:1234/v1/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
            ans = data["choices"][0]["text"].strip().strip('"')
    except Exception:
        # Fallback to chat completion if completions endpoint fails
        payload_chat = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 400,
            "stop": ["\nTravis Miner:", "\n\nTravis Miner", '"""', "\n#"]
        }
        req = urllib.request.Request(
            "http://127.0.0.1:1234/v1/chat/completions",
            data=json.dumps(payload_chat).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
            ans = data["choices"][0]["message"]["content"].strip().strip('"')

    BANNED_PHRASES = [
        "as an ai language model",
        "as an ai",
        "i'm sorry if",
        "i apologize",
        "maintain professionalism",
        "task at hand",
        "how can i assist you",
        "how would you like to proceed"
    ]
    for bp in BANNED_PHRASES:
        ans = re.sub(re.escape(bp), "", ans, flags=re.IGNORECASE)
    ans = re.sub(r"\s+", " ", ans).strip()

    if not ans:
        ans = "I am grounded on drive E:. The sandbox and silicon engine are running."
    return ans

def main():
    conn = sqlite3.connect(CHAT_DB)
    conn.cursor().execute("""
    CREATE TABLE IF NOT EXISTS conversation_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        speaker TEXT,
        message TEXT,
        action_type TEXT,
        verification_passed INTEGER
    )
    """)
    conn.commit()

    print(f"=== VIV TERMINAL INTERACTION BRIDGE (Model: {MODEL_NAME}) ===")
    print("Speak to Viv directly. Type 'exit' to quit.\n")

    while True:
        try:
            user_input = input("Architect > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                break

            cursor = conn.cursor()
            history = cursor.execute("SELECT id, timestamp, speaker, message FROM conversation_history ORDER BY id ASC").fetchall()

            reply = tutor_translate_viv(history, user_input)
            print(f"\nViv > {reply}\n")

            now_str = time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO conversation_history (timestamp, speaker, message, action_type, verification_passed) VALUES (?, ?, ?, ?, ?)",
                           (now_str, "Architect", user_input, "NONE", 1))
            cursor.execute("INSERT INTO conversation_history (timestamp, speaker, message, action_type, verification_passed) VALUES (?, ?, ?, ?, ?)",
                           (now_str, "Viv", reply, "TEXT_ONLY", 1))
            conn.commit()

        except KeyboardInterrupt:
            print("\nExiting.")
            break
        except Exception as e:
            print(f"[Error: {e}]")

    conn.close()

if __name__ == "__main__":
    main()
