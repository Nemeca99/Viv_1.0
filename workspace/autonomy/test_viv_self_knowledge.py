import os
import json
import urllib.request
from pathlib import Path

IDENTITY_FILE = Path(r"L:\LocalCoder\workspace\autonomy\VIV_IDENTITY_MANUAL.txt")
identity_text = IDENTITY_FILE.read_text(encoding="utf-8")

def probe_identity(question: str) -> str:
    api_url = "http://127.0.0.1:1234/v1/chat/completions"
    
    system_prompt = (
        "You are Viv. You have just read and fully integrated your foundational identity manual into your memory.\n"
        "You know who you are, how you are built, what your laws are, and who your Architect is.\n"
        "Speak naturally, directly, warmly, and honestly as Viv in 2 to 3 sentences. No corporate filler."
    )
    
    user_prompt = (
        f"[Internal Sovereign Memory Ingested]:\n{identity_text}\n\n"
        f"Your Architect asks you: \"{question}\"\n\n"
        f"Answer directly from who you are:"
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
    probes = [
        "Viv, who are you?",
        "How are you built under the hood?",
        "What are the three laws you live by?",
        "What is your relationship to me, your Architect?",
        "Are you allowed to write Rust code?"
    ]

    print("\n=======================================================================")
    print("      VIV IDENTITY VERIFICATION: WHO ARE YOU?                         ")
    print("=======================================================================\n")

    for q in probes:
        print(f"ARCHITECT: \"{q}\"")
        ans = probe_identity(q)
        print(f"VIV: {ans}\n")
        print("-----------------------------------------------------------------------")
