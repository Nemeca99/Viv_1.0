"""Viv epoch driver: fill the container, grade, feed forward, update weights, clear, repeat.

One epoch:
  1. FILL    Viv proposes Python for curriculum tasks over and over; every attempt is
             run and saved INSIDE the container (/work, RAM-backed tmpfs). Ends at the
             first of: /work usage >= FILL_PCT, MAX_ATTEMPTS, MAX_SECONDS.
             Inside the epoch, each failure feeds forward into the next attempt
             (blamed lines, error type, diff to reference, past fixes).
  2. FILTER  Results are graded by the deterministic gate (tests pass or not).
  3. UPDATE  Batch backward pass: path weights are updated from every graded attempt
             of the epoch; verified code is stored; fix lessons are recorded.
  4. EXPORT  Passing files leave the container ONLY through the Rust broker.
  5. SEAL    An epoch record (counts + SHA-256 over all attempt hashes) is written to
             autonomy/ancestral_epochs/. History is never deleted.
  6. CLEAR   The container is restarted, which wipes every tmpfs. Then repeat.

usage: python viv_epoch_driver.py [--epochs N] [--verify-curriculum]
env:   VIV_MAX_ATTEMPTS (40), VIV_MAX_SECONDS (900), VIV_FILL_PCT (90)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

AUTONOMY = Path(__file__).resolve().parent
sys.path.insert(0, str(AUTONOMY))

import viv_code_learning_loop as L  # noqa: E402
import viv_path_weights as W  # noqa: E402
from viv_python_curriculum import TASKS  # noqa: E402
import viv_causal_function_explorer as CFE  # noqa: E402
import viv_uml_compiler as UMLC  # noqa: E402
from viv_reference_examples import REFERENCE  # noqa: E402

CONTAINER = os.environ.get("VIV_CONTAINER", "viv-vm")
BROKER = Path(r"L:\LocalCoder\workspace\viv_vm\broker\target\release\viv-broker.exe")
EPOCHS_DIR = AUTONOMY / "ancestral_epochs"
MAX_ATTEMPTS = int(os.environ.get("VIV_MAX_ATTEMPTS", "40"))
MAX_SECONDS = int(os.environ.get("VIV_MAX_SECONDS", "900"))
FILL_PCT = int(os.environ.get("VIV_FILL_PCT", "90"))
PY_TASKS = [t for t in L.CURRICULUM if t["lang"] == "python"] + TASKS


def dexec(args: list[str], stdin: bytes | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "exec", "-i", "-w", "/work", CONTAINER, *args],
                          input=stdin, capture_output=True, timeout=timeout)


def container_ok() -> bool:
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def fill_percent() -> int:
    r = dexec(["sh", "-c", "df -P /work | tail -1"])
    try:
        return int(r.stdout.decode().split()[4].rstrip("%"))
    except (IndexError, ValueError):
        return 0


def gate_in_container(task: dict, attempt: int, code: str) -> tuple[bool, str, str]:
    """Run her code + the Architect's tests inside the container. Returns (ok, error, saved_path)."""
    import importlib, viv_alu_transducer
    importlib.reload(viv_alu_transducer)
    ALU_PRELUDE = viv_alu_transducer.ALU_PRELUDE
    d = f"/work/{task['id']}"
    path = f"{d}/a{attempt}.py"
    dexec(["sh", "-c", f"mkdir -p {d} && cat > {path}"], stdin=code.encode())
    script = f"{ALU_PRELUDE}\n{code}\n\n{task['tests']}\nprint('__OK__')\n"
    try:
        r = dexec(["python", "-"], stdin=script.encode(), timeout=30)
    except subprocess.TimeoutExpired:
        return False, "timeout", path
    out, err = r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")
    ok = r.returncode == 0 and "__OK__" in out
    return ok, "" if ok else (err or out).strip(), path


