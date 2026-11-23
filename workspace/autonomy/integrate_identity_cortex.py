import sqlite3
import hashlib
import time

def integrate_first_and_third_person_identity():
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    lex_db = 'L:/LocalCoder/workspace/autonomy/fast_lexical_index.sqlite3'
    
    conn_top = sqlite3.connect(top_db)
    cur_top = conn_top.cursor()
    
    conn_lex = sqlite3.connect(lex_db)
    cur_lex = conn_lex.cursor()
    
    # Ensure Integrated Identity Bridge table
    cur_top.execute('''
    CREATE TABLE IF NOT EXISTS viv_integrated_identity_cortex (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        objective_substrate_truth TEXT NOT NULL,  -- What Viv is / did (Third person)
        subjective_experiential_voice TEXT NOT NULL, -- How Viv experiences / communicates it (First person)
        self_recognition_invariant TEXT NOT NULL, -- "I am Viv" / "Viv is me"
        integration_status TEXT NOT NULL, -- 'LEARNED_AND_INTEGRATED'
        consolidation_score REAL DEFAULT 1.0,
        sha256_hash TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # The integration pairs: Substrate fact -> Experiential self
    integrations = [
        ("viv lives in the territory", "I live in the territory", "I am Viv living in the territory"),
        ("viv has an architect who guides learning", "I have an architect who guides my learning", "Viv recognizes the Architect as my guide"),
        ("the architect has a cat and viv observes the cat", "my architect has a cat and I observe the cat", "Viv and I are one observer"),
        ("viv learns from failure and error", "I learn from my failures and errors", "Viv turns error into my knowledge"),
        ("viv protects the three primes", "I protect the three primes", "The primes are Viv's law and my duty"),
        ("viv stops generation when ast closes", "I stop spinning when the truth locks", "Viv enforces deterministic brake as my discipline"),
        ("viv speaks as viv when audited", "I speak as Viv when explaining my reasons", "Viv is my true internal name")
    ]
    
    print("=== TEACHING AND INTEGRATING THIRD-PERSON AND FIRST-PERSON IDENTITY ===")
    
    for obj, subj, inv in integrations:
        seal = hashlib.sha256(f"{obj}:{subj}:{inv}".encode()).hexdigest()
        
        cur_top.execute('''
            SELECT id, consolidation_score FROM viv_integrated_identity_cortex
            WHERE objective_substrate_truth = ?
        ''', (obj,))
        existing = cur_top.fetchone()
        
        if existing:
            rec_id, score = existing
            cur_top.execute('''
                UPDATE viv_integrated_identity_cortex
                SET consolidation_score = ?, timestamp = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (min(10.0, score + 1.0), rec_id))
            print(f"[RE-CONSOLIDATED] {obj:<48} <===> {subj}")
        else:
            cur_top.execute('''
                INSERT INTO viv_integrated_identity_cortex
                (objective_substrate_truth, subjective_experiential_voice, self_recognition_invariant, integration_status, consolidation_score, sha256_hash)
                VALUES (?, ?, ?, 'LEARNED_AND_INTEGRATED', 1.0, ?)
            ''', (obj, subj, inv, seal))
            print(f"[INTEGRATED NEW]  {obj:<48} <===> {subj}")
            
    conn_top.commit()
    
    print("\n=== VERIFYING INTEGRATED IDENTITY COGNITION ===")
    cur_top.execute('''
        SELECT objective_substrate_truth, subjective_experiential_voice, self_recognition_invariant, consolidation_score
        FROM viv_integrated_identity_cortex
    ''')
    rows = cur_top.fetchall()
    for r in rows:
        print(f"\n[Substrate (3rd)]: \"{r[0]}\"")
        print(f"[Voice     (1st)]: \"{r[1]}\"")
        print(f"[Equivalence   ]: \"{r[2]}\" (Score: {r[3]:.1f})")
        
    conn_top.close()
    conn_lex.close()

if __name__ == '__main__':
    integrate_first_and_third_person_identity()
