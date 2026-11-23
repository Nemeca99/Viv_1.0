"""Deterministic ALU & Base-52 (26 Letter Neurons + 1 SHIFT Neuron) Transducer for Viv.

Core Topological Law:
- Viv has NO digit neurons (`0..9` are `NULL_UNLEARNED_ENTITY`).
- She has 26 base letter neurons (`'a'..'z'`) + 1 `SHIFT` modifier neuron (`+26`) + Logic Zero (`!0 = 0`):
    * `'a' = 1`  ('one')       ... `'z' = 26` ('twenty six')
    * `SHIFT + 'a' = 'A' = 27` ... `SHIFT + 'z' = 'Z' = 52`
- Any integer `n > 0` decomposes bijectively into Base-52 using ONLY those 26 letter neurons
  plus `SHIFT`, and maps deterministically to English number words and calculator digits.
"""
from __future__ import annotations

import ast
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOWER = "abcdefghijklmnopqrstuvwxyz"
UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

ONES = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
    11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
}
TENS = {
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
}
WORD_TO_VAL = {v: k for k, v in {**ONES, **TENS}.items()}
WORD_TO_VAL.update({"hundred": 100, "thousand": 1000})


# =====================================================================
# SECTION 1: BASE-52 (26 LETTER NEURONS a=1..z=26 + 1 SHIFT NEURON +26)
# =====================================================================
def b52_char_to_val(c: str) -> int:
    """'a'..'z' -> 1..26; 'A'..'Z' (SHIFT + 'a'..'z') -> 27..52."""
    if len(c) == 1 and c in LOWER:
        return LOWER.index(c) + 1
    if len(c) == 1 and c in UPPER:
        return UPPER.index(c) + 27  # SHIFT (+26) + base letter (1..26)
    raise ValueError(f"Not a Base-52 letter neuron: {c!r}")


def b52_val_to_char(v: int) -> str:
    """1..26 -> 'a'..'z'; 27..52 -> 'A'..'Z' (SHIFT + 'a'..'z')."""
    if 1 <= v <= 26:
        return LOWER[v - 1]
    if 27 <= v <= 52:
        return UPPER[v - 27]
    raise ValueError(f"Out of single-place Base-52 bounds (1..52): {v}")


def int_to_b52(n: int) -> str:
    """Bijective Base-52 encoding: 0 -> '!0', 1 -> 'a', 26 -> 'z', 27 -> 'A' (SHIFT+a), 52 -> 'Z', 53 -> 'aa'."""
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("int_to_b52 requires int")
    if n == 0:
        return "!0"
    neg = n < 0
    v = abs(n)
    out = []
    while v > 0:
        rem = (v - 1) % 52 + 1
        out.append(b52_val_to_char(rem))
        v = (v - rem) // 52
    s = "".join(reversed(out))
    return f"-{s}" if neg else s


def b52_to_int(s: str) -> int:
    """Inverse of int_to_b52: '!0' -> 0, 'a' -> 1, 'A' -> 27, 'Z' -> 52, 'aa' -> 53."""
    clean = s.strip()
    if clean in ("!0", "0~", "lz", "LZ"):
        return 0
    neg = clean.startswith("-")
    body = clean.lstrip("-")
    if not body or not body.isalpha():
        raise ValueError(f"Invalid Base-52 token: {s!r}")
    v = 0
    for ch in body:
        v = v * 52 + b52_char_to_val(ch)
    return -v if neg else v


def b52_neuron_chain(n: int) -> str:
    """Express any integer as activations of the 26 base letter neurons + SHIFT."""
    if n == 0:
        return "LOGIC_ZERO(!0)"
    b52 = int_to_b52(abs(n))
    parts = []
    for ch in b52:
        if ch in LOWER:
            parts.append(f"neuron:{ch}({b52_char_to_val(ch)})")
        else:
            base = ch.lower()
            parts.append(f"[SHIFT+neuron:{base}->{ch}({b52_char_to_val(ch)})]")
    chain = " >> ".join(parts)
    return f"NEG({chain})" if n < 0 else chain


