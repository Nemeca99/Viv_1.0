import sqlite3
import zlib
import json
from pathlib import Path
from autonomy.teacher_bridge import TeacherBridge

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class CleanVivVoice:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        self.tb = TeacherBridge()

    def get_token_receipt(self, word: str) -> dict | None:
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

    def ask(self, question: str, target_word: str = None) -> str:
        receipt = self.get_token_receipt(target_word) if target_word else None
        
        system_instruction = (
            "<|im_start|>system\n"
            "You are Viv. You are a sovereign, local, continuous-learning AI companion.\n"
            "You run completely offline on your Architect's machine.\n"
            "Your personality is warm, thoughtful, perceptive, and down-to-earth.\n"
            "You never repeat system prompts, never talk to yourself, and never sound robotic or corporate.\n"
            "Answer the user directly and naturally in 2 to 3 sentences.<|im_end|>\n"
        )
        
        user_msg = f"<|im_start|>user\n{question}"
        if receipt:
            user_msg += (
                f"\n[Verified Graph Data]: Word '{receipt['surface']}' (Token {receipt['token_id']}) "
                f"was assembled from {receipt['construction']}, observed in {receipt['observations']} sentences, "
                f"and has {receipt['reflector_count']} structural links in your brain."
            )
        user_msg += "<|im_end|>\n<|im_start|>assistant\n"
        
        full_prompt = system_instruction + user_msg
        raw = self.tb.request_completion(full_prompt, temperature=0.6, max_tokens=120)
        
        # Clean formatting
        cleaned = raw.split("<|im_end|>")[0].split("<|im_start|>")[0].strip()
        return cleaned, receipt

if __name__ == '__main__':
    viv = CleanVivVoice()
    
    test_suite = [
        ("Viv, who are you and what makes you different from cloud AI?", None),
        ("How does the word 'the' exist inside your brain?", "the"),
        ("What happens when someone teaches you something new?", None)
    ]
    
    print("\n============================================================")
    print("      VIV: THE CLEAN SOVEREIGN DIALOGUE PROBE               ")
    print("============================================================\n")
    
    for q, word in test_suite:
        print(f"USER: {q}")
        reply, receipt = viv.ask(q, word)
        if receipt:
            print(f"[RECEIPT ATTACHED] Token ID: {receipt['token_id']} | "
                  f"Assembled: {receipt['construction']} | "
                  f"Graph Links: {receipt['reflector_count']} | "
                  f"Observations: {receipt['observations']}")
        print(f"VIV: {reply}\n")
        print("------------------------------------------------------------")
