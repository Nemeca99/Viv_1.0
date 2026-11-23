"""Experiment: Loop Thermodynamics & AST Equivalence Class Discovery
Viv is given 3 base loop patterns reaching target 10, prompted to author 3 novel unique variants,
and profiles all candidates on physical silicon to rank them by thermodynamic efficiency.
"""

from __future__ import annotations
import ast
import dis
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import tracemalloc
import urllib.request
from pathlib import Path

WORKSPACE_PATH = Path(r"L:\LocalCoder\workspace")
AUTONOMY_DIR = WORKSPACE_PATH / "autonomy"
CODE_DB = AUTONOMY_DIR / "viv_code_topology.sqlite3"
L_TMP_DIR = AUTONOMY_DIR / ".tmp"
L_TMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(L_TMP_DIR)

COMPLETIONS_URL = "http://127.0.0.1:1234/v1/completions"

BASE_SEEDS = [
    (
        "seed_range_10",
        """def loop_seed_range() -> int:
    total = 0
    for _ in range(10):
        total += 1
    return total"""
    ),
    (
        "seed_list_unroll",
        """def loop_seed_list() -> int:
    total = 0
    for val in [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]:
        total += val
    return total"""
    ),
    (
        "seed_string_stream",
        """def loop_seed_string() -> int:
    total = 0
    for ch in "ABCDEFGHIJ":
        total += 1
    return total"""
    )
]

def profile_function(fn_code: str, fn_name: str) -> dict:
    """Executes on silicon to measure opcodes, memory entropy, and CPU latency."""
    local_env = {}
    exec(fn_code, local_env)
    fn = local_env[fn_name]

    # Verification: must equal 10
    assert fn() == 10, f"{fn_name} failed verification: {fn()} != 10"

    # 1. Opcode count
    instructions = list(dis.Bytecode(fn))
    opcode_count = len(instructions)

    # 2. Memory entropy (heap bytes)
    tracemalloc.start()
    _ = fn()
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # 3. CPU Latency (avg nanoseconds over 10,000 runs)
    for _ in range(500):  # Warmup
        fn()
    t0 = time.perf_counter_ns()
    runs = 10_000
    for _ in range(runs):
        fn()
    t1 = time.perf_counter_ns()
    avg_ns = (t1 - t0) / runs

    # Efficiency score: higher is better (minimal time, memory, opcodes)
    efficiency = round(10_000_000 / ((avg_ns * 10) + (peak_bytes * 5) + (opcode_count * 20)), 2)

    return {
        "fn_name": fn_name,
        "opcode_count": opcode_count,
        "peak_bytes": peak_bytes,
        "avg_nanoseconds": round(avg_ns, 2),
        "efficiency_score": efficiency,
        "code": fn_code
    }

def get_ast_signature(code: str) -> str:
    """Returns canonical normalized AST representation of the loop body."""
    tree = ast.parse(code)
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            return ast.dump(node)
    return ast.dump(tree)

def query_novel_variants() -> list[str]:
    prompt = '''"""
Task: Python Loop Equivalence Class Discovery
Goal: Write 3 UNIQUE Python functions that calculate the number 10 using a for loop adding 1 at each iteration.
Each function must return int 10.
Every function must use a completely different iteration mechanism (e.g., generator expressions, enumerate, reversed, dictionary keys, slicing, itertools, while-in-for, etc.).

Base examples already known:
1. for _ in range(10): total += 1
2. for val in [1] * 10: total += val
3. for ch in "ABCDEFGHIJ": total += 1

Now write 3 NEW, DIFFERENT functions named variant_one(), variant_two(), and variant_three():
"""
from __future__ import annotations
import math, sys, itertools
from typing import List, Dict

def variant_one() -> int:
'''
    payload = {
        "model": "deepseek-coder-6.7b-base",
        "prompt": prompt,
        "temperature": 0.3,
        "max_tokens": 500,
        "stop": ["<|EOT|>", "<|end_of_sentence|>", "\n# ==="]
    }

    req = urllib.request.Request(COMPLETIONS_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read().decode("utf-8"))
        gen_text = res["choices"][0]["text"]

    full_text = "def variant_one() -> int:\n" + gen_text
    return full_text