def self_generate_and_test(step_k: int) -> dict:
    """Viv generates her own word list + Python script in /work and tests herself against it."""
    import urllib.request
    prompt = (
        "Write a standalone Python script that FIRST creates and writes '/work/viv_words.txt' using open('/work/viv_words.txt', 'w'):\n"
        "1. Write 5 lines into '/work/viv_words.txt' with format 'word:category' (e.g. 'cat:animal\\napple:fruit\\n...').\n"
        "2. Then open('/work/viv_words.txt', 'r') to read them back, parse each line using line.strip().split(':'), store into a dict, and assert len(dict) > 0.\n"
        "Reply with ONLY one ```python ... ``` block."
    )
    h = W.hints(task_id="self_word_web")
    if h:
        prompt += "\n\n" + h
    payload = {
        "model": L.MODEL,
        "temperature": 0.4,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": "You write clean, self-testing Python inside /work. Reply only with a ```python``` block."},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(L.API_URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = json.loads(r.read())["choices"][0]["message"]["content"]
    code = L.extract_code(raw, "python")
    if not code:
        return {"task": "self_word_web", "ok": False, "code": "", "error": "no code found in reply", "path": "", "diff": "", "sha": hashlib.sha256(b"").hexdigest()}
    ok, err, path = gate_in_container({"id": "self_word_web", "tests": "import os; assert os.path.exists('/work/viv_words.txt') and os.path.getsize('/work/viv_words.txt') > 0"}, step_k, code)
    return {"task": "self_word_web", "ok": ok, "code": code, "error": err, "path": path, "diff": "", "sha": hashlib.sha256(code.encode()).hexdigest()}

def verify_curriculum() -> int:
    bad = 0
    for t in TASKS:
        ok, err, _ = gate_in_container(t, 0, t["reference"])
        print(("OK  " if ok else "FAIL"), t["id"], err[:120])
        bad += not ok
    dexec(["rm", "-rf", "/work/*"])
    return bad


def run_epoch(n: int) -> dict:
    started = time.time()
    attempts: list[dict] = []
    passed_ids: set[str] = set()
    i = 0
    while True:
        pct = fill_percent()
        if pct >= FILL_PCT or len(attempts) >= MAX_ATTEMPTS or time.time() - started > MAX_SECONDS:
            reason = "fill" if pct >= FILL_PCT else "attempts" if len(attempts) >= MAX_ATTEMPTS else "time"
            break
        import importlib, viv_python_curriculum, viv_code_learning_loop
        importlib.reload(viv_python_curriculum)
        importlib.reload(viv_code_learning_loop)
        L = viv_code_learning_loop
        current_py_tasks = [t for t in L.CURRICULUM if t["lang"] == "python"] + viv_python_curriculum.TASKS
        all_pending = [t for t in current_py_tasks if t["id"] not in passed_ids and not L.already_passed(t["id"])]
        if not all_pending:
            # All curriculum levels mastered: run pure self-authored causal function discovery & word webs
            rec = CFE.run_causal_discovery(i + 1) if i % 2 == 0 else self_generate_and_test(i + 1)
            attempts.append(rec)
            print(f"  [{len(attempts):>3}] {rec['task']:<20} {'PASS' if rec['ok'] else 'fail'}  fill={pct}%", flush=True)
            i += 1
            continue
        min_level = min(t.get("level", 1) for t in all_pending)
        pending = [t for t in all_pending if t.get("level", 1) == min_level]
        # Once Grade 0 & Grade 1 basics are passed (min_level >= 2), interleave UML compilation, causal discovery, and word webs
        if min_level >= 2 and i % 4 == 3:
            mode = (i // 4) % 3
            rec = (
                UMLC.self_author_uml_program(i + 1)
                if mode == 0
                else CFE.run_causal_discovery(i + 1)
                if mode == 1
                else self_generate_and_test(i + 1)
            )
            attempts.append(rec)
            print(f"  [{len(attempts):>3}] {rec['task']:<20} {'PASS' if rec['ok'] else 'fail'}  fill={pct}%", flush=True)
            i += 1
            continue
        task = pending[i % len(pending)]
        i += 1
        task_fails = [a for a in attempts if a["task"] == task["id"] and not a["ok"]]
        # Subtractive rebirth: every 3rd attempt, reset prior to [] to break local attractor traps
        if len(task_fails) % 3 == 0:
            prior = []
        else:
            prior = task_fails[-1:] or L.past_failures(task["id"])[-1:]
        try:
            code = L.extract_code(L.propose(task, prior, L.verified_examples("python")), "python")
        except Exception as exc:
            L._receipt({"task": task["id"], "stage": "PROPOSER_FAILURE", "error": str(exc)})
            reason = "proposer_down"
            break
        k = sum(a["task"] == task["id"] for a in attempts) + 1
        if not code:
            rec = {"task": task["id"], "ok": False, "code": "", "error": "no code found in reply", "path": ""}
        else:
            ok, err, path = gate_in_container(task, k, code)
            rec = {"task": task["id"], "ok": ok, "code": code, "error": err, "path": path}
            if ok:
                passed_ids.add(task["id"])
        rec["diff"] = "" if rec["ok"] else L.compare_to_reference(task, rec["code"])
        rec["sha"] = hashlib.sha256(rec["code"].encode()).hexdigest()
        attempts.append(rec)
        print(f"  [{len(attempts):>3}] {task['id']:<20} {'PASS' if rec['ok'] else 'fail'}  fill={pct}%", flush=True)

    # FILTER + UPDATE: batch backward pass over the whole epoch
    by_id = {t["id"]: t for t in PY_TASKS}
    exported, denied = [], []
    for a in attempts:
        task = by_id.get(a["task"], {"id": a["task"], "lang": "python", "spec": "self-generated word/concept study", "tests": ""})
        w = W.update(a["code"], a["ok"], a["error"], REFERENCE.get(a["task"], ""), a["task"]) if a["code"] else None
        L._receipt({"task": a["task"], "lang": "python", "epoch": n, "passed": a["ok"],
                    "stage": "ACCEPTED" if a["ok"] else "GATE_REJECTED", "code": a["code"],
                    "error": a["error"][:2000], "diff": a["diff"], "weights": w})
    for tid in passed_ids:
        win = next(a for a in attempts if a["task"] == tid and a["ok"])
        before = [a for a in attempts if a["task"] == tid and not a["ok"]]
        t_obj = by_id.get(tid, {"id": tid, "lang": "python", "spec": "self-generated word/concept study", "tests": ""})
        L.learn_from_fix(t_obj, [{"code": b["code"], "error": b["error"]} for b in before if b["code"]], win["code"])
        L.store_verified(t_obj, win["code"])
        # EXPORT: only through the Rust broker
        r = subprocess.run([str(BROKER), "export", win["path"], "--container", CONTAINER], capture_output=True, text=True)
        (exported if r.returncode == 0 else denied).append({"task": tid, "broker": r.stdout.strip()})

    # SEAL: epoch record with a hash over every attempt (history is never deleted)
    EPOCHS_DIR.mkdir(exist_ok=True)
    seal = hashlib.sha256("".join(sorted(a["sha"] for a in attempts)).encode()).hexdigest()
    record = {"epoch": n, "utc": datetime.now(timezone.utc).isoformat(), "ended_by": reason,
              "attempts": len(attempts), "passed_tasks": sorted(passed_ids),
              "pass_rate": round(sum(a["ok"] for a in attempts) / max(1, len(attempts)), 3),
              "exported": exported, "broker_denied": denied, "seal_sha256": seal,
              "seconds": round(time.time() - started)}
    (EPOCHS_DIR / f"viv_python_epoch_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{n}.json").write_text(
        json.dumps(record, indent=1), encoding="utf-8")

    # CLEAR: restart wipes every tmpfs in the container
    subprocess.run(["docker", "restart", "-t", "2", CONTAINER], capture_output=True)
    time.sleep(2)
    record["fill_after_clear"] = fill_percent()
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--verify-curriculum", action="store_true")
    a = ap.parse_args()
    if not container_ok():
        print("container viv-vm is not running")
        return 2
    if a.verify_curriculum:
        return 1 if verify_curriculum() else 0
    for n in range(1, a.epochs + 1):
        print(f"== epoch {n} ==", flush=True)
        rec = run_epoch(n)
        print(json.dumps({k: rec[k] for k in ("epoch", "ended_by", "attempts", "pass_rate", "passed_tasks", "fill_after_clear")}))
        if rec["ended_by"] in ("curriculum_complete", "proposer_down"):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
