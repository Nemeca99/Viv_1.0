import sys
import re
import sqlite3
import hashlib
from datetime import datetime
from pathlib import Path

CODE_DB = Path(r"L:\LocalCoder\workspace\autonomy\viv_code_topology.sqlite3")
FAST_INDEX_DB = Path(r"L:\LocalCoder\workspace\autonomy\fast_lexical_index.sqlite3")

# Digit to Word Mapping (Characters / Words Only)
DIGIT_TO_WORD = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
    "+": "plus",
    "-": "minus",
    "*": "times",
    "/": "divided by",
    "=": "equals"
}

def init_math_bridge():
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS symbolic_math_bridge (
        expression_raw TEXT PRIMARY KEY,
        verbal_translation TEXT,
        calculator_result INTEGER,
        verbal_result TEXT,
        topological_bond TEXT,
        registered_at TEXT
    )
    """)
    conn.commit()
    conn.close()

def translate_symbols_to_words(expr: str) -> str:
    """Converts raw digit math '1+1' into letter tokens 'one plus one'."""
    tokens = []
    for ch in expr.replace(" ", ""):
        if ch in DIGIT_TO_WORD:
            tokens.append(DIGIT_TO_WORD[ch])
        else:
            tokens.append(ch)
    return " ".join(tokens)

def execute_symbolic_math_trial(raw_input: str) -> dict:
    """
    1. Input: '1+1'
    2. Translate to character tokens: 'one plus one'
    3. Run through ALU calculator: 1 + 1 = 2
    4. Translate result to word neuron: 'two'
    5. Form the bond: 'one unit plus one unit equals two units'
    6. Commit permanent associative bond to SQLite.
    """
    init_math_bridge()
    clean_expr = raw_input.replace(" ", "")
    verbal_expr = translate_symbols_to_words(clean_expr)

    # Safe deterministic arithmetic parser (ALU engine)
    match = re.match(r"^(\d+)([\+\-\*\/])(\d+)$", clean_expr)
    if not match:
        return {"success": False, "error": f"Invalid arithmetic pattern: {raw_input}"}

    a, op, b = int(match.group(1)), match.group(2), int(match.group(3))
    
    if op == "+":
        calc_res = a + b
    elif op == "-":
        calc_res = a - b
    elif op == "*":
        calc_res = a * b
    elif op == "/":
        calc_res = a // b if b != 0 else 0

    verbal_res = DIGIT_TO_WORD.get(str(calc_res), str(calc_res))
    verbal_a = DIGIT_TO_WORD.get(str(a), str(a))
    verbal_b = DIGIT_TO_WORD.get(str(b), str(b))
    verbal_op = DIGIT_TO_WORD.get(op, op)

    # Topological bond sentence: 'one unit plus one unit equals two units'
    bond_statement = f"{verbal_a} unit {verbal_op} {verbal_b} unit equals {verbal_res} units"

    # Commit to SQLite
    conn = sqlite3.connect(CODE_DB)
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO symbolic_math_bridge 
    (expression_raw, verbal_translation, calculator_result, verbal_result, topological_bond, registered_at)
    VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (clean_expr, verbal_expr, calc_res, verbal_res, bond_statement))

    # Also form an associative link
    cur.execute("""
    INSERT OR REPLACE INTO cognitive_associative_links 
    (source_concept, target_concept, bond_type, co_occurrence_count, weight, created_at)
    VALUES (?, ?, 'MATHEMATICAL_IDENTITY', 1, 1.0, datetime('now'))
    """, (f"{verbal_a}_PLUS_{verbal_b}", verbal_res))

    conn.commit()
    conn.close()

    return {
        "raw": clean_expr,
        "verbal_translation": verbal_expr,
        "calculator_result": calc_res,
        "verbal_result": verbal_res,
        "bond_statement": bond_statement
    }

if __name__ == "__main__":
    trials = ["1+1", "2+2", "3+5", "4*2"]
    print("=" * 70)
    print("[SYMBOLIC MATH TRANSLATION & NEURON BONDING TRIAL]")
    print("Digit numbers -> ALU Calculator -> Verbal Character Neurons")
    print("=" * 70)

    for t in trials:
        res = execute_symbolic_math_trial(t)
        print(f"Input: {res['raw']:<6} -> Verbal: {res['verbal_translation']:<18} -> ALU: {res['calculator_result']} ({res['verbal_result']})")
        print(f"  [TOPOLOGICAL BOND]: \"{res['bond_statement']}\"")
