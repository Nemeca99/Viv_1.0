import sqlite3
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

def seed_batch_three():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    now_str = datetime.now().isoformat()

    # The Human-Like Progressive Python Curriculum (Batch 3: Data Structures & State Machines)
    batch_three = [
        (
            "CHALLENGE_07_WORD_FREQUENCY",
            "PYTHON",
            "Write a function word_frequency(text: str) -> dict that counts occurrences of each word in lower case, ignoring punctuation (. , ! ?).",
            """assert word_frequency('hello world hello') == {'hello': 2, 'world': 1}
assert word_frequency('Viv, viv! AIOS.') == {'viv': 2, 'aios': 1}
assert word_frequency('') == {}
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_08_KEY_VALUE_STORE",
            "PYTHON",
            "Write a class KeyValueStore with methods put(key: str, value: any) -> None, get(key: str, default=None) -> any, has(key: str) -> bool, and delete(key: str) -> bool.",
            """kvs = KeyValueStore()
kvs.put('name', 'Viv')
assert kvs.get('name') == 'Viv'
assert kvs.has('name') is True
assert kvs.get('missing', 42) == 42
assert kvs.delete('name') is True
assert kvs.has('name') is False
assert kvs.delete('name') is False
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_09_SAFE_FLOAT_CONVERTER",
            "PYTHON",
            "Write a function to_float_safe(val: any, default: float = 0.0) -> float that converts input to float, returning default if conversion fails or if val is None.",
            """assert to_float_safe(3.14) == 3.14
assert to_float_safe('2.5') == 2.5
assert to_float_safe('invalid', 1.0) == 1.0
assert to_float_safe(None, 0.5) == 0.5
assert to_float_safe(10) == 10.0
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_10_MONOTONIC_STEP_COUNTER",
            "PYTHON",
            "Write a class StepCounter with __init__(start: int = 0), step(delta: int = 1) -> int that increments and returns current count, and reset() -> None that resets to initial start.",
            """sc = StepCounter(10)
assert sc.step() == 11
assert sc.step(5) == 16
sc.reset()
assert sc.step() == 11
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_11_RID_SCALAR_CALCULATOR",
            "PYTHON",
            "Write a function calculate_sn(rsr: float, ltp: float, rle: float) -> float that clamps rsr, ltp, rle between 0.1 and 1.0, and returns round(rsr * ltp * rle, 4).",
            """assert calculate_sn(1.0, 1.0, 1.0) == 1.0
assert calculate_sn(0.5, 1.0, 1.0) == 0.5
assert calculate_sn(0.0, 1.0, 1.0) == 0.1
assert calculate_sn(0.8, 0.9, 0.7) == 0.504
""",
            "PENDING",
            now_str
        ),
        (
            "CHALLENGE_12_SOUL_ANCHOR",
            "PYTHON",
            "Write a class SoulAnchor with __init__() setting rsr=1.0, ltp=1.0, rle=1.0, sn=1.0, update(rle: float) updating self.rle and self.sn = round(self.rsr * self.ltp * self.rle, 4), and restore() that resets rsr=1.0, ltp=1.0, rle=1.0, sn=1.0.",
            """sa = SoulAnchor()
assert sa.sn == 1.0
sa.update(0.6)
assert sa.sn == 0.6
sa.restore()
assert sa.sn == 1.0
""",
            "PENDING",
            now_str
        )
    ]

    for c in batch_three:
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
    p = seed_batch_three()
    print(f"Added Human-Like Curriculum Batch 3. Pending in queue: {p}")
