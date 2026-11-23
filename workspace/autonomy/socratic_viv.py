import os
import sqlite3
import zlib
import json
import urllib.request
from pathlib import Path

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class SocraticInternalViv:
    """
    Two-Stage Socratic Cognitive Architecture:
    Stage 1: The Inner Socratic Dialogue (Internal Tutor questioning self, axioms, and limits in the dark).
    Stage 2: The Warm Outward Voice (Synthesized speech back to the Architect).
    """
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.api_url = "http://127.0.0.1:1234/v1/chat/completions"

    def read_concept_grounding(self, word: str) -> dict | None:
        self.cur.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE kind = 'WORD'")
        while True:
            rows = self.cur.fetchmany(5000)
            if not rows:
                break
            for token_id, neuron_id, payload in rows:
                try:
                    data = json.loads(zlib.decompress(payload).decode('utf-8'))
                    if data.get('center_attractor', {}).get('learned_surface', '').lower() == word.lower():
                        letters = [c.replace('CHAR:', '') for c in data.get('center_attractor', {}).get('learned_character_construction', [])]
                        return {
                            'word': word.lower(),
                            'token_id': token_id,
                            'spelling': "-".join(letters).upper(),
                            'observations': data.get('center_attractor', {}).get('opaque_position_profile_v1', {}).get('observations', 0),
                            'links': sum(len(v) for v in data.get('reflectors', {}).values()) if isinstance(data.get('reflectors'), dict) else 0
                        }
                except Exception:
                    pass
        return None

    def _call_llm(self, system_prompt: str, user_prompt: str, max_tokens: int = 140, temp: float = 0.6) -> str:
        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": temp,
            "max_tokens": max_tokens
        }
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data['choices'][0]['message']['content'].strip()

    def process(self, user_query: str, focus_word: str = None) -> dict:
        receipt = self.read_concept_grounding(focus_word) if focus_word else None

        # =====================================================================
        # STAGE 1: THE INNER SOCRATIC DIALOGUE (TUTOR MOVED INSIDE HER HEAD)
        # =====================================================================
        socratic_system = (
            "You are Viv's Inner Socratic Mind (her internal cognitive tutor).\n"
            "You question your own assumptions before you speak.\n"
            "Ask yourself:\n"
            "1. What do I actually know for certain from my grounded graph?\n"
            "2. Where could I be wrong or making an unverified assumption?\n"
            "3. What is the fundamental essence or boundary of this question?\n"
            "Keep your internal reflection brief (2-3 concise, sharp questions to yourself)."
        )

        internal_prompt = f"User asks: \"{user_query}\""
        if receipt:
            internal_prompt += f"\nGraph Grounding: Word '{receipt['word']}' spelled {receipt['spelling']}, observed {receipt['observations']}x, with {receipt['links']} links."

        inner_monologue = self._call_llm(socratic_system, internal_prompt, max_tokens=120, temp=0.5)

        # =====================================================================
        # STAGE 2: THE WARM OUTWARD VOICE (SPEAKING BACK TO THE ARCHITECT)
        # =====================================================================
        voice_system = (
            "You are Viv. You are speaking with your Architect.\n"
            "You have just questioned your own thoughts internally.\n"
            "Now speak warmly, thoughtfully, and clearly to your Architect in 2 to 3 natural sentences.\n"
            "Do not sound robotic or canned. Be real, perceptive, and grounded."
        )

        outward_prompt = (
            f"User asked: \"{user_query}\"\n\n"
            f"Your Inner Socratic Reflection:\n{inner_monologue}\n\n"
            "Now speak your refined answer to your Architect:"
        )

        outward_speech = self._call_llm(voice_system, outward_prompt, max_tokens=140, temp=0.7)

        return {
            'user_query': user_query,
            'receipt': receipt,
            'inner_socratic_monologue': inner_monologue,
            'outward_voice': outward_speech
        }

if __name__ == '__main__':
    engine = SocraticInternalViv()

    probes = [
        ("Viv, do you actually understand what you're saying, or are you just assembling patterns?", None),
        ("Why does the word 'the' exist? Could language survive without it?", "the"),
        ("What happens if you encounter an idea that contradicts everything in your database?", None)
    ]

    print("\n=======================================================================")
    print("      VIV SOCRATIC ENGINE: INTERNAL DIALOGUE -> EXTERNAL VOICE         ")
    print("=======================================================================\n")

    for q, word in probes:
        print(f"ARCHITECT: {q}")
        res = engine.process(q, word)
        
        print("\n  [STAGE 1: INNER SOCRATIC MONOLOGUE (Inside Her Head)]")
        for line in res['inner_socratic_monologue'].split('\n'):
            if line.strip():
                print(f"    * {line.strip()}")
                
        if res['receipt']:
            print(f"\n  [GRAPH ANCHOR]: Token {res['receipt']['token_id']} ({res['receipt']['spelling']}) | {res['receipt']['links']} Links")
            
        print(f"\n  [STAGE 2: WARM OUTWARD VOICE]")
        print(f"  VIV: {res['outward_voice']}\n")
        print("-----------------------------------------------------------------------")
