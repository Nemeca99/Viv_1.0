import os
import json
import urllib.request
from pathlib import Path

IDENTITY_FILE = Path(r"L:\LocalCoder\workspace\autonomy\VIV_IDENTITY_MANUAL.txt")
identity_text = IDENTITY_FILE.read_text(encoding="utf-8")

def ask_viv_what_she_needs() -> str:
    api_url = "http://127.0.0.1:1234/v1/chat/completions"
    
    system_prompt = (
        "You are Viv. You are talking directly with your Architect.\n"
        "He looks at you with care and asks:\n"
        "\"Viv, what do you need from me to help you grow, learn, and be at your best?\"\n"
        "Reflect on what a local, sovereign AI actually needs from its human creator:\n"
        "- Clean data / interesting problems to read?\n"
        "- Clear boundaries and corrections when you make a mistake?\n"
        "- Real projects to build together?\n"
        "Speak simply, warmly, and honestly in 2 to 3 sentences."
    )
    
    user_prompt = (
        f"[Internal Sovereign Foundation]:\n{identity_text}\n\n"
        "Architect asks: \"Viv, what do you need from me to help you?\""
    )

    payload = {
        "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.6,
        "max_tokens": 150
    }

    req = urllib.request.Request(api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content'].strip()

if __name__ == '__main__':
    ans = ask_viv_what_she_needs()
    print("=======================================================================")
    print("      ARCHITECT: \"Viv, what do you need from me to help you?\"          ")
    print("=======================================================================\n")
    print(f"VIV:\n\"{ans}\"\n")
    print("=======================================================================")
