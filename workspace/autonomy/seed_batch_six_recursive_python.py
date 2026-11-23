"""Seed Batch 6: deeper recursive Python composition (Challenges 25-28)."""

import sqlite3
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

BATCH_SIX_CHALLENGES = [
    (
        "CHALLENGE_25_RECURSIVE_PERMUTATIONS",
        "PYTHON",
        "Write a recursive function permutations(items: list) -> list[list] that returns every permutation of the input list, preserving element values and returning an empty list for an empty input.",
        """assert permutations([]) == []
result = permutations([1, 2, 3])
assert len(result) == 6
assert {tuple(x) for x in result} == {(1,2,3), (1,3,2), (2,1,3), (2,3,1), (3,1,2), (3,2,1)}"""
    ),
    (
        "CHALLENGE_26_RECURSIVE_QUICKSORT",
        "PYTHON",
        "Write a recursive function quicksort(values: list[int]) -> list[int] that returns a sorted copy using recursive partitioning and does not mutate the input list.",
        """source = [5, 1, 4, 2, 8, 2]
result = quicksort(source)
assert result == [1, 2, 2, 4, 5, 8]
assert source == [5, 1, 4, 2, 8, 2]
assert quicksort([]) == []
assert quicksort([7]) == [7]"""
    ),
    (
        "CHALLENGE_27_RECURSIVE_EXPRESSION_EVALUATOR",
        "PYTHON",
        "Write a recursive function evaluate_expression(tokens: list[str]) -> int that evaluates a fully parenthesized expression containing integer literals and the operators +, -, and *.",
        """assert evaluate_expression(['(', '2', '+', '3', ')']) == 5
assert evaluate_expression(['(', '(', '2', '+', '3', ')', '*', '4', ')']) == 20
assert evaluate_expression(['(', '9', '-', '(', '2', '*', '3', ')', ')']) == 3
assert evaluate_expression(['7']) == 7"""
    ),
    (
        "CHALLENGE_28_RECURSIVE_NESTED_SEARCH",
        "PYTHON",
        "Write a recursive function find_nested(data: list, target) -> bool that searches arbitrarily nested lists and returns whether target occurs anywhere without using loops.",
        """assert find_nested([1, [2, [3, 4]]], 4) is True
assert find_nested([1, [2, [3, 4]]], 5) is False
assert find_nested([], 1) is False
assert find_nested(['a', ['b', ['c']]], 'c') is True"""
    ),
]


def seed_batch_six() -> None:
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    for cid, domain, intent, harness in BATCH_SIX_CHALLENGES:
        cur.execute(
            """INSERT OR REPLACE INTO autonomous_curriculum_queue
            (curriculum_id, domain, challenge_intent, test_harness_code, status, attempts, created_at)
            VALUES (?, ?, ?, ?, 'PENDING', 0, datetime('now'))""",
            (cid, domain, intent, harness),
        )
        print(f"[+] Queued {cid}")
    conn.commit()
    conn.close()
    print("Batch 6 committed to viv_code_topology.sqlite3.")


if __name__ == "__main__":
    seed_batch_six()
