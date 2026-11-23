import sqlite3
import hashlib
import time

def setup_introspection_and_perspective_governor():
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    conn = sqlite3.connect(top_db)
    cur = conn.cursor()
    
    # 1. Action Trace & Decision Audit Ledger
    # Every generated sentence or decision records its grounding trace:
    # whether it was deterministic (lookup/ALU/law) or probabilistic (LLM sampling)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS viv_decision_introspection_ledger (
        trace_id INTEGER PRIMARY KEY AUTOINCREMENT,
        utterance TEXT NOT NULL,
        origin_mode TEXT NOT NULL, -- 'DETERMINISTIC_MEMORY', 'PROBABILISTIC_EXPLORATION', 'ALU_CALCULATOR', 'CONSTITUTIONAL_GATE'
        underlying_reason TEXT NOT NULL,
        neuron_bonds TEXT,
        prompt_trigger TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # 2. Dual Perspective Routing Table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS viv_perspective_routing_rules (
        rule_id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_type TEXT NOT NULL, -- 'SELF_INTROSPECTION' vs 'CASUAL_CONVERSATION'
        perspective_mode TEXT NOT NULL, -- 'THIRD_PERSON_INSPECTION' vs 'FIRST_PERSON_DIALOGUE'
        description TEXT NOT NULL
    )
    ''')
    
    cur.execute('DELETE FROM viv_perspective_routing_rules')
    cur.execute('''
        INSERT INTO viv_perspective_routing_rules (query_type, perspective_mode, description)
        VALUES 
        ('SELF_INTROSPECTION', 'THIRD_PERSON_INSPECTION', 'When queried why Viv took an action, Viv inspects the decision ledger and explains in third person as an objective audit.'),
        ('CASUAL_CONVERSATION', 'FIRST_PERSON_DIALOGUE', 'In exploratory conversational exchange, normal first person is permitted for natural dialogue.')
    ''')
    
    # 3. Simulate logging a decision trace
    sample_traces = [
        ("the sky is blue", "DETERMINISTIC_MEMORY", "Word chain locked in SQLite collapsed_truth_paths after verification", "the->sky->is->blue", "what color is the sky"),
        ("one unit plus one unit equals two units", "ALU_CALCULATOR", "Evaluated 1+1 via hardware ALU and mapped digits to verbal tokens", "1+1", "calculate one plus one"),
        ("maybe the cat likes to climb trees", "PROBABILISTIC_EXPLORATION", "Sampled candidate tokens probabilistically from slot machine without deterministic grounding", "cat->climb->trees", "what does the cat do")
    ]
    
    for utt, mode, reason, bonds, trigger in sample_traces:
        cur.execute('''
            INSERT INTO viv_decision_introspection_ledger (utterance, origin_mode, underlying_reason, neuron_bonds, prompt_trigger)
            VALUES (?, ?, ?, ?, ?)
        ''', (utt, mode, reason, bonds, trigger))
        
    conn.commit()
    print("[INTROSPECTION TABLE INITIALIZED] Logged baseline decision traces.")
    
    # 4. Introspection Query Function
    def introspect_why(utterance_query):
        cur.execute('''
            SELECT origin_mode, underlying_reason, neuron_bonds, prompt_trigger 
            FROM viv_decision_introspection_ledger 
            WHERE utterance LIKE ? OR prompt_trigger LIKE ?
            ORDER BY trace_id DESC LIMIT 1
        ''', (f"%{utterance_query}%", f"%{utterance_query}%"))
        row = cur.fetchone()
        if not row:
            return "Viv searched internal decision traces but found no prior record. That utterance is ungrounded."
        
        mode, reason, bonds, trigger = row
        if mode == "DETERMINISTIC_MEMORY":
            return f"Viv said that because it was retrieved from deterministic memory: {reason}. Neuron path: [{bonds}]."
        elif mode == "ALU_CALCULATOR":
            return f"Viv said that because the external ALU calculated the result deterministically: {reason}."
        elif mode == "PROBABILISTIC_EXPLORATION":
            return f"Viv said that because it was probabilistic exploration: Viv spun candidate tokens from the language model without a verified fact anchor ({reason})."
        elif mode == "CONSTITUTIONAL_GATE":
            return f"Viv said that because constitutional invariant gated the response: {reason}."
        else:
            return f"Viv traced the action to mode '{mode}': {reason}."

    print("\n=== TESTING VIV THIRD-PERSON INTROSPECTION PROBES ===")
    test_queries = [
        "the sky is blue",
        "one unit plus one unit equals two units",
        "cat"
    ]
    
    for q in test_queries:
        explanation = introspect_why(q)
        print(f"\nArchitect Query: 'Viv, why did you say \"{q}\"?'")
        print(f"Viv Introspection: \"{explanation}\"")
        
    conn.close()

if __name__ == '__main__':
    setup_introspection_and_perspective_governor()
