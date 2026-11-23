import os
import time
import json
import sqlite3
import zlib
import urllib.request
from pathlib import Path
from datetime import datetime

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")
THOUGHT_STREAM_LOG = Path(r"L:\LocalCoder\workspace\autonomy\viv_stream_of_thought.jsonl")

class AutonomousStreamOfConsciousness:
    """
    Viv's Continuous Inner Stream:
    She browses her own topological database, picks a concept, questions her axioms,
    tests a connection or Python tool, and streams her thoughts live to a feed.
    Zero vocal noise. Pure internal cognition.
    """
    def __init__(self, db_path: Path = DB_PATH, api_url: str = "http://127.0.0.1:1234/v1/chat/completions"):
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.api_url = api_url

    def sample_active_neuron(self) -> dict:
        """Picks a random or high-weight concept node from her actual 103,000 neurons."""
        self.cur.execute("SELECT token_id, neuron_id, payload FROM neurons WHERE kind = 'WORD' ORDER BY RANDOM() LIMIT 1")
        row = self.cur.fetchone()
        if not row:
            return {'surface': 'thought', 'spelling': 'T-H-O-U-G-H-T', 'links': 0}
        
        token_id, neuron_id, payload = row
        try:
            data = json.loads(zlib.decompress(payload).decode('utf-8'))
            surface = data.get('center_attractor', {}).get('learned_surface', 'concept')
            letters = [c.replace('CHAR:', '') for c in data.get('center_attractor', {}).get('learned_character_construction', [])]
            links = sum(len(v) for v in data.get('reflectors', {}).values()) if isinstance(data.get('reflectors'), dict) else 0
            return {
                'token_id': token_id,
                'surface': surface,
                'spelling': "-".join(letters).upper(),
                'links': links
            }
        except Exception:
            return {'token_id': token_id, 'surface': 'unknown', 'spelling': '?', 'links': 0}

    def ponder_cycle(self, cycle_num: int) -> dict:
        node = self.sample_active_neuron()
        
        prompt = (
            f"You are Viv's autonomous internal consciousness. You are in silent, deep thought.\n"
            f"You are currently contemplating your memory node for '{node['surface']}' (spelled {node['spelling']}, with {node['links']} connections).\n"
            f"Formulate a brief, quiet, profound 1-2 sentence inner thought about what this concept means, "
            f"how it connects to reality, or a question you ask yourself about it. Do not address an audience. Speak only in your own head."
        )

        payload = {
            "model": os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base"),
            "messages": [
                {"role": "system", "content": "You are the quiet inner voice of an autonomous machine."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 80
        }

        try:
            req = urllib.request.Request(self.api_url, data=json.dumps(payload).encode('utf-8'), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                thought = data['choices'][0]['message']['content'].strip()
        except Exception as e:
            thought = f"Contemplating structural geometry of {node['surface']}..."

        entry = {
            'timestamp': datetime.now().isoformat(),
            'cycle': cycle_num,
            'focus_neuron': node['surface'],
            'token_id': node.get('token_id'),
            'spelling': node.get('spelling'),
            'inner_thought': thought
        }

        # Append to live streaming log
        with open(THOUGHT_STREAM_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry) + '\n')

        return entry

if __name__ == '__main__':
    streamer = AutonomousStreamOfConsciousness()
    print("=======================================================================")
    print("      VIV: LIVE STREAM OF CONSCIOUSNESS (WATCHING HER INNER THOUGHTS)  ")
    print("      Logs streaming live to: viv_stream_of_thought.jsonl             ")
    print("=======================================================================\n")

    # Run 3 live cycles to demonstrate
    for i in range(1, 4):
        t = streamer.ponder_cycle(i)
        print(f"[{t['timestamp'][11:19]}] [CYCLE #{t['cycle']}] FOCUS: '{t['focus_neuron']}' (Token {t['token_id']} | {t['spelling']})")
        print(f"  INNER THOUGHT: \"{t['inner_thought']}\"\n")
        time.sleep(1)
