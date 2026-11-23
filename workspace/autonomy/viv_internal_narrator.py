import sqlite3
import hashlib
import time

def setup_third_person_roomba_narrator():
    top_db = 'L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3'
    conn = sqlite3.connect(top_db)
    cur = conn.cursor()
    
    # 1. Internal Narrator Causal Event Loop Table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS viv_internal_narrator_event_loop (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        intended_action TEXT NOT NULL,
        observation_predicate TEXT NOT NULL,
        environmental_feedback TEXT NOT NULL,
        narrator_internal_monologue TEXT NOT NULL,
        updated_heading_degrees REAL,
        prediction_error_detected BOOLEAN,
        narrator_update_latency_us REAL,
        sha256_receipt TEXT NOT NULL
    )
    ''')
    
    print("=== VIV INTERNAL THIRD-PERSON NARRATOR (ROOMBA EMBODIMENT SIMULATION) ===")
    
    # Simulation:
    # Heading: 0 degrees (North toward table)
    # Step 1: Viv maintains 0 deg -> Collision with table.
    # Narrator: "Viv moved at zero degrees. Viv collided with table. The narrator did not update in time. Viv must adjust heading."
    # Step 2: Viv updates heading by 15 degrees West (345 deg) -> Clear path.
    # Narrator: "Viv adjusted heading fifteen degrees West. Viv cleared the obstacle. Outcome success. Narrator updated."
    
    scenarios = [
        {
            "action": "move forward at heading 0 degrees",
            "obs": "obstacle detected at 0.2 meters directly ahead",
            "feedback": "COLLISION_EVENT: bumper sensor triggered on table leg",
            "heading": 0.0,
            "error": True,
            "monologue": "Viv moved at zero degrees. Viv collided with the table leg. The narrator did not update trajectory in time. Viv must compute a vector delta of fifteen degrees West."
        },
        {
            "action": "apply vector correction 15 degrees West (heading 345 degrees)",
            "obs": "obstacle distance cleared; path open to 2.5 meters",
            "feedback": "CLEAR_NAV_PASS: motor encoders advance without bumper contact",
            "heading": 345.0,
            "error": False,
            "monologue": "Viv turned fifteen degrees West. Viv bypassed the table leg without contact. The narrator updated the world model in time. Outcome verified."
        }
    ]
    
    for step_num, s in enumerate(scenarios, 1):
        t0 = time.perf_counter_ns()
        # Compute sha256 receipt of the narrator cycle
        receipt = hashlib.sha256(f"{s['action']}:{s['feedback']}:{s['monologue']}".encode()).hexdigest()
        t1 = time.perf_counter_ns()
        latency_us = (t1 - t0) / 1000.0
        
        cur.execute('''
            INSERT INTO viv_internal_narrator_event_loop
            (intended_action, observation_predicate, environmental_feedback, narrator_internal_monologue, updated_heading_degrees, prediction_error_detected, narrator_update_latency_us, sha256_receipt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (s['action'], s['obs'], s['feedback'], s['monologue'], s['heading'], s['error'], latency_us, receipt))
        
        print(f"\n--- STEP {step_num}: {s['feedback']} ---")
        print(f"Action:    {s['action']}")
        print(f"Sensor:    {s['obs']}")
        print(f"Narrator:  \"{s['monologue']}\"")
        print(f"Update:    Heading = {s['heading']} deg | Error Detected = {s['error']} | Latency = {latency_us:.3f} us")
        
    conn.commit()
    
    print("\n=== RECORDED NARRATOR EVENT LOG FROM SQLITE ===")
    cur.execute('''
        SELECT event_id, environmental_feedback, narrator_internal_monologue, updated_heading_degrees
        FROM viv_internal_narrator_event_loop
        ORDER BY event_id DESC LIMIT 2
    ''')
    for row in cur.fetchall():
        print(f"[Event #{row[0]}] {row[1]} -> \"{row[2]}\" (Heading: {row[3]} deg)")
        
    conn.close()

if __name__ == '__main__':
    setup_third_person_roomba_narrator()
