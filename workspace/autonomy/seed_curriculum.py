import sqlite3
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def init_curriculum():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS autonomous_curriculum_queue (
        curriculum_id TEXT PRIMARY KEY,
        domain TEXT,
        challenge_intent TEXT,
        test_harness_code TEXT,
        status TEXT,
        attempts INTEGER DEFAULT 0,
        graduated_primitive_id TEXT,
        created_at TEXT
    )
    """)

    now_str = datetime.now().isoformat()
    curriculum = [
        (
            "CHALLENGE_01_REVERSE_WORDS",
            "PYTHON",
            "Write a function reverse_words(s: str) -> str that reverses the order of words in a sentence.",
            """assert reverse_words('hello world') == 'world hello'
assert reverse_words('viv is alive') == 'alive is viv'
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_02_FILTER_PRIMES",
            "PYTHON",
            "Write a function filter_primes(numbers: list) -> list that returns only prime numbers.",
            """assert filter_primes([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == [2, 3, 5, 7]
assert filter_primes([0, 1]) == []
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_03_RUST_FIBONACCI",
            "RUST",
            "Write a Rust function fn fibonacci(n: u32) -> u32 with fn main() testing fibonacci(10) == 55.",
            """fn main() {
    assert_eq!(fibonacci(10), 55);
    println!("FIB_PASS");
}
""",
            "PENDING",
            now_str
        )
    ]

    for c in curriculum:
        cur.execute("""
        INSERT OR REPLACE INTO autonomous_curriculum_queue 
        (curriculum_id, domain, challenge_intent, test_harness_code, status, attempts, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """, (c[0], c[1], c[2], c[3], c[4], c[5]))

    conn.commit()
    count = cur.execute("SELECT count(*) FROM autonomous_curriculum_queue").fetchone()[0]
    conn.close()
    return count

if __name__ == "__main__":
    total = init_curriculum()
    print(f"Autonomous Curriculum Queue Ready: {total} challenges in SQLite.")
