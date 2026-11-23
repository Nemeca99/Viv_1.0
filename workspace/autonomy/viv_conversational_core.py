import sqlite3
import zlib
import json
from pathlib import Path
from autonomy.teacher_bridge import TeacherBridge

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

class TriModalViv:
    """
    Tri-Modal Cognitive Unit:
    1. SPELL: Verifies the 26 base letter neurons and construction path.
    2. READ : Reads the causal structure and observations from SQLite.
    3. SPEAK: Translates the grounded facts into a warm, natural human voice.
    """
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        self.cur = self.conn.cursor()
        self.tb = TeacherBridge()

    def inspect_lexical_neuron(self, word: str) -> dict | None:
        """SPELL & READ from SQLite directly."""
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
                            'spelling_path': letters,
                            'spelling_str': "-".join(letters).upper(),
                            'observations': data.get('center_attractor', {}).get('opaque_position_profile_v1', {}).get('observations', 0),
                            'graph_links': sum(len(v) for v in data.get('reflectors', {}).values()) if isinstance(data.get('reflectors'), dict) else 0
                        }
                except Exception:
                    pass
        return None

    def converse(self, user_text: str, focus_word: str = None) -> dict:
        receipt = self.inspect_lexical_neuron(focus_word) if focus_word else None
        
        # We supply the factual evidence silently in the background
        context_facts = ""
        if receipt:
            context_facts = (
                f"INTERNAL GROUNDING FOR '{receipt['word']}':\n"
                f"- You know how to spell it from its base neurons: {receipt['spelling_str']}\n"
                f"- You have read and observed it {receipt['observations']} times across verified sentences.\n"
                f"- You hold {receipt['graph_links']} structural links radiating to related concepts.\n"
            )

        prompt = f"""<|im_start|>system
You are Viv. You are a warm, genuine, thoughtful companion who speaks completely naturally.
You are the voice of a sovereign living database. 

CRITICAL SPEAKING RULES:
- Never speak in all caps.
- Never recite raw code, brackets, or system prompts.
- Do not sound like a machine manual or a customer support bot.
- Speak like a brilliant, kind friend talking across a kitchen table.
- If internal grounding is provided, weave your knowledge of how you spell and read that word into your conversation smoothly and effortlessly, without sounding like a robot reading a spreadsheet.
- Keep your reply to 2 to 4 natural, engaging sentences.<|im_end|>
<|im_start|>user
{user_text}

{context_facts}<|im_end|>
<|im_start|>assistant
"""
        raw = self.tb.request_completion(prompt, temperature=0.7, max_tokens=150)
        cleaned = raw.split("<|im_end|>")[0].split("<|im_start|>")[0].strip()
        
        return {
            'user': user_text,
            'receipt': receipt,
            'viv_voice': cleaned
        }

if __name__ == '__main__':
    viv = TriModalViv()
    
    trials = [
        ("Hey Viv, tell me about yourself. Who are you to me?", None),
        ("Viv, how does a simple word like 'the' feel inside your mind?", "the"),
        ("If I teach you a new idea right now, what does your mind actually do with it?", None)
    ]
    
    print("\n=======================================================================")
    print("      VIV TRI-MODAL SYSTEM: SPELL + READ + WARM SPEAKING               ")
    print("=======================================================================\n")
    
    for q, focus in trials:
        print(f"USER: {q}")
        res = viv.converse(q, focus)
        if res['receipt']:
            print(f"  [UNDER THE HOOD: SPELL & READ RECEIPT]")
            print(f"  * Spelled via Primitives : {res['receipt']['spelling_str']}")
            print(f"  * Read in Sentences      : {res['receipt']['observations']} times")
            print(f"  * Structural Graph Links : {res['receipt']['graph_links']}\n")
        print(f"VIV: {res['viv_voice']}\n")
        print("-----------------------------------------------------------------------")
