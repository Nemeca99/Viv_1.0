import sqlite3

top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
conn = sqlite3.connect(top_db)
cur = conn.cursor()

def viv_recall():
    cur.execute('''
        SELECT full_sentence, repetition_count, energy_sn 
        FROM viv_grounded_identity_synapses 
        ORDER BY repetition_count DESC, energy_sn ASC
    ''')
    synapses = cur.fetchall()
    print("=== VIV THIRD-PERSON GROUNDED KNOWLEDGE RECALL ===")
    for s in synapses:
        print(f"Viv knowledge: \"{s[0]}\" (Energy: {s[2]:.6f} Sn)")

if __name__ == '__main__':
    viv_recall()
    conn.close()