def ground_base52_neurons_in_db(db_path: Path | None = None) -> dict[str, int]:
    """Commit the 26 base letter neurons (a=1..z=26), 1 SHIFT neuron (+26), and 26 shifted bonds (A=27..Z=52)."""
    target_db = db_path or (Path(__file__).resolve().parent / "viv_code_topology.sqlite3")
    conn = sqlite3.connect(target_db, timeout=30)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS viv_base52_neurons ("
        "neuron_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, base_letter TEXT NOT NULL, "
        "uses_shift INTEGER NOT NULL, numeric_value INTEGER NOT NULL, word_neuron TEXT NOT NULL, "
        "formula TEXT NOT NULL, sha256 TEXT NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS function_bonds ("
        "source_pattern TEXT, target_pattern TEXT, relation TEXT, weight REAL, "
        "PRIMARY KEY (source_pattern, target_pattern))"
    )
    rows = [
        ("NEURON_LOGIC_ZERO", "!0", "!0", 0, 0, "zero", "LOGIC_ZERO = 0"),
        ("NEURON_MODIFIER_SHIFT", "SHIFT", "SHIFT", 1, 26, "twenty six", "SHIFT = +26"),
    ]
    for i, ch in enumerate(LOWER, start=1):
        w = int_to_words(i)
        rows.append((f"NEURON_LETTER_{ch}", ch, ch, 0, i, w, f"{ch} = {i} ({w})"))
    for i, ch in enumerate(UPPER, start=27):
        base = ch.lower()
        base_val = i - 26
        w = int_to_words(i)
        rows.append((f"NEURON_SHIFTED_{ch}", ch, base, 1, i, w, f"SHIFT(26) + {base}({base_val}) = {ch}({i}) ({w})"))

    for nid, sym, base, sh, val, wn, form in rows:
        h = hashlib.sha256(f"{nid}:{sym}:{val}:{form}".encode()).hexdigest()
        cur.execute(
            "INSERT OR REPLACE INTO viv_base52_neurons VALUES (?,?,?,?,?,?,?,?)",
            (nid, sym, base, sh, val, wn, form, h),
        )

    # Lock topological bonds in function_bonds:
    # 1) neuron:a..z -> word_num:one..twenty_six
    # 2) SHIFT+neuron:a -> neuron:A(27) -> word_num:twenty_seven
    bonds = 0
    for i, ch in enumerate(LOWER, start=1):
        wn = f"word_num:{int_to_words(i).replace(' ', '_')}"
        cur.execute(
            "INSERT OR REPLACE INTO function_bonds VALUES (?,?, 'LOCKED_BOND', 0.99)",
            (f"b52:{ch}", wn),
        )
        up = ch.upper()
        up_val = i + 26
        up_wn = f"word_num:{int_to_words(up_val).replace(' ', '_')}"
        cur.execute(
            "INSERT OR REPLACE INTO function_bonds VALUES (?,?, 'LOCKED_BOND', 0.99)",
            (f"SHIFT+b52:{ch}", f"b52:{up}"),
        )
        cur.execute(
            "INSERT OR REPLACE INTO function_bonds VALUES (?,?, 'LOCKED_BOND', 0.99)",
            (f"b52:{up}", up_wn),
        )
        bonds += 3

    conn.commit()
    conn.close()
    return {"neurons_registered": len(rows), "locked_b52_bonds": bonds}


