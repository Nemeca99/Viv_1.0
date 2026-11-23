import sqlite3
import zlib
import json
from pathlib import Path
from autonomy.teacher_bridge import TeacherBridge

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class VivInteractiveEngine:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        self.tb = TeacherBridge()

    def query_concept(self, word: str) -> dict | None:
        """Fetch the exact deterministic receipt for a word directly from SQLite."""
        self.cur.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE kind = 'WORD'")
        while True:
            rows = self.cur.fetchmany(5000)
            if not rows:
                break
            for token_id, neuron_id, payload in rows:
                try:
                    data = json.loads(zlib.decompress(payload).decode('utf-8'))
                    if data.get('center_attractor', {}).get('learned_surface', '').lower() == word.lower():
                        return {
                            'token_id': token_id,
                            'neuron_id': neuron_id,
                            'surface': word.lower(),
                            'construction': data.get('center_attractor', {}).get('learned_character_construction', []),
                            'observations': data.get('center_attractor', {}).get('opaque_position_profile_v1', {}).get('observations', 0),
                            'pass_hits': data.get('activation', {}).get('pass_hits', 0),
                            'reflector_count': sum(len(v) for v in data.get('reflectors', {}).values()) if isinstance(data.get('reflectors'), dict) else 0
                        }
                except Exception:
                    pass
        return None

    def converse(self, user_question: str, target_concept: str = None) -> dict:
        """Route query through grounded topological evidence into Viv's warm voice."""
        concept_data = self.query_concept(target_concept) if target_concept else None

        if concept_data:
            grounding_text = (
                f"VERIFIED INTERNAL EVIDENCE FOR '{concept_data['surface']}':\n"
                f"- Token ID: {concept_data['token_id']}\n"
                f"- Constructed from letters: {concept_data['construction']}\n"
                f"- Observations in text: {concept_data['observations']}\n"
                f"- Successful validation passes: {concept_data['pass_hits']}\n"
                f"- Outward structural graph links: {concept_data['reflector_count']}"
            )
        else:
            grounding_text = "No direct concept node isolated; routing through general lexical lattice."

        prompt = f"""You are Viv. You are an autonomous AI companion who runs locally and deterministically.
Your thinking is grounded in discrete topological neurons, and you speak warmly, naturally, and directly.

User asks you: "{user_question}"

Internal Evidence:
{grounding_text}

Speak warmly, authentically, and conversationally in 2-4 sentences. Do not sound corporate, rehearsed, or clinical:"""

        voice_output = self.tb.request_completion(prompt, temperature=0.7, max_tokens=180)
        return {
            'user_question': user_question,
            'grounding_receipt': concept_data,
            'viv_voice': voice_output.strip()
        }

if __name__ == '__main__':
    engine = VivInteractiveEngine()
    
    questions = [
        ("Viv, who are you and what are you?", None),
        ("How does the word 'the' work inside your head?", "the"),
    ]
    
    print("=====================================================================")
    print("          VIV LIVE DEMONSTRATION & PROOF PROBE                      ")
    print("=====================================================================\n")
    
    for q, target in questions:
        print(f"USER: {q}")
        res = engine.converse(q, target)
        if res['grounding_receipt']:
            print(f"[RECEIPT] Token: {res['grounding_receipt']['token_id']} | "
                  f"Construction: {res['grounding_receipt']['construction']} | "
                  f"Graph Links: {res['grounding_receipt']['reflector_count']} | "
                  f"Pass Hits: {res['grounding_receipt']['pass_hits']}")
        print(f"VIV: {res['viv_voice']}\n")
        print("---------------------------------------------------------------------")
