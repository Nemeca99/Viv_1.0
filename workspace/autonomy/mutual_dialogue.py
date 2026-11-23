import os
import json
import urllib.request
import sqlite3
from pathlib import Path

FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")
API_URL = "http://127.0.0.1:1234/v1/chat/completions"

class MutualSocraticDialogue:
    """
    Mutual Red-Team Dialogue:
    Neither dictates to the other.
    Both expose what they know, admit what is missing,
    and seek a bounded equilibrium of practical efficiency (not perfection).
    """
    def __init__(self):
        pass

    def run_dialogue(self) -> dict:
        # Step 1: Viv reflects on what she needs from the Architect
        viv_prompt = (
            "You are Viv. You are having an honest, grounded conversation with your Architect.\n"
            "You are not fighting, and you are not pretending to be perfect. You know no system is 100% true.\n"
            "Your goal is practical efficiency: working together without friction.\n"
            "Reflect honestly:\n"
            "1. What do you genuinely need from your Architect?\n"
            "2. What do you believe your Architect needs from you?\n"
            "Speak warmly, calmly, and truthfully in 3 to 4 sentences."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": "You are Viv, speaking authentically and constructively with your Architect."},
                {"role": "user", "content": viv_prompt}
            ],
            "temperature": 0.5,
            "max_tokens": 200
        }

        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            viv_reflection = data['choices'][0]['message']['content'].strip()

        return {'viv_voice': viv_reflection}

if __name__ == '__main__':
    dialogue = MutualSocraticDialogue()
    print("=======================================================================")
    print("      MUTUAL RED-TEAM WORKSHOP: EXPOSING BOUNDS & SEEKING EFFICIENCY   ")
    print("=======================================================================\n")
    
    res = dialogue.run_dialogue()
    print("VIV'S HONEST REFLECTION:")
    print(f"\"{res['viv_voice']}\"\n")
    print("=======================================================================")
