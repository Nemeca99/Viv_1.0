"""Seed Batch 5: Recursive Linked Systems & Autonomous Game Engines (Challenges 19–24)
Teaches Viv mutual recursion, game state tree evaluations, backtracking maze navigation,
Towers of Hanoi, and territory flood fill on physical silicon.
"""

import sqlite3
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")

BATCH_FIVE_CHALLENGES = [
    (
        "CHALLENGE_19_MUTUAL_RECURSION_PARITY",
        "PYTHON",
        "Write mutually recursive functions is_even(n: int) -> bool and is_odd(n: int) -> bool that call each other to determine parity for non-negative integers without using modulo (%) or bitwise (&).",
        """assert is_even(0) is True
assert is_odd(0) is False
assert is_even(4) is True
assert is_odd(7) is True
assert is_even(13) is False
assert is_odd(100) is False"""
    ),
    (
        "CHALLENGE_20_TOWERS_OF_HANOI_GAME",
        "PYTHON",
        "Write a recursive function hanoi_solve(n: int, src: str, dst: str, aux: str) -> list[tuple[str, str]] that returns the ordered list of disk moves (from_peg, to_peg) to solve Towers of Hanoi.",
        """moves_1 = hanoi_solve(1, 'A', 'C', 'B')
assert moves_1 == [('A', 'C')]
moves_3 = hanoi_solve(3, 'A', 'C', 'B')
assert len(moves_3) == 7
assert moves_3[0] == ('A', 'C')
assert moves_3[-1] == ('A', 'C')"""
    ),
    (
        "CHALLENGE_21_RECURSIVE_MAZE_SOLVER",
        "PYTHON",
        "Write recursive functions is_valid_cell(grid: list[list[int]], r: int, c: int, visited: set) -> bool and solve_maze(grid: list[list[int]], r: int, c: int, target_r: int, target_c: int, visited: set) -> list[tuple[int, int]] that find a path through a 2D maze where 0 is open and 1 is wall using recursive backtracking.",
        """grid = [
    [0, 0, 1],
    [1, 0, 1],
    [1, 0, 0]
]
path = solve_maze(grid, 0, 0, 2, 2, set())
assert path is not None
assert path[0] == (0, 0)
assert path[-1] == (2, 2)
assert (0, 2) not in path
assert (1, 0) not in path"""
    ),
    (
        "CHALLENGE_22_RECURSIVE_NUMBER_GUESS_SEARCH",
        "PYTHON",
        "Write recursive functions evaluate_guess(secret: int, guess: int) -> str and recursive_guess(secret: int, low: int, high: int) -> int that iteratively guesses using binary search and returns the secret when evaluate_guess returns 'EQUAL'.",
        """assert evaluate_guess(42, 42) == 'EQUAL'
assert evaluate_guess(42, 20) == 'LOW'
assert evaluate_guess(42, 50) == 'HIGH'
assert recursive_guess(42, 1, 100) == 42
assert recursive_guess(1, 1, 100) == 1
assert recursive_guess(100, 1, 100) == 100"""
    ),
    (
        "CHALLENGE_23_RECURSIVE_TERRITORY_FLOOD",
        "PYTHON",
        "Write a recursive function flood_fill(grid: list[list[int]], r: int, c: int, new_val: int, orig_val: int) -> int that recursively replaces connected matching cells with new_val and returns total cells changed.",
        """grid = [
    [1, 1, 0],
    [1, 0, 0],
    [0, 0, 2]
]
changed = flood_fill(grid, 0, 0, 9, 1)
assert changed == 3
assert grid[0][0] == 9
assert grid[0][1] == 9
assert grid[1][0] == 9
assert grid[0][2] == 0
assert grid[2][2] == 2"""
    ),
    (
        "CHALLENGE_24_RECURSIVE_TIC_TAC_TOE_EVALUATOR",
        "PYTHON",
        "Write recursive functions check_winner(board: list[str]) -> str and minimax_score(board: list[str], is_max: bool) -> int that evaluate winning state or returns 1 for X win, -1 for O win, 0 for draw/unfinished.",
        """assert check_winner(['X', 'X', 'X', ' ', 'O', ' ', 'O', ' ', ' ']) == 'X'
assert check_winner(['O', 'X', ' ', 'O', 'X', ' ', 'O', ' ', ' ']) == 'O'
assert check_winner(['X', 'O', 'X', ' ', ' ', ' ', ' ', ' ', ' ']) == 'NONE'
assert minimax_score(['X', 'X', 'X', ' ', 'O', ' ', 'O', ' ', ' '], False) == 1
assert minimax_score(['O', 'X', ' ', 'O', 'X', ' ', 'O', ' ', ' '], True) == -1"""
    )
]

def seed_batch_five():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    print("Seeding Batch 5 (Challenges 19–24: Recursive Linked Systems & Game Engines)...")
    for cid, domain, intent, harness in BATCH_FIVE_CHALLENGES:
        cur.execute("""
        INSERT OR REPLACE INTO autonomous_curriculum_queue
        (curriculum_id, domain, challenge_intent, test_harness_code, status, attempts, created_at)
        VALUES (?, ?, ?, ?, 'PENDING', 0, datetime('now'))
        """, (cid, domain, intent, harness))
        print(f"  [+] Queued: {cid} -> {intent[:60]}...")
    conn.commit()
    conn.close()
    print("Batch 5 successfully committed to viv_code_topology.sqlite3.")

if __name__ == "__main__":
    seed_batch_five()