def extract_functions(full_code: str) -> list[tuple[str, str]]:
    """Extracts valid function definitions from the generated block."""
    try:
        tree = ast.parse(full_code)
    except SyntaxError:
        # Backtrack line by line to compile
        lines = full_code.splitlines()
        for i in range(len(lines), 3, -1):
            try:
                tree = ast.parse("\n".join(lines[:i]))
                full_code = "\n".join(lines[:i])
                break
            except SyntaxError:
                continue

    functions = []
    lines = full_code.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            start = node.lineno - 1
            end = node.end_lineno
            fn_code = "\n".join(lines[start:end])
            functions.append((node.name, fn_code))
    return functions

def run_experiment():
    print("=" * 75)
    print("VIV ALGORITHMIC THERMODYNAMICS: LOOP VARIATION & EFFICIENCY PROFILING")
    print("=" * 75)

    all_candidates = []
    known_ast_sigs = set()

    # Step 1: Profile Seeds
    print("\n[Phase 1] Profiling 3 Base Seed Implementations on Silicon...")
    for name, code in BASE_SEEDS:
        sig = get_ast_signature(code)
        known_ast_sigs.add(sig)
        profile = profile_function(code, code.split("(")[0].replace("def ", "").strip())
        all_candidates.append(profile)
        print(f"  * Seed '{profile['fn_name']}': {profile['avg_nanoseconds']} ns | {profile['peak_bytes']} bytes | {profile['opcode_count']} opcodes | Score: {profile['efficiency_score']}")

    # Step 2: Query Model for Novel Variants
    print("\n[Phase 2] Prompting Viv for 3 Structurally Novel Loop Variants...")
    gen_code = query_novel_variants()
    extracted = extract_functions(gen_code)
    print(f"  -> Extracted {len(extracted)} candidate functions from generated AST.")

    # Step 3: Verify & Profile Variants
    print("\n[Phase 3] Testing AST Uniqueness and Profiling Silicon Thermodynamics...")
    novel_count = 0
    for name, code in extracted:
        try:
            sig = get_ast_signature(code)
            is_unique = sig not in known_ast_sigs
            known_ast_sigs.add(sig)

            profile = profile_function(code, name)
            profile["is_novel_ast"] = is_unique
            all_candidates.append(profile)
            novel_count += 1
            status = "NOVEL AST" if is_unique else "DUPLICATE AST"
            print(f"  [PASS] {name} ({status}): {profile['avg_nanoseconds']} ns | {profile['peak_bytes']} B | {profile['opcode_count']} opcodes | Score: {profile['efficiency_score']}")
        except Exception as e:
            print(f"  [FAIL] {name} failed: {e}")

    # Step 4: Leaderboard
    all_candidates.sort(key=lambda x: x["efficiency_score"], reverse=True)
    print("\n" + "=" * 75)
    print("THERMODYNAMIC EFFICIENCY LEADERBOARD (PHYSICAL SILICON EXECUTION)")
    print("=" * 75)
    print(f"{'Rank':<5} | {'Function':<22} | {'Time (ns)':<10} | {'Heap Mem':<10} | {'Opcodes':<8} | {'Score':<8}")
    print("-" * 75)
    for i, c in enumerate(all_candidates, 1):
        print(f"{i:<5} | {c['fn_name']:<22} | {c['avg_nanoseconds']:<10} | {c['peak_bytes']} B{'':<6} | {c['opcode_count']:<8} | {c['efficiency_score']:<8}")

    winner = all_candidates[0]
    print("\n[+] THERMODYNAMIC CHAMPION:")
    print(f"  Function: {winner['fn_name']} (Score: {winner['efficiency_score']})")
    print(f"  Execution Time: {winner['avg_nanoseconds']} ns per loop")
    print(f"  Heap Entropy: {winner['peak_bytes']} bytes")
    print(f"  Bytecode Size: {winner['opcode_count']} instructions")
    print("\nCode:")
    print(winner["code"])

if __name__ == "__main__":
    run_experiment()
