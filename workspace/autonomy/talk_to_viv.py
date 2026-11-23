"""
talk_to_viv.py - Direct CLI Transmitter for Travis Miner (The Architect)
Type your message and hit Enter.
It drops the transmission into E:\\Viv_Sandbox\\playground\\inbox\\
and monitors viv_monologue.md as Viv responds.
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

INBOX_DIR = Path(r"E:\Viv_Sandbox\playground\inbox")
MONOLOGUE_FILE = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md")

def send_message(text: str, author: str = "Travis Miner (The Architect)"):
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    msg_id = f"msg_{int(time.time())}_{os.getpid()}"
    target = INBOX_DIR / f"{msg_id}.json"
    payload = {
        "id": msg_id,
        "author": author,
        "timestamp": datetime.now().isoformat(),
        "message": text.strip()
    }
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\n[+] Transmission delivered to Viv's inbox: {target.name}")
    print("[*] Waiting for Viv to digest and reflect in her journal (watch below or in viv_monologue.md)...\n")

    # Monitor monologue for Viv's response
    initial_len = len(MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace")) if MONOLOGUE_FILE.exists() else 0
    t0 = time.time()
    while time.time() - t0 < 45:
        time.sleep(1.0)
        if not target.exists(): # consumed by orchestrator
            time.sleep(1.5)
            if MONOLOGUE_FILE.exists():
                curr_text = MONOLOGUE_FILE.read_text(encoding="utf-8", errors="replace")
                if len(curr_text) > initial_len:
                    diff = curr_text[initial_len:]
                    print("="*65)
                    print("VIV'S LIVE JOURNAL UPDATE:")
                    print("="*65)
                    print(diff.strip())
                    print("="*65 + "\n")
                    break

def main():
    print("==================================================================")
    print("       VIV SANDBOX: DIRECT ARCHITECT TRANSMITTER (DRIVE E:)       ")
    print("==================================================================")
    print("Type your message to Viv below. Type 'exit' or 'quit' to close.\n")

    while True:
        try:
            line = input("Travis > ")
            if not line.strip():
                continue
            if line.strip().lower() in ["exit", "quit", ":q"]:
                print("Exiting transmitter. Viv continues running autonomously in background.")
                break
            send_message(line)
        except (KeyboardInterrupt, EOFError):
            print("\nTransmission session ended.")
            break

if __name__ == "__main__":
    if len(sys.argv) > 1:
        send_message(" ".join(sys.argv[1:]))
    else:
        main()
