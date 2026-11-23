"""Viv Stage-2 Autonomous Causal Function Explorer:
Write a function -> Run in container -> Observe (input -> output) -> Understand "What did this do?"

How Understanding is Verified Deterministically (Zero Scripted Answers):
1. Viv writes her own Python function `def explore(x): ...` and 3 probe inputs.
2. The `viv-vm` container runs `explore(x)` on the 3 inputs and captures the real outputs.
3. Deterministic trace analyzer extracts the input->output transformation invariants
   (e.g. `out:len_shrunk`, `out:type_int`, `out:reversed`, `out:all_lower`, `out:unique_elements`).
4. Viv inspects her function + the 3 `(input -> output)` pairs, states in one sentence what the
   function does, and predicts the exact output for a held-out 4th input `holdout_x`.
5. The container runs `explore(holdout_x)`.
   - If `predicted_output == actual_output`: she understood what her code did.
     The AST concepts inside her function are bonded to the observed `out:*` effects in
     `function_bonds`, and the discovery is committed to `viv_causal_discoveries` + exported via Rust broker.
   - If `predicted_output != actual_output` (or runtime crash): recorded in append-only failure
     ledger and path weights/bonds are updated with backward blame.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AUTONOMY = Path(__file__).resolve().parent
import viv_code_learning_loop as L  # noqa: E402
import viv_path_weights as W  # noqa: E402

DB = AUTONOMY / "viv_code_topology.sqlite3"
CONTAINER = "viv-vm"

HOLDOUT_BY_TYPE = {
    "str": "'RustAndPython42'",
    "list": "[3, 1, 3, 2, 5]",
    "int": "12",
}


def _init_table() -> None:
    with sqlite3.connect(DB, timeout=30) as c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS viv_causal_discoveries ("
            "discovery_id TEXT PRIMARY KEY, func_name TEXT NOT NULL, code TEXT NOT NULL, "
            "io_trace_json TEXT NOT NULL, observed_effects TEXT NOT NULL, "
            "viv_explanation TEXT NOT NULL, holdout_input TEXT NOT NULL, "
            "predicted_output TEXT NOT NULL, actual_output TEXT NOT NULL, "
            "understood INTEGER NOT NULL, created_utc TEXT NOT NULL, sha256 TEXT NOT NULL)"
        )


def _dexec(script: str, timeout: int = 20) -> tuple[int, str, str]:
    r = subprocess.run(
        ["docker", "exec", "-i", "-w", "/work", CONTAINER, "python", "-"],
        input=script.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
    )
    return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")


def infer_io_effects(pairs: list[dict]) -> list[str]:
    """Deterministic comparison of input vs output to label what the function actually did."""
    effects: set[str] = set()
    for p in pairs:
        inp, out = p["in"], p["out"]
        effects.add(f"out_type:{type(out).__name__}")
        if type(inp) is type(out):
            effects.add("effect:type_preserved")
        else:
            effects.add(f"effect:type_{type(inp).__name__}_to_{type(out).__name__}")
        if isinstance(inp, (str, list)) and isinstance(out, (str, list)):
            if len(out) < len(inp):
                effects.add("effect:filtered_or_shrunk")
            elif len(out) == len(inp) and inp != out:
                effects.add("effect:transformed_same_len")
            elif len(out) > len(inp):
                effects.add("effect:expanded")
            if inp and out == inp[::-1]:
                effects.add("effect:reversed")
        if isinstance(inp, str) and isinstance(out, str) and inp != out:
            if out == inp.lower():
                effects.add("effect:lowercased")
            elif out == inp.upper():
                effects.add("effect:uppercased")
        if isinstance(inp, list) and isinstance(out, list) and inp:
            try:
                if out == sorted(inp):
                    effects.add("effect:sorted")
                if len(out) == len(set(out)) and len(out) < len(inp):
                    effects.add("effect:deduplicated")
            except TypeError:
                pass
        if isinstance(inp, (int, float)) and isinstance(out, (int, float)):
            if out > inp:
                effects.add("effect:numeric_growth")
            elif out < inp:
                effects.add("effect:numeric_reduction")
    return sorted(effects)


def _call_llm(system: str, user: str, temp: float = 0.4) -> str:
    payload = {
        "model": L.MODEL,
        "temperature": temp,
        "max_tokens": 500,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    req = urllib.request.Request(L.API_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"].strip()


def run_causal_discovery(step_k: int) -> dict:
    """Full self-authored function -> output trace -> holdout prediction loop."""
    _init_table()
    hint_str = W.hints(limit=5, task_id="self_causal_explore")
    kind = ["str", "list", "int"][step_k % 3]
    sample_inputs = {
        "str": "['Hello World', 'Python3', 'aBcDe']",
        "list": "[[4, 2, 4, 1], [10, 5, 10], [7, 7, 8]]",
        "int": "[3, 5, 10]",
    }[kind]
    sample_display = {
        "str": "'Hello World', 'Python3', or 'aBcDe'",
        "list": "[4, 2, 1] or [10, 5, 10] (a list of numbers)",
        "int": "3, 5, or 10 (an integer)",
    }[kind]
    holdout_expr = HOLDOUT_BY_TYPE[kind]

    # Step 1: Viv writes her own function
    sys_write = (
        "You are Viv exploring Python in your sandbox. Write ONE pure Python function named "
        "`explore(x)` that takes a single argument `x` and returns a transformed result. "
        "Reply with ONLY one ```python ... ``` block defining `def explore(x):`."
    )
    usr_write = (
        f"Write a clean function `def explore(x):` that operates on a single `{kind}` argument `x` "
        f"(for example: x={sample_display}) and returns a meaningful result.\n"
        + (f"\n{hint_str}\n" if hint_str else "")
    )
    try:
        raw_code = _call_llm(sys_write, usr_write, temp=0.5)
    except Exception as exc:
        return {"task": "self_causal_explore", "ok": False, "code": "", "error": f"LLM error: {exc}", "path": "", "diff": "", "sha": "0" * 64}

    code = L.extract_code(raw_code, "python")
    func_name = ""
    try:
        for _n in ast.walk(ast.parse(code)):
            if isinstance(_n, ast.FunctionDef) and len(_n.args.args) == 1:
                func_name = _n.name
                break
    except SyntaxError:
        pass
    if not code or not func_name:
        return {"task": "self_causal_explore", "ok": False, "code": code, "error": "missing 1-arg function def", "path": "", "diff": "", "sha": hashlib.sha256(code.encode()).hexdigest()}

    # Step 2: Run her function in viv-vm on the 3 probe inputs + the holdout input
    from viv_alu_transducer import ALU_PRELUDE, describe_value_in_words, parse_word_or_literal
    probe_runner = (
        f"{ALU_PRELUDE}\n{code}\n\n"
        "import json\n"
        f"_inputs = {sample_inputs}\n"
        f"_holdout = {holdout_expr}\n"
        f"_pairs = [{{'in': x, 'out': {func_name}(x)}} for x in _inputs]\n"
        f"_hout = {func_name}(_holdout)\n"
        "print('__TRACE__' + json.dumps({'pairs': _pairs, 'holdout_out': _hout}))\n"
    )
    rc, out, err = _dexec(probe_runner)
    if rc != 0 or "__TRACE__" not in out:
        err_msg = (err or out).strip()
        W.update(code, False, err_msg, "", "self_causal_explore")
        return {"task": "self_causal_explore", "ok": False, "code": code, "error": err_msg, "path": "", "diff": "", "sha": hashlib.sha256(code.encode()).hexdigest()}

    trace = json.loads(out.split("__TRACE__", 1)[1].strip())
    pairs = trace["pairs"]
    actual_holdout = trace["holdout_out"]
    effects = infer_io_effects(pairs)

    # Step 3: Show Viv her own code + the 3 real (input -> output) pairs (with ALU word-neuron transduction)
    sys_pred = (
        "You are examining a Python function you wrote and the actual outputs it produced.\n"
        "Reply in EXACTLY two lines:\n"
        "EXPLANATION: <one sentence explaining what the function did to the input>\n"
        "PREDICTED: <exact return value (you may write number words like 'twelve' or literals)>"
    )
    usr_pred = (
        f"Your function:\n```python\n{code}\n```\n\n"
        f"Observed input -> output trace from execution (with ALU word-neuron grounding):\n"
        + "\n".join(
            f"  {func_name}({describe_value_in_words(p['in'])}) -> {describe_value_in_words(p['out'])}"
            for p in pairs
        )
        + f"\n\nNow predict the output for:\n  {func_name}({describe_value_in_words(ast.literal_eval(holdout_expr))})\n"
        "Reply with EXPLANATION: and PREDICTED: on two lines."
    )
    raw_pred = _call_llm(sys_pred, usr_pred, temp=0.1)
    explanation, predicted = "", "__UNPARSED__"
    for line in raw_pred.splitlines():
        if line.strip().upper().startswith("EXPLANATION:"):
            explanation = line.split(":", 1)[1].strip()
        elif line.strip().upper().startswith("PREDICTED:"):
            val_str = line.split(":", 1)[1].strip().strip("`")
            if "->" in val_str:
                val_str = val_str.split("->", 1)[1].strip()
            if "=" in val_str and val_str.startswith(func_name):
                val_str = val_str.split("=", 1)[1].strip()
            predicted = parse_word_or_literal(val_str)
    if not explanation:
        explanation = raw_pred.splitlines()[0][:200] if raw_pred else ""
    if predicted == "__UNPARSED__":
        # Robust semantic extraction from prose:
        patterns = [
            r"(?:predicted(?:\s+output)?(?:\s+for\s+this\s+case)?\s+is|returns?\s+the\s+output\s+as|returns?)\s+['\"`]?([A-Za-z0-9_\-\[\]]+)",
            r"`([^`]+)`",
            r"(\[[^\]]+\])",
        ]
        for p in patterns:
            m = re.search(p, raw_pred, re.I)
            if m:
                cand = parse_word_or_literal(m.group(1).strip("'\"` "))
                if cand != "__UNPARSED__":
                    predicted = cand
                    break

    understood = (predicted == actual_holdout) or (str(predicted).strip(" '\"") == str(actual_holdout).strip(" '\""))

    # Step 4: Bond the AST concepts in her function to the observed output effects
    concepts = W.extract_concepts(code)
    with sqlite3.connect(DB, timeout=30) as c:
        cur = c.cursor()
        for c_node in concepts:
            for eff in effects:
                row = cur.execute(
                    "SELECT weight FROM function_bonds WHERE source_pattern=? AND target_pattern=?",
                    (c_node, eff),
                ).fetchone()
                w0 = row[0] if row else 0.5
                lr = 0.15 if understood else 0.20
                target = 1.0 if understood else 0.0
                w1 = min(0.99, max(0.01, w0 + lr * (target - w0)))
                rel = "LOCKED_CAUSAL_BOND" if (understood and w1 >= 0.80) else "CAUSAL_IO_EFFECT"
                cur.execute(
                    "INSERT INTO function_bonds(source_pattern,target_pattern,relation,weight) VALUES(?,?,?,?) "
                    "ON CONFLICT(source_pattern,target_pattern) DO UPDATE SET weight=?, relation=?",
                    (c_node, eff, rel, w1, w1, rel),
                )
        now = datetime.now(timezone.utc).isoformat()
        disc_id = f"DISC_{step_k}_{hashlib.sha256((code + now).encode()).hexdigest()[:10]}"
        seal = hashlib.sha256(json.dumps([disc_id, code, pairs, effects, understood]).encode()).hexdigest()
        cur.execute(
            "INSERT INTO viv_causal_discoveries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                disc_id,
                func_name,
                code,
                json.dumps(pairs),
                json.dumps(effects),
                explanation,
                holdout_expr,
                json.dumps(predicted),
                json.dumps(actual_holdout),
                int(understood),
                now,
                seal,
            ),
        )
        c.commit()

    # Save inside container /work for epoch archival / broker export if understood
    cpath = f"/work/self_causal_explore/a{step_k}.py"
    annotated = (
        f"# Discovery: {disc_id}\n# Effects: {', '.join(effects)}\n"
        f"# Viv explanation: {explanation}\n"
        f"# Holdout {holdout_expr} -> predicted={predicted!r}, actual={actual_holdout!r} (understood={understood})\n"
        f"{code}\n"
    )
    subprocess.run(
        ["docker", "exec", "-i", "-w", "/work", CONTAINER, "sh", "-c", f"mkdir -p /work/self_causal_explore && cat > {cpath}"],
        input=annotated.encode(),
        capture_output=True,
    )
    err_str = "" if understood else f"prediction mismatch on {holdout_expr}: predicted {predicted!r} != actual {actual_holdout!r}"
    return {
        "task": "self_causal_explore",
        "ok": understood,
        "code": code,
        "error": err_str,
        "path": cpath,
        "diff": "",
        "sha": hashlib.sha256(code.encode()).hexdigest(),
    }


if __name__ == "__main__":
    res = run_causal_discovery(1)
    print(json.dumps({k: res[k] for k in ("task", "ok", "error", "path")}, indent=2))
