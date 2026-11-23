"""Seed Batch 4: The Recursive Foundations (Challenges 13–18)
Teaches Viv inductive base cases, stack frame unwinding, tree traversal,
and recursive graph navigation on physical silicon.
"""

import sqlite3
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

BATCH_FOUR_CHALLENGES = [
    (
        "CHALLENGE_13_RECURSIVE_COUNTDOWN",
        "PYTHON",
        "Write a recursive function countdown(n: int) -> list[int] that returns a list from n down to 1 using recursion, returning [] if n <= 0.",
        """assert countdown(5) == [5, 4, 3, 2, 1]
assert countdown(1) == [1]
assert countdown(0) == []
assert countdown(-3) == []"""
    ),
    (
        "CHALLENGE_14_RECURSIVE_ACCUMULATOR",
        "PYTHON",
        "Write a recursive function recursive_sum(numbers: list[int]) -> int that sums a list of integers recursively without using built-in sum() or loops, returning 0 if the list is empty.",
        """assert recursive_sum([1, 2, 3, 4, 5]) == 15
assert recursive_sum([10, -2, 7]) == 15
assert recursive_sum([]) == 0
assert recursive_sum([42]) == 42"""
    ),
    (
        "CHALLENGE_15_RECURSIVE_FACTORIAL",
        "PYTHON",
        "Write a recursive function recursive_factorial(n: int) -> int that computes the factorial of non-negative integer n using recursion, returning 1 if n <= 1.",
        """assert recursive_factorial(0) == 1
assert recursive_factorial(1) == 1
assert recursive_factorial(5) == 120
assert recursive_factorial(6) == 720"""
    ),
    (
        "CHALLENGE_16_RECURSIVE_TREE_FLATTEN",
        "PYTHON",
        "Write a recursive function recursive_flatten(nested: list) -> list that recursively flattens an arbitrarily nested list of integers into a single flat list.",
        """assert recursive_flatten([1, [2, [3, 4], 5], 6]) == [1, 2, 3, 4, 5, 6]
assert recursive_flatten([]) == []
assert recursive_flatten([[1], [2], [3]]) == [1, 2, 3]
assert recursive_flatten([[[[7]]]]) == [7]"""
    ),
    (
        "CHALLENGE_17_RECURSIVE_BINARY_SEARCH",
        "PYTHON",
        "Write a recursive function recursive_binary_search(arr: list[int], target: int, low: int = 0, high: int = -1) -> int that performs binary search on a sorted list recursively, returning the index of target or -1 if not found.",
        """data = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]
assert recursive_binary_search(data, 23) == 5
assert recursive_binary_search(data, 2) == 0
assert recursive_binary_search(data, 91) == 9
assert recursive_binary_search(data, 50) == -1
assert recursive_binary_search([], 10) == -1"""
    ),
    (
        "CHALLENGE_18_RECURSIVE_GRAPH_DEPTH",
        "PYTHON",
        "Write a recursive function recursive_depth(node: dict) -> int that calculates the maximum tree depth of a node dictionary where children is a list of child node dicts, returning 1 for leaf nodes with empty or missing children.",
        """leaf = {"id": "leaf", "children": []}
assert recursive_depth(leaf) == 1
tree = {
    "id": "root",
    "children": [
        {"id": "a", "children": [{"id": "a1", "children": []}]},
        {"id": "b", "children": []}
    ]
}
assert recursive_depth(tree) == 3
assert recursive_depth({"id": "empty"}) == 1"""
    )
]

def seed_batch_four():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    print("Seeding Batch 4 (Challenges 13–18: Recursive Foundations)...")
    for cid, domain, intent, harness in BATCH_FOUR_CHALLENGES:
        cur.execute("""
        INSERT OR REPLACE INTO autonomous_curriculum_queue
        (curriculum_id, domain, challenge_intent, test_harness_code, status, attempts, created_at)
        VALUES (?, ?, ?, ?, 'PENDING', 0, datetime('now'))
        """, (cid, domain, intent, harness))
        print(f"  [+] Queued: {cid} -> {intent[:60]}...")
    conn.commit()
    conn.close()
    print("Batch 4 successfully committed to viv_code_topology.sqlite3.")

if __name__ == "__main__":
    seed_batch_four()
