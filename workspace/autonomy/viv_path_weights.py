"""Viv's Python path weights & automatic relational concept-web:
forward credit, backward blame, lock-in, and subtractive pruning.

A "path" is a (parent AST node -> child AST node) edge in her code, e.g.
FunctionDef>For, For>AugAssign.
A "concept bond" is a higher-level link in `function_bonds` between semantic/syntactic
concepts discovered inside the same verified or failed attempt (e.g. `concept:loop` <->
`concept:accumulator`, or `task:py_gcd` <-> `op:Mod`). Viv does not consciously create
these bonds—they form automatically as side effects of her execution results.

Layers in viv_code_topology.sqlite3 (nothing is ever destructively deleted):
  viv_python_path_weights  live, adaptive AST edge weights
  viv_path_tasks           per-path evidence broken down by task
  viv_locked_edges         LOCKED topology (frozen weights, proven across tasks)
  function_bonds           automatic concept-to-concept relational web (live)
  viv_pruned_bonds_archive discarded/superseded bonds kept permanently as failure history
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).resolve().parent / "viv_code_topology.sqlite3"
LR_PASS, LR_BLAME, LR_BLAME_DIFFUSE, LR_REF = 0.10, 0.25, 0.05, 0.05
MIN_EVIDENCE = 3
LOCK_WEIGHT, LOCK_PASSES, LOCK_TASKS, LOCK_MAX_FAIL_RATE = 0.80, 8, 2, 0.15
PRUNE_WEIGHT, PRUNE_MIN_FAILS = 0.20, 4


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=30)
    c.execute(
        "CREATE TABLE IF NOT EXISTS viv_python_path_weights ("
        "path TEXT PRIMARY KEY, weight REAL NOT NULL DEFAULT 0.5, "
        "passes INTEGER NOT NULL DEFAULT 0, fails INTEGER NOT NULL DEFAULT 0, updated TEXT)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS viv_path_tasks ("
        "path TEXT NOT NULL, task_id TEXT NOT NULL, passes INTEGER NOT NULL DEFAULT 0, "
        "fails INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(path, task_id))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS viv_locked_edges ("
        "path TEXT PRIMARY KEY, locked_utc TEXT NOT NULL, weight REAL NOT NULL, passes INTEGER NOT NULL, "
        "fails INTEGER NOT NULL, tasks INTEGER NOT NULL, sha256 TEXT NOT NULL)"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS function_bonds ("
        "source_pattern TEXT, target_pattern TEXT, relation TEXT, weight REAL, "
        "PRIMARY KEY (source_pattern, target_pattern))"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS viv_pruned_bonds_archive ("
        "archive_id INTEGER PRIMARY KEY AUTOINCREMENT, source_pattern TEXT NOT NULL, "
        "target_pattern TEXT NOT NULL, relation TEXT NOT NULL, final_weight REAL NOT NULL, "
        "reason TEXT NOT NULL, archived_utc TEXT NOT NULL, sha256 TEXT NOT NULL)"
    )
    return c


def edges(code: str) -> list[tuple[str, int]]:
    """(path, line) for every parent>child AST edge. Empty list if the code doesn't parse."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    out = []
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.Load, ast.Store, ast.Del)):
                continue
            out.append((f"{type(parent).__name__}>{type(child).__name__}", getattr(child, "lineno", 0)))
    return out


