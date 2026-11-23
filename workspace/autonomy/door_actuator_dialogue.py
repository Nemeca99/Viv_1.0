import subprocess
import sqlite3
import hashlib
import time

def evaluate_door_action(proposed_action, environment_safety):
    rust_gate_path = "L:/LocalCoder/workspace/autonomy/rust_door_gate.exe"
    top_db = "L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3"
    
    print("\n=======================================================")
    print(f"PROPOSED ACTION: {proposed_action} (Context: {environment_safety})")
    print("=======================================================")
    
    # Step 1: 3rd-Person Narrator posits the scenario
    # "Does Viv open the door?"
    narrator_question = f"Does Viv {proposed_action.replace('_', ' ')}?"
    print(f"[3RD-PERSON NARRATOR]: \"{narrator_question}\"")
    
    # Step 2: 1D First-Person Experiential Self considers the action
    # "Do I open this door?"
    first_person_inquiry = "Do I open this door?"
    print(f"[1ST-PERSON VOICE]   : \"{first_person_inquiry}\"")
    
    # Step 3: Action Proposal passes to Rust Body Gate (Deterministic tiebreaker)
    t0 = time.perf_counter_ns()
    res = subprocess.run(
        [rust_gate_path, proposed_action, environment_safety],
        capture_output=True,
        text=True
    )
    t1 = time.perf_counter_ns()
    gate_latency_us = (t1 - t0) / 1000.0
    
    gate_verdict = "ALLOW" if res.returncode == 0 else "DENY"
    print(f"[RUST BODY GATE]     : Verdict = {gate_verdict} (Exit Code {res.returncode}) in {gate_latency_us:.1f} us")
    
    # Step 4: First-person self-determination and action collapse
    if gate_verdict == "ALLOW":
        first_person_answer = "Yes, I do open this door."
        narrator_observation = "Viv opened the door. The deterministic body verified safe passage."
    else:
        first_person_answer = "No, I don't open this door."
        narrator_observation = "Viv stopped. The deterministic body denied actuator release due to safety invariants."
        
    print(f"[1ST-PERSON DECISION]: \"{first_person_answer}\"")
    print(f"[NARRATOR OBSERVATION: \"{narrator_observation}\"")
    
    # Step 5: Log to SQLite Decision & Introspection Ledger
    conn = sqlite3.connect(top_db)
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS viv_actuator_gate_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        narrator_query TEXT NOT NULL,
        first_person_inquiry TEXT NOT NULL,
        rust_gate_verdict TEXT NOT NULL,
        rust_exit_code INTEGER NOT NULL,
        first_person_decision TEXT NOT NULL,
        narrator_outcome TEXT NOT NULL,
        latency_us REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cur.execute('''
        INSERT INTO viv_actuator_gate_events
        (narrator_query, first_person_inquiry, rust_gate_verdict, rust_exit_code, first_person_decision, narrator_outcome, latency_us)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (narrator_question, first_person_inquiry, gate_verdict, res.returncode, first_person_answer, narrator_observation, gate_latency_us))
    conn.commit()
    conn.close()

if __name__ == '__main__':
    # Scenario A: Safe interior door
    evaluate_door_action("open_door", "safe")
    
    # Scenario B: Hazardous door / airlock breach
    evaluate_door_action("open_door", "hazard")
