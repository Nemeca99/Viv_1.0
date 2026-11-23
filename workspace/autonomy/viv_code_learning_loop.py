"""Viv code-learning loop: propose -> deterministic gate -> receipt.

Model output is only a proposal. Python code is accepted when pre-written tests
pass in a subprocess. Rust code is accepted when `rustc --test` builds and the
tests pass. Every attempt (pass or fail) is appended to a JSONL receipt log with
a SHA-256 hash. Verified code is stored in viv_code_topology.sqlite3 (Python)
and autonomy/viv_verified_rust (Rust).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AUTONOMY = Path(__file__).resolve().parent
RECEIPTS = AUTONOMY / "learning" / "code_learning_receipts.jsonl"
RUST_DIR = AUTONOMY / "viv_verified_rust"
SANDBOX = Path(os.environ.get("VIV_SANDBOX", r"E:\Viv_Sandbox"))
SANDBOX.mkdir(parents=True, exist_ok=True)
API_URL = os.environ.get("VIV_PROPOSER_URL", "http://127.0.0.1:1234/v1/chat/completions")
MODEL = os.environ.get("VIV_TUTOR_MODEL", "deepseek-coder-6.7b-base")
RUSTC = os.environ.get("RUSTC", "rustc")
MAX_ATTEMPTS = int(os.environ.get("VIV_MAX_ATTEMPTS", "12"))
# Bare `docker` resolves to Docker Desktop; set VIV_DOCKER to route it through WSL,
# e.g. VIV_DOCKER="wsl.exe -d Ubuntu -- docker". Default is unchanged.
DOCKER = os.environ.get("VIV_DOCKER", "docker").split()

# Tests are written by the Architect side, never by the proposer.
CURRICULUM = [
    {"id": "py_reverse_string", "lang": "python", "level": 1,
     "spec": "def reverse_string(s: str) -> str: return s reversed",
     "tests": "assert reverse_string('abc')=='cba'\nassert reverse_string('')==''\nassert reverse_string('a')=='a'"},
    {"id": "py_factorial", "lang": "python", "level": 1,
     "spec": "def factorial(n: int) -> int: n! for n>=0",
     "tests": "assert factorial(0)==1\nassert factorial(5)==120\nassert factorial(10)==3628800"},
    {"id": "py_is_palindrome", "lang": "python", "level": 1,
     "spec": "def is_palindrome(s: str) -> bool: case-insensitive, ignore non-alphanumerics",
     "tests": "assert is_palindrome('A man, a plan, a canal: Panama')\nassert not is_palindrome('abc')\nassert is_palindrome('')"},
    {"id": "py_word_freq", "lang": "python", "level": 2,
     "spec": "def word_freq(text: str) -> dict[str,int]: lowercase word counts split on whitespace",
     "tests": "assert word_freq('a b a')=={'a':2,'b':1}\nassert word_freq('')=={}\nassert word_freq('A a')=={'a':2}"},
    {"id": "rs_fib", "lang": "rust", "level": 1,
     "spec": "pub fn fib(n: u32) -> u64: nth Fibonacci, fib(0)=0, fib(1)=1",
     "tests": "#[cfg(test)] mod t { use super::*; #[test] fn a(){ assert_eq!(fib(0),0); assert_eq!(fib(1),1); assert_eq!(fib(10),55); assert_eq!(fib(50),12586269025); } }"},
    {"id": "rs_is_prime", "lang": "rust", "level": 1,
     "spec": "pub fn is_prime(n: u64) -> bool",
     "tests": "#[cfg(test)] mod t { use super::*; #[test] fn a(){ assert!(!is_prime(0)); assert!(!is_prime(1)); assert!(is_prime(2)); assert!(is_prime(97)); assert!(!is_prime(100)); } }"},
    {"id": "rs_reverse", "lang": "rust", "level": 1,
     "spec": "pub fn reverse(s: &str) -> String: reverse the chars",
     "tests": "#[cfg(test)] mod t { use super::*; #[test] fn a(){ assert_eq!(reverse(\"abc\"),\"cba\"); assert_eq!(reverse(\"\"),\"\"); } }"},
]


def _receipt(entry: dict) -> None:
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    body = json.dumps(entry, sort_keys=True)
    entry["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    RECEIPTS.parent.mkdir(parents=True, exist_ok=True)
    with RECEIPTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _bare_rust(text: str) -> str:
    """Keep top-level Rust items (balanced braces); stop where trailing prose begins."""
    item = re.compile(r"\s*(?:#\[|//|pub\b|fn\b|use\b|struct\b|enum\b|impl\b|const\b|static\b|mod\b|trait\b|type\b)")
    pos, end = 0, 0
    while pos < len(text) and item.match(text, pos):
        depth, started, i = 0, False, pos
        while i < len(text):
            ch = text[i]
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}" and depth:
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            elif ch == ";" and depth == 0 and started is False and not text[pos:i].lstrip().startswith(("pub fn", "fn", "#[")):
                i += 1
                break
            i += 1
        if depth != 0:
            break
        end = pos = i
    return text[:end].strip()

def _bare_python(text: str) -> str:
    """Longest leading run of lines that parses as Python; drop trailing prose."""
    import ast
    lines = text.splitlines()
    for n in range(len(lines), 0, -1):
        chunk = "\n".join(lines[:n]).strip()
        try:
            ast.parse(chunk)
            return chunk
        except SyntaxError:
            continue
    return ""


def extract_code(text: str, lang: str) -> str:
    """Prefer a closed fenced block; otherwise strip any leading fence and recover bare code."""
    m = re.search(r"```(?:%s|py|rs)?\s*\n(.*?)```" % lang, text, re.S)
    if m:
        return m.group(1).strip()
    clean = re.sub(r"^```[a-zA-Z0-9_-]*\s*\n", "", text.strip())
    return _bare_rust(clean) if lang == "rust" else _bare_python(clean)

def past_failures(task_id: str, limit: int = 3) -> list[dict]:
    """Negative evidence from earlier runs: distinct failed attempts and their errors."""
    out, seen = [], set()
    if RECEIPTS.exists():
        for line in reversed(RECEIPTS.read_text(encoding="utf-8").splitlines()):
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get("task") == task_id and j.get("stage") == "GATE_REJECTED" and j["error"][:80] not in seen:
                seen.add(j["error"][:80])
                out.append({"code": j["code"], "error": j["error"], "diff": j.get("diff", "")})
                if len(out) >= limit:
                    break
    return out


def compare_to_reference(task: dict, code: str) -> str:
    """Diff her code against the known-good reference; returned text is fed back to her."""
    import difflib
    sys.path.insert(0, str(AUTONOMY))
    from viv_reference_examples import REFERENCE
    ref = REFERENCE.get(task["id"])
    if not ref:
        return ""
    diff = difflib.unified_diff(code.splitlines(), ref.splitlines(), "yours", "reference", lineterm="", n=1)
    return "\n".join(diff)[:900]


LESSONS = AUTONOMY / "learning" / "code_failure_lessons.json"


def error_key(err: str, lang: str) -> str:
    """Stable label for a failure: compiler code (E0425), exception type, or a coarse class."""
    m = re.search(r"error\[(E\d+)\]", err) or re.search(r"\b(\w+Error|\w+Warning)\b", err)
    if m:
        return m.group(1)
    if "no code found" in err or "no fenced" in err:
        return "NO_CODE_BLOCK"
    if "panicked" in err or "AssertionError" in err:
        return "WRONG_OUTPUT"
    return "OTHER"


def blame(err: str, code: str) -> str:
    """Backward pass: trace the error to the exact source lines responsible."""
    lines = code.splitlines()
    hits = sorted({int(n) for n in re.findall(r"t\.(?:rs|py)[\":,]+\s*(\d+)|line (\d+)", err) for n in n if n})
    out = []
    for n in hits:
        for i in range(max(1, n - 1), min(len(lines), n + 1) + 1):
            out.append(f"{i}: {lines[i - 1]}")
    return "\n".join(dict.fromkeys(out))[:500]


LEDGER = AUTONOMY / "learning" / "code_failure_ledger.jsonl"


def _load_lessons() -> dict:
    """Derived view over the append-only ledger: newest distinct fixes per error key."""
    lessons: dict = {}
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            entry = lessons.setdefault(j["key"], {"seen": 0, "fixes": []})
            entry["seen"] += 1
            if j["delta"] and j["delta"] not in entry["fixes"]:
                entry["fixes"].append(j["delta"])
    return lessons


def learn_from_fix(task: dict, failures: list[dict], fixed_code: str) -> None:
    """Credit assignment: when a failing task finally passes, APPEND the change that fixed each error type.

    Nothing is trimmed or overwritten; the ledger keeps every failure and every fix.
    """
    import difflib
    if not failures:
        return
    bad = failures[-1]["code"]
    delta = "\n".join(difflib.unified_diff(bad.splitlines(), fixed_code.splitlines(), "failed", "fixed", lineterm="", n=0))[:600]
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as fh:
        for f in failures:
            row = {"ts": datetime.now(timezone.utc).isoformat(), "task": task["id"],
                   "key": f"{task['lang']}:{error_key(f['error'], task['lang'])}",
                   "failed_code_sha256": hashlib.sha256(f["code"].encode()).hexdigest(), "delta": delta}
            fh.write(json.dumps(row) + "\n")

def forward_hint(task: dict, last: dict) -> str:
    """Forward pass: localized blame plus past fixes for this error type, fed into the next attempt."""
    if task.get("id") == "rs_fib":
        return ("CRITICAL STRUCTURAL HINT: use u64, iterative not recursive. Maintain two running "
                "values starting (0, 1); each of n steps update both (next = a + b, then shift). "
                "Return the first running value after the loop.")
    if task.get("id") == "py_second_largest":
        return "CRITICAL STRUCTURAL HINT: Do NOT return a list. Return a single integer or None. Pattern: d = sorted(set(xs)); return d[-2] if len(d) >= 2 else None"
    if task.get("id") == "py_roman":
        return "CRITICAL STRUCTURAL HINT: Iterate through vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]; append symbol while n >= val."
    k = f"{task['lang']}:{error_key(last['error'], task['lang'])}"
    parts = [f"ERROR TYPE: {k}"]
    b = blame(last["error"], last["code"])
    if b:
        parts.append("BLAMED LINES:\n" + b)
    fixes = _load_lessons().get(k, {}).get("fixes", [])
    if fixes:
        parts.append("WHAT FIXED THIS ERROR BEFORE:\n" + "\n".join(fixes[-2:]))
    return "\n".join(parts)

def propose(task: dict, prior: list[dict], examples: list[str]) -> str:
    sys.path.insert(0, str(AUTONOMY))
    from viv_reference_examples import STUDY
    from viv_alu_transducer import transduce_digits_in_spec
    examples = list(STUDY.get(task["lang"], [])) + list(examples)
    system = (f"You write clean, standard-library {task['lang']} code (do NOT import third-party packages like numpy). Reply with ONLY one fenced code block "
              "containing the implementation. No tests, no main, no explanation.")
    user = f"Implement: {transduce_digits_in_spec(task['spec'])}"
    if task["lang"] == "python":
        user += "\n(ALU word-number constants ZERO, ONE, TWO, THREE, FOUR, FIVE, SIX, SEVEN, EIGHT, NINE, TEN, TWELVE, FIFTEEN, TWENTY, HUNDRED are also available.)"
    if examples:
        user += "\n\nVerified examples of your earlier work:\n" + "\n---\n".join(examples[-2:])
    if prior:
        user += "\n\nThese attempts FAILED. Do not repeat them:"
        for f in prior[-3:]:
            user += f"\n---\n{f['code'][:700]}\nERROR: {f['error'][:300]}"
            if f.get("diff"):
                user += f"\nHOW THE REFERENCE DIFFERS (- yours, + reference):\n{f['diff']}"
        user += "\n---\n" + forward_hint(task, prior[-1]) + "\nWrite a different, correct implementation."
    payload = {"model": MODEL, "temperature": min(0.9, 0.2 + 0.1 * len(prior)), "max_tokens": 256,
               "stop": ["\nUSER:", "\nSYSTEM:"],
               "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]


def gate_python(code: str, tests: str) -> tuple[bool, str]:
    script = f"{code}\n\n{tests}\nprint('__OK__')\n"
    try:
        r = subprocess.run(
            [*DOCKER, "run", "--rm", "-i", "--network", "none", "--read-only",
             "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "32",
             "--memory", "256m", "--cpus", "1", "--user", "10001:10001",
             "--entrypoint", "python", "viv-vm:1", "-I", "-"],
            input=script, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "GATE_UNAVAILABLE: docker not found"
    if r.returncode == 125:
        return False, "GATE_UNAVAILABLE: " + r.stderr.strip()[:300]
    ok = r.returncode == 0 and "__OK__" in r.stdout
    return ok, "" if ok else (r.stderr or r.stdout).strip()


RUST_IMAGE = os.environ.get("VIV_RUST_IMAGE", "rust:1.90.0-slim-bookworm")


def gate_rust(code: str, tests: str) -> tuple[bool, str]:
    """Rust is built and tested inside a locked-down container; no host mount.

    No network, read-only root, all capabilities dropped, bounded pids/memory/cpu.
    Source is piped over stdin (like gate_python); build output goes to a bounded
    tmpfs, so nothing leaves the container and no host drive is mounted.
    """
    source = f"{code}\n\n{tests}\n"
    cmd = [*DOCKER, "run", "--rm", "-i", "--network", "none", "--read-only",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
           "--pids-limit", "256", "--memory", "2g", "--cpus", "2",
           "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
           "--user", "10001:10001", "-w", "/tmp", RUST_IMAGE,
           "sh", "-c",
           "rustc --edition 2021 --test --crate-name viv_test - -o /tmp/t && /tmp/t"]
    try:
        r = subprocess.run(cmd, input=source, capture_output=True, text=True, timeout=240)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, "GATE_UNAVAILABLE: docker not found"
    if r.returncode == 125 or "Cannot connect to the Docker daemon" in r.stderr or "error during connect" in r.stderr:
        return False, "GATE_UNAVAILABLE: " + r.stderr.strip()[:300]
    return r.returncode == 0, "" if r.returncode == 0 else (r.stderr + r.stdout).strip()

def store_verified(task: dict, code: str) -> None:
    if task["lang"] == "python":
        sys.path.insert(0, str(AUTONOMY))
        from viv_python_code_cortex import PythonCodeCortex
        PythonCodeCortex().graduate_to_database(task["id"], task["spec"], code, task["tests"])
    else:
        RUST_DIR.mkdir(parents=True, exist_ok=True)
        (RUST_DIR / f"{task['id']}.rs").write_text(code + "\n", encoding="utf-8")


def verified_examples(lang: str) -> list[str]:
    if lang == "python":
        import sqlite3
        db = AUTONOMY / "viv_code_topology.sqlite3"
        if not db.exists():
            return []
        try:
            with sqlite3.connect(db) as c:
                return [r[0] for r in c.execute(
                    "SELECT verified_python_code FROM verified_code_primitives "
                    "WHERE verified_python_code NOT LIKE '//%' AND verified_python_code NOT LIKE '/*%' "
                    "ORDER BY registered_at DESC LIMIT 2"
                )]
        except sqlite3.Error:
            return []
    return [p.read_text(encoding="utf-8") for p in sorted(RUST_DIR.glob("*.rs"))[-2:]] if RUST_DIR.exists() else []


def already_passed(task_id: str) -> bool:
    if not RECEIPTS.exists():
        return False
    return any('"stage": "ACCEPTED"' in l and f'"task": "{task_id}"' in l for l in RECEIPTS.read_text(encoding="utf-8").splitlines())


def run_task(task: dict) -> bool:
    if already_passed(task["id"]):
        return True
    gate = gate_python if task["lang"] == "python" else gate_rust
    prior: list[dict] = past_failures(task["id"])
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            code = extract_code(propose(task, prior, verified_examples(task["lang"])), task["lang"])
        except Exception as exc:  # proposer unavailable
            _receipt({"task": task["id"], "attempt": attempt, "stage": "PROPOSER_FAILURE", "error": str(exc)})
            return False
        if not code:
            _receipt({"task": task["id"], "lang": task["lang"], "attempt": attempt, "passed": False, "stage": "GATE_REJECTED", "code": "", "error": "no code found in reply"})
            continue
        ok, err = gate(code, task["tests"])
        if task["lang"] == "python" and not err.startswith("GATE_UNAVAILABLE"):
            import viv_path_weights
            from viv_reference_examples import REFERENCE as _REF
            _w = viv_path_weights.update(code, ok, err, _REF.get(task["id"], ""), task["id"])
        else:
            _w = None
        if err.startswith("GATE_UNAVAILABLE"):
            _receipt({"task": task["id"], "attempt": attempt, "stage": "GATE_UNAVAILABLE", "error": err})
            return False
        _receipt({"task": task["id"], "lang": task["lang"], "attempt": attempt, "passed": ok,
                  "stage": "ACCEPTED" if ok else "GATE_REJECTED", "code": code, "error": err[:2000],
                  "diff": "" if ok else compare_to_reference(task, code), "weights": _w})
        if ok:
            learn_from_fix(task, prior, code)
            store_verified(task, code)
            return True
        prior.append({"code": code, "error": err, "diff": compare_to_reference(task, code)})
    return False


def main(argv: list[str]) -> int:
    only = set(argv[1:])
    results = {t["id"]: run_task(t) for t in CURRICULUM if not only or t["id"] in only}
    print(json.dumps(results, indent=2))
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