def extract_concepts(code: str) -> list[str]:
    """Automatic subconscious concept extraction from AST (operations, calls, control structures)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    concepts: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While, ast.ListComp, ast.GeneratorExp, ast.If, ast.Try, ast.With)):
            concepts.add(f"ctrl:{type(node).__name__}")
        elif isinstance(node, ast.BinOp):
            concepts.add(f"op:{type(node.op).__name__}")
        elif isinstance(node, ast.Compare):
            for op in node.ops:
                concepts.add(f"cmp:{type(op).__name__}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                concepts.add(f"call:{node.func.id}")
            elif isinstance(node.func, ast.Attribute):
                concepts.add(f"method:{node.func.attr}")
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            concepts.add("ctrl:Slice")
        elif isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            from viv_alu_transducer import int_to_words
            if -20 <= node.value <= 100:
                concepts.add(f"word_num:{int_to_words(node.value).replace(' ', '_')}")
    return sorted(concepts)


def blamed_lines(error: str) -> set[int]:
    return {int(n) for a, b in re.findall(r"t\.py[\":,]+\s*(\d+)|line (\d+)", error) for n in (a, b) if n}


def _bump(cur: sqlite3.Cursor, path: str, target: float, lr: float, passed: bool, task_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    locked = cur.execute("SELECT 1 FROM viv_locked_edges WHERE path=?", (path,)).fetchone() is not None
    row = cur.execute("SELECT weight FROM viv_python_path_weights WHERE path=?", (path,)).fetchone()
    w = row[0] if row else 0.5
    if not locked:
        w = min(0.99, max(0.01, w + lr * (target - w)))
    cur.execute(
        "INSERT INTO viv_python_path_weights(path,weight,passes,fails,updated) VALUES(?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET weight=?, passes=passes+?, fails=fails+?, updated=?",
        (path, w, int(passed), int(not passed), now, w, int(passed), int(not passed), now),
    )
    if task_id:
        cur.execute(
            "INSERT INTO viv_path_tasks(path,task_id,passes,fails) VALUES(?,?,?,?) "
            "ON CONFLICT(path,task_id) DO UPDATE SET passes=passes+?, fails=fails+?",
            (path, task_id, int(passed), int(not passed), int(passed), int(not passed)),
        )


def _update_concept_bonds(cur: sqlite3.Cursor, code: str, passed: bool, task_id: str) -> tuple[int, int]:
    """Automatically form/strengthen concept bonds on pass; weaken and prune dead bonds on fail."""
    concepts = extract_concepts(code)
    if not concepts:
        return 0, 0
    target = 1.0 if passed else 0.0
    lr = LR_PASS if passed else LR_BLAME
    bonds_touched = 0
    # Link task -> concept and concept <-> concept
    pairs: list[tuple[str, str, str]] = []
    if task_id:
        for c in concepts:
            pairs.append((f"task:{task_id}", c, "TASK_USES_CONCEPT"))
    for i, a in enumerate(concepts):
        for b in concepts[i + 1:]:
            pairs.append((a, b, "CO_OCCURS_IN_SOLUTION"))

    for src, dst, rel in pairs:
        row = cur.execute(
            "SELECT weight, relation FROM function_bonds WHERE source_pattern=? AND target_pattern=?",
            (src, dst),
        ).fetchone()
        if row and row[1] == "LOCKED_BOND":
            continue
        w = row[0] if row else 0.5
        w = min(0.99, max(0.01, w + lr * (target - w)))
        if w >= LOCK_WEIGHT and passed:
            rel = "LOCKED_BOND"
        cur.execute(
            "INSERT INTO function_bonds(source_pattern,target_pattern,relation,weight) VALUES(?,?,?,?) "
            "ON CONFLICT(source_pattern,target_pattern) DO UPDATE SET weight=?, relation=?",
            (src, dst, rel, w, w, rel),
        )
        bonds_touched += 1

    # Prune bonds whose weight fell below PRUNE_WEIGHT: discard from active web, keep in archive as failure
    pruned = 0
    weak = cur.execute(
        "SELECT source_pattern, target_pattern, relation, weight FROM function_bonds "
        "WHERE weight <= ? AND relation != 'LOCKED_BOND'",
        (PRUNE_WEIGHT,),
    ).fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for src, dst, rel, w in weak:
        seal = hashlib.sha256(json.dumps([src, dst, rel, round(w, 6), now]).encode()).hexdigest()
        cur.execute(
            "INSERT INTO viv_pruned_bonds_archive(source_pattern,target_pattern,relation,final_weight,reason,archived_utc,sha256) "
            "VALUES (?,?,?,?,?,?,?)",
            (src, dst, rel, w, "SUBTRACTIVE_PRUNE_LOW_WEIGHT", now, seal),
        )
        cur.execute("DELETE FROM function_bonds WHERE source_pattern=? AND target_pattern=?", (src, dst))
        pruned += 1
    return bonds_touched, pruned


def consider_locks(cur: sqlite3.Cursor) -> list[str]:
    """Promote proven links into the locked topology. Append-only: a locked link is never removed here."""
    newly = []
    rows = cur.execute(
        "SELECT w.path, w.weight, w.passes, w.fails FROM viv_python_path_weights w "
        "WHERE w.weight >= ? AND w.passes >= ? AND w.path NOT IN (SELECT path FROM viv_locked_edges)",
        (LOCK_WEIGHT, LOCK_PASSES),
    ).fetchall()
    for path, weight, passes, fails in rows:
        if fails > LOCK_MAX_FAIL_RATE * (passes + fails):
            continue
        tasks = cur.execute("SELECT COUNT(*) FROM viv_path_tasks WHERE path=? AND passes>0", (path,)).fetchone()[0]
        if tasks < LOCK_TASKS:
            continue
        now = datetime.now(timezone.utc).isoformat()
        seal = hashlib.sha256(json.dumps([path, round(weight, 6), passes, fails, tasks, now]).encode()).hexdigest()
        cur.execute("INSERT INTO viv_locked_edges VALUES (?,?,?,?,?,?,?)", (path, now, weight, passes, fails, tasks, seal))
        newly.append(path)
    return newly


def update(code: str, passed: bool, error: str = "", reference: str = "", task_id: str = "") -> dict:
    """Backward pass for one graded attempt. Returns what changed (for receipts)."""
    es = edges(code)
    if not es:
        return {"updated": 0, "mode": "unparseable", "locked": [], "bonds": 0, "pruned": 0}
    c = _conn()
    cur = c.cursor()
    touched: Counter = Counter()
    if passed:
        for p in {p for p, _ in es}:
            _bump(cur, p, 1.0, LR_PASS, True, task_id)
            touched[p] += 1
        mode = "credit"
    else:
        lines = blamed_lines(error)
        hit = {p for p, ln in es if ln in lines} if lines else set()
        if hit:
            for p in hit:
                _bump(cur, p, 0.0, LR_BLAME, False, task_id)
                touched[p] += 1
            mode = "blame_lines"
        else:
            for p in {p for p, _ in es}:
                _bump(cur, p, 0.0, LR_BLAME_DIFFUSE, False, task_id)
                touched[p] += 1
            mode = "blame_diffuse"
        if reference:
            missing = {p for p, _ in edges(reference)} - {p for p, _ in es}
            for p in missing:
                _bump(cur, p, 1.0, LR_REF, True, task_id)
                touched[p] += 1
    bonds_touched, pruned = _update_concept_bonds(cur, code, passed, task_id)
    newly = consider_locks(cur)
    c.commit()
    c.close()
    return {"updated": len(touched), "mode": mode, "locked": newly, "bonds": bonds_touched, "pruned": pruned}


def locked_topology() -> list[tuple]:
    c = _conn()
    rows = c.execute("SELECT path, weight, passes, fails, tasks, locked_utc FROM viv_locked_edges ORDER BY locked_utc").fetchall()
    c.close()
    return rows


def hints(limit: int = 4, task_id: str = "") -> str:
    """Forward pass: locked links first, automatic concept bonds for the task, then live constructs."""
    c = _conn()
    locked = [r[0] for r in c.execute("SELECT path FROM viv_locked_edges ORDER BY weight DESC LIMIT ?", (limit,))]
    rows = c.execute(
        "SELECT path, weight, passes, fails FROM viv_python_path_weights WHERE passes+fails >= ? "
        "AND path NOT IN (SELECT path FROM viv_locked_edges)", (MIN_EVIDENCE,)
    ).fetchall()
    task_bonds = []
    if task_id:
        task_bonds = [
            f"{r[0]} ({r[1]:.2f})"
            for r in c.execute(
                "SELECT target_pattern, weight FROM function_bonds WHERE source_pattern=? AND weight >= 0.55 "
                "ORDER BY weight DESC LIMIT ?",
                (f"task:{task_id}", limit),
            )
        ]
    c.close()
    out = []
    if locked:
        out.append("Locked-in structure (proven): " + ", ".join(locked))
    if task_bonds:
        out.append("Linked concepts for this task: " + ", ".join(task_bonds))
    good = sorted((r for r in rows if r[1] >= 0.6), key=lambda r: -r[1])[:limit]
    bad = sorted((r for r in rows if r[1] <= 0.4), key=lambda r: r[1])[:limit]
    if good:
        out.append("Constructs that have worked for you: " + ", ".join(f"{p} ({w:.2f})" for p, w, *_ in good))
    if bad:
        out.append("Constructs that keep failing for you: " + ", ".join(f"{p} ({w:.2f})" for p, w, *_ in bad))
    return "\n".join(out)
