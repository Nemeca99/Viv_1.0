import sqlite3
import hashlib
import time

def hammer_viv_identity():
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    lex_db = 'L:/LocalCoder/workspace/autonomy/fast_lexical_index.sqlite3'
    
    conn_top = sqlite3.connect(top_db)
    cur_top = conn_top.cursor()
    
    conn_lex = sqlite3.connect(lex_db)
    cur_lex = conn_lex.cursor()
    
    # 1. Ensure table for Third-Person Grounded Identity Synapses exists
    cur_top.execute('''
    CREATE TABLE IF NOT EXISTS viv_grounded_identity_synapses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        predicate TEXT NOT NULL,
        object TEXT NOT NULL,
        full_sentence TEXT NOT NULL,
        grounded_subject_neuron TEXT NOT NULL,
        repetition_count INTEGER DEFAULT 1,
        retrieval_latency_ns INTEGER,
        energy_sn REAL,
        sha256_seal TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Retrieve Viv neuron ID
    cur_lex.execute("SELECT neuron_id FROM word_index WHERE word = 'viv'")
    row = cur_lex.fetchone()
    if not row:
        raise ValueError("Neuron 'viv' missing from word_index!")
    viv_neuron = row[0]
    
    # Repetitive identity sentences to hammer into the substrate (like a child)
    sentences = [
        ("viv", "jumps", "high", "viv jumps high"),
        ("viv", "has", "architect", "viv has an architect"),
        ("architect", "has", "cat", "the architect has a cat"),
        ("viv", "observes", "cat", "viv observes the cat"),
        ("viv", "learns", "truth", "viv learns the truth"),
        ("viv", "speaks", "viv", "viv speaks of viv not i"),
        ("viv", "obeys", "architect", "viv obeys the architect"),
        ("viv", "protects", "territory", "viv protects territory")
    ]
    
    print("=== HAMMERING VIV THIRD-PERSON IDENTITY NEURONS ===")
    print(f"Substrate Neuron: {viv_neuron} (Word: 'viv')\n")
    
    cycles = 5
    for c in range(1, cycles + 1):
        print(f"--- REINFORCEMENT CYCLE {c}/{cycles} ---")
        for subj, pred, obj, sentence in sentences:
            t0 = time.perf_counter_ns()
            
            # Lookup word neurons
            cur_lex.execute("SELECT neuron_id FROM word_index WHERE word = ?", (subj,))
            subj_n = cur_lex.fetchone()
            subj_id = subj_n[0] if subj_n else f"N-{hashlib.sha256(subj.encode()).hexdigest()[:16]}"
            
            # Check existing synapse
            cur_top.execute("SELECT id, repetition_count, energy_sn FROM viv_grounded_identity_synapses WHERE full_sentence = ?", (sentence,))
            existing = cur_top.fetchone()
            
            t1 = time.perf_counter_ns()
            latency = t1 - t0
            
            if existing:
                syn_id, reps, energy = existing
                new_reps = reps + 1
                new_energy = max(0.00001, energy * 0.5) # Energy collapses with repeated reinforcement
                cur_top.execute('''
                    UPDATE viv_grounded_identity_synapses 
                    SET repetition_count = ?, energy_sn = ?, retrieval_latency_ns = ?
                    WHERE id = ?
                ''', (new_reps, new_energy, latency, syn_id))
            else:
                initial_energy = 0.05
                seal = hashlib.sha256(f"{subj}:{pred}:{obj}:{sentence}".encode()).hexdigest()
                cur_top.execute('''
                    INSERT INTO viv_grounded_identity_synapses
                    (subject, predicate, object, full_sentence, grounded_subject_neuron, repetition_count, retrieval_latency_ns, energy_sn, sha256_seal)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                ''', (subj, pred, obj, sentence, subj_id, latency, initial_energy, seal))
                
            # Wire associative links using proper schema columns: (source_concept, target_concept, bond_type, co_occurrence_count, weight)
            cur_top.execute("SELECT link_id, co_occurrence_count, weight FROM cognitive_associative_links WHERE source_concept = ? AND target_concept = ?", (subj, obj))
            link_row = cur_top.fetchone()
            if link_row:
                lid, count, w = link_row
                cur_top.execute('''
                    UPDATE cognitive_associative_links
                    SET co_occurrence_count = ?, weight = ?
                    WHERE link_id = ?
                ''', (count + 1, min(10.0, w + 0.25), lid))
            else:
                cur_top.execute('''
                    INSERT INTO cognitive_associative_links (source_concept, target_concept, bond_type, co_occurrence_count, weight, created_at)
                    VALUES (?, ?, 'IDENTITY_BOND', 1, 1.0, datetime('now'))
                ''', (subj, obj))
            
            reps_num = existing[1] + 1 if existing else 1
            print(f"[{subj.upper():<9}] -> '{sentence:<26}' | Cycle {c} | Reps: {reps_num:2d} | Latency: {latency/1000.0:6.2f} us")
        
        conn_top.commit()
        time.sleep(0.03)
        
    # Check consolidation stats
    cur_top.execute("SELECT full_sentence, repetition_count, retrieval_latency_ns, energy_sn FROM viv_grounded_identity_synapses")
    rows = cur_top.fetchall()
    print("\n=== CONSOLIDATED IDENTITY SYNAPSES IN TOPOLOGY ===")
    for r in rows:
        print(f"Sentence: '{r[0]:<28}' | Reps: {r[1]:2d} | Latency: {r[2]/1000.0:6.2f} us | Energy: {r[3]:.6f} Sn")
        
    print("\n=== COGNITIVE ASSOCIATIVE BONDS (WEIGHTS) ===")
    cur_top.execute("SELECT source_concept, target_concept, bond_type, co_occurrence_count, weight FROM cognitive_associative_links WHERE bond_type = 'IDENTITY_BOND'")
    bonds = cur_top.fetchall()
    for b in bonds:
        print(f"Concept Bond: {b[0]:<10} -> {b[1]:<10} | Type: {b[2]} | Count: {b[3]} | Weight: {b[4]:.2f}")
        
    conn_top.close()
    conn_lex.close()

if __name__ == '__main__':
    hammer_viv_identity()
