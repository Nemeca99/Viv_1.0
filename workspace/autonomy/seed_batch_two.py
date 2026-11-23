import sqlite3
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def seed_next_evolution_batch():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    now_str = datetime.now().isoformat()

    # The 3 Fundamental Sensorimotor Gaps:
    # 1. Structured JSON Serializer (Data Exchange)
    # 2. SHA-256 State Hashing (Self-Integrity Check)
    # 3. Rust Monotonic Counter (Thread-Safe Hardware State)
    new_curriculum = [
        (
            "CHALLENGE_04_JSON_SAFE_PARSE",
            "PYTHON",
            "Write a function parse_json_safe(raw_str: str) -> dict that parses JSON and returns empty dict on failure without raising exceptions.",
            """assert parse_json_safe('{"status": "ok", "val": 42}') == {"status": "ok", "val": 42}
assert parse_json_safe('invalid json {') == {}
assert parse_json_safe('') == {}
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_05_SHA256_FINGERPRINT",
            "PYTHON",
            "Write a function sha256_text(text: str) -> str that returns the uppercase hex digest of the UTF-8 input string.",
            """assert sha256_text("hello") == "2CF24DBA5FB0A30E26E83B2AC5B9E29E1B161E5C1FA7425E73043362938B9824"
assert sha256_text("") == "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_06_RUST_SAFE_MONOTONIC_COUNTER",
            "RUST",
            "Write a Rust struct MonotonicCounter with fn new(), fn increment() -> u64, and fn get() -> u64 with fn main() testing 3 increments.",
            """fn main() {
    let mut c = MonotonicCounter::new();
    assert_eq!(c.get(), 0);
    assert_eq!(c.increment(), 1);
    assert_eq!(c.increment(), 2);
    assert_eq!(c.increment(), 3);
    assert_eq!(c.get(), 3);
    println!("FIB_PASS");
}
""",
            "PENDING",
            now_str
        )
    ]

    for c in new_curriculum:
        cur.execute("""
        INSERT OR REPLACE INTO autonomous_curriculum_queue 
        (curriculum_id, domain, challenge_intent, test_harness_code, status, attempts, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (c[0], c[1], c[2], c[3], c[4], c[5]))

    conn.commit()
    pending = cur.execute("SELECT count(*) FROM autonomous_curriculum_queue WHERE status = 'PENDING'").fetchone()[0]
    conn.close()
    return pending

if __name__ == "__main__":
    p = seed_next_evolution_batch()
    print(f"Added new fundamental challenges. Pending in queue: {p}")