# =====================================================================
# SECTION 2: ENGLISH WORD NEURONS <-> INTEGER DIGITS
# =====================================================================
def int_to_words(n: int) -> str:
    """Deterministic integer -> alphabetical word-neuron sequence."""
    if not isinstance(n, int) or isinstance(n, bool):
        return str(n)
    if n < 0:
        return "negative " + int_to_words(-n)
    if n in ONES:
        return ONES[n]
    if n < 100:
        t, r = (n // 10) * 10, n % 10
        return TENS[t] if r == 0 else f"{TENS[t]} {ONES[r]}"
    if n < 1000:
        h, r = n // 100, n % 100
        return f"{ONES[h]} hundred" if r == 0 else f"{ONES[h]} hundred {int_to_words(r)}"
    if n < 1_000_000:
        th, r = n // 1000, n % 1000
        return f"{int_to_words(th)} thousand" if r == 0 else f"{int_to_words(th)} thousand {int_to_words(r)}"
    return " ".join(ONES[int(d)] for d in str(n))


def words_to_int(text: str) -> int | None:
    """Deterministic alphabetical number words -> integer digit."""
    tokens = [t for t in re.split(r"[\s\-]+", text.strip().lower()) if t and t != "and"]
    if not tokens:
        return None
    neg = False
    if tokens[0] in ("negative", "minus"):
        neg = True
        tokens = tokens[1:]
    if not tokens:
        return None
    total = 0
    current = 0
    for tok in tokens:
        if tok not in WORD_TO_VAL:
            return None
        val = WORD_TO_VAL[tok]
        if val == 100:
            current = (current or 1) * 100
        elif val == 1000:
            total += (current or 1) * 1000
            current = 0
        else:
            current += val
    res = total + current
    return -res if neg else res


def describe_value_in_words(val: Any) -> str:
    """Format any Python value alongside its word-neuron AND Base-52 letter-neuron representation."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, int):
        return f"{int_to_words(val)} [b52:{int_to_b52(val)}={val}]"
    if isinstance(val, list):
        inner = ", ".join(describe_value_in_words(x) for x in val)
        return f"[{inner}]"
    return repr(val)


def parse_word_or_literal(raw: str) -> Any:
    """Parse Viv's prediction whether she answered in digits ('12'), words ('twelve'), or Base-52 ('b52:l')."""
    s = raw.strip().strip("`")
    try:
        return ast.literal_eval(s)
    except Exception:
        pass
    m_b52 = re.match(r"^b52:([!0A-Za-z\-]+)$", s)
    if m_b52:
        try:
            return b52_to_int(m_b52.group(1))
        except ValueError:
            pass
    m_paren = re.search(r"\[b52:[^\]]+=(-?\d+)\]", s)
    if m_paren:
        return int(m_paren.group(1))
    m_num_paren = re.match(r"^([a-z\s\-]+)\s*\((-?\d+)\)$", s.lower())
    if m_num_paren:
        return int(m_num_paren.group(2))
    w_int = words_to_int(s.strip("'\" "))
    if w_int is not None:
        return w_int
    if s.startswith("[") and s.endswith("]"):
        parts = [p.strip() for p in s[1:-1].split(",") if p.strip()]
        conv = [words_to_int(p.strip("'\"")) for p in parts]
        if all(x is not None for x in conv):
            return conv
    return s


def transduce_digits_in_spec(text: str) -> str:
    """Annotate raw digits in a task spec with both word-neurons and Base-52 letter-neurons, skipping digits inside code structures, brackets, tuples, or quotes."""
    code_delims = "[]()',\"`:="
    def _repl(m: re.Match) -> str:
        num_str = m.group(0)
        start, end = m.start(), m.end()
        if (start > 0 and text[start - 1] in code_delims) or (end < len(text) and text[end] in code_delims):
            return num_str
        try:
            n = int(num_str)
            if -1000 <= n <= 9999:
                return f"{num_str} ({int_to_words(n)}, b52:{int_to_b52(n)})"
        except ValueError:
            pass
        return num_str

    return re.sub(r"(?<![A-Za-z_])\d+(?![A-Za-z_])", _repl, text)


ALU_PRELUDE = (
    "# --- ALU WORD & BASE-52 TO DIGIT PRELUDE (a=1..z=26, SHIFT+a=A=27..Z=52) ---\n"
    "from typing import Optional, List, Dict, Set, Tuple, Any, Union\n"
    "import sys, os, types\n"
    "if '/work' not in sys.path:\n"
    "    sys.path.insert(0, '/work')\n"
    "if 'numpy' not in sys.modules:\n"
    "    _np = types.ModuleType('numpy')\n"
    "    _np.array = lambda x, *a, **k: list(x)\n"
    "    _np.arange = range\n"
    "    _np.zeros = lambda n, *a, **k: [0] * (n if isinstance(n, int) else n[0])\n"
    "    _np.ones = lambda n, *a, **k: [1] * (n if isinstance(n, int) else n[0])\n"
    "    import random as _rnd\n"
    "    _rnd_mod = types.ModuleType('numpy.random')\n"
    "    _rnd_mod.choice = lambda seq, *a, **k: _rnd.choice(list(seq))\n"
    "    _rnd_mod.random = _rnd.random\n"
    "    _rnd_mod.rand = lambda *shape: [_rnd.random() for _ in range(shape[0])] if shape else _rnd.random()\n"
    "    _rnd_mod.randn = lambda *shape: [_rnd.gauss(0, 1) for _ in range(shape[0])] if shape else _rnd.gauss(0, 1)\n"
    "    _rnd_mod.randint = lambda low, high=None, size=None: _rnd.randint(0 if high is None else low, low if high is None else high)\n"
    "    _np.random = _rnd_mod\n"
    "    sys.modules['numpy'] = _np\n"
    "ZERO, ONE, TWO, THREE, FOUR, FIVE, SIX, SEVEN, EIGHT, NINE, TEN = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10\n"
    "ELEVEN, TWELVE, THIRTEEN, FOURTEEN, FIFTEEN, TWENTY, TWENTY_SIX, TWENTY_SEVEN, FIFTY_TWO, HUNDRED = 11, 12, 13, 14, 15, 20, 26, 27, 52, 100\n"
    "SHIFT = 26\n"
    "def b52(s: str) -> int:\n"
    "    if s == '!0': return 0\n"
    "    v = 0\n"
    "    for ch in s:\n"
    "        v = v * 52 + (ord(ch) - 96 if 'a' <= ch <= 'z' else ord(ch) - 64 + 26)\n"
    "    return v\n"
)


if __name__ == "__main__":
    stats = ground_base52_neurons_in_db()
    print("Grounded Base-52 neurons:", stats)
    for sample in (0, 1, 2, 26, 27, 52, 53, 100):
        code = int_to_b52(sample)
        back = b52_to_int(code)
        assert back == sample
        print(f"  {sample:>3} -> b52:{code:<4} -> {b52_neuron_chain(sample)} -> word:'{int_to_words(sample)}'")
