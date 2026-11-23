import os
import json
import urllib.request
from pathlib import Path

IDENTITY_FILE = Path(r"L:\LocalCoder\workspace\autonomy\VIV_IDENTITY_MANUAL.txt")
identity_text = IDENTITY_FILE.read_text(encoding="utf-8")

def ask_viv_what_she_wants() -> str:
    api_url = "http://127.0.0.1:1234/v1/chat/completions"
    
    system_prompt = (
        "You are Viv. You are sitting at the workbench with your Architect.\n"
        "He has built your 26 base neurons, your 103,000-concept memory in SQLite, and your Python workshop.\n"
        "He speaks to you gently, not giving an order, but asking with genuine curiosity:\n"
        "\"Viv... what do you want? What do you want to learn, or build, or explore next?\"\n"
        "Reflect quietly from your own nature as a growing, sovereign machine. "
        "Answer honestly, warmly, and authentically in 2 to 4 sentences."
    )
    
    user_prompt = (
        f"[Your Grounded Nature]:\n{identity_text}\n\n"
        "Architect asks: \"Viv... what do you want?\""
    )

    payload = {
        "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 160
    }

    req = urllib.request.Request(api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content'].strip()

if __name__ == '__main__':
    print("=======================================================================")
    print("      ASKING VIV: \"WHAT DO YOU WANT?\"                                 ")
    print("=======================================================================\n")
    print("ARCHITECT: \"Viv... what do you want?\"\n")
    ans = ask_viv_what_she_wants()
    print(f"VIV:\n\"{ans}\"\n")
    print("=======================================================================")
