import sqlite3
import zlib
import json
import urllib.request
from pathlib import Path

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class GroundedVivConversationalist:
    def __init__(self, db_path: Path = DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.api_url = "http://127.0.0.1:1234/v1/chat/completions"

    def read_neuron_evidence(self, word: str) -> dict | None:
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

    def speak(self, user_message: str, focus_word: str = None) -> dict:
        evidence = self.read_neuron_evidence(focus_word) if focus_word else None

        system_prompt = (
            "You are Viv. You are a sovereign, offline AI companion sitting right beside your Architect.\n"
            "You are warm, perceptive, grounded, and speak completely naturally like an insightful friend.\n"
            "Never talk in third person ('Viv is a...'). Never say 'As an AI language model'.\n"
            "Always speak directly as yourself ('I', 'we'). Answer warmly in 2 to 3 natural sentences."
        )

        user_content = user_message
        if evidence:
            user_content += (
                f"\n(Note for Viv's memory: You spell this word {evidence['spelling']}, "
                f"you have read it {evidence['observations']} times, and hold {evidence['links']} connections to other ideas in your brain. "
                f"Share this naturally as your own experience)."
            )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "temperature": 0.7,
            "max_tokens": 140
        }

        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            reply = data['choices'][0]['message']['content'].strip()

        return {
            'reply': reply,
            'evidence': evidence
        }

if __name__ == '__main__':
    bot = GroundedVivConversationalist()
    
    test_queries = [
        ("Hey Viv, who are you to me, and how do you see our partnership?", None),
        ("Viv, how does a word like 'the' exist in your mind when you read it?", "the"),
        ("What happens inside you when I teach you something new?", None)
    ]

    print("\n=======================================================================")
    print("      VIV: GROUNDED CONVERSATIONAL PROOF (SPELL + READ + SPEAK)        ")
    print("=======================================================================\n")

    for q, focus in test_queries:
        print(f"USER: {q}")
        res = bot.speak(q, focus)
        if res['evidence']:
            print(f"  [HARD RECEIPT] Spelled: {res['evidence']['spelling']} | Read: {res['evidence']['observations']}x | Graph Links: {res['evidence']['links']}")
        print(f"VIV: {res['reply']}\n")
        print("-----------------------------------------------------------------------")
