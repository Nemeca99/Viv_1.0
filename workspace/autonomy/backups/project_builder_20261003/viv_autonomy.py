"""Persistent local build worker and chat control surface.

Candidate code executes only in disposable, resource-limited containers. Passing
frozen examples records a tested capability; it does not prove general correctness
or constitute model-weight training or permission to rewrite the controller.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
CONTROLLER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
STATE = ROOT / "autonomy"
MODEL = "qwen3:8b-local"
MAX_ATTEMPTS = 5
OBJECTIVE = (
    "Build Viv into a continuously autonomous local system: choose useful next work, "
    "generate and build capabilities, independently evaluate outcomes, repair failures, "
    "retain and use experience, train and evaluate model improvements, recover and continue. "
    "Integrate with viv_chat_cli.py. The Architect retains intent and final authority."
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, root=STATE):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "state.sqlite3"
        with self.connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
                    status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    feedback TEXT NOT NULL DEFAULT '', created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS capabilities(
                    task_id TEXT PRIMARY KEY, path TEXT NOT NULL, code_hash TEXT NOT NULL,
                    receipt TEXT NOT NULL);
            """)
            for key, value in {"objective": OBJECTIVE, "enabled": True, "image": "",
                               "model": MODEL, "worker": {}}.items():
                con.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, canonical(value)))

    @contextlib.contextmanager
    def connect(self):
        con = sqlite3.connect(self.db, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=15000")
        try:
            with con:
                yield con
        finally:
            con.close()

    def get(self, key):
        with self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def set(self, key, value):
        with self.connect() as con:
            con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, canonical(value)))

    def event(self, kind, data):
        with self.connect() as con:
            con.execute("INSERT INTO events(at,kind,data) VALUES (?,?,?)", (time.time(), kind, canonical(data)))

    def add(self, spec):
        validate_spec(spec)
        encoded = canonical(spec)
        task_id = sha(encoded)[:20]
        with self.connect() as con:
            con.execute("INSERT OR IGNORE INTO tasks(id,spec,spec_hash,status,created) VALUES (?,?,?,?,?)",
                        (task_id, encoded, sha(encoded), "queued", time.time()))
        return task_id

    def status(self):
        with self.connect() as con:
            tasks = [dict(r) for r in con.execute(
                "SELECT id,status,attempts,feedback FROM tasks ORDER BY created DESC LIMIT 8")]
            capabilities = [dict(r) for r in con.execute(
                "SELECT c.task_id,c.path,c.code_hash,t.spec FROM capabilities c JOIN tasks t ON t.id=c.task_id")]
            for capability in capabilities:
                spec = json.loads(capability.pop("spec"))
                capability.update(title=spec["title"], requirement=spec["requirement"])
            events = [dict(r) for r in con.execute("SELECT at,kind,data FROM events ORDER BY id DESC LIMIT 5")]
        worker = self.get("worker") or {}
        worker["heartbeat_recent"] = time.time() - worker.get("at", 0) < 30
        return {"objective": self.get("objective"), "enabled": self.get("enabled"),
                "worker": worker, "tasks": tasks, "capabilities": capabilities,
                "recent_events": events, "weight_training": "not_implemented"}

    def experience(self):
        with self.connect() as con:
            rows = [dict(r) for r in con.execute(
                "SELECT id,spec,status,feedback FROM tasks ORDER BY created DESC LIMIT 6")]
        for row in rows:
            spec = json.loads(row.pop("spec"))
            row.update(title=spec["title"], requirement=spec["requirement"])
        return rows


def validate_spec(spec):
    if not isinstance(spec, dict) or set(spec) != {"title", "requirement", "cases"}:
        raise ValueError("Task must contain title, requirement, cases")
    if not isinstance(spec["title"], str) or not 1 <= len(spec["title"]) <= 150:
        raise ValueError("Invalid title")
    if not isinstance(spec["requirement"], str) or not 20 <= len(spec["requirement"]) <= 8000:
        raise ValueError("Invalid requirement")
    cases = spec["cases"]
    if not isinstance(cases, list) or not 3 <= len(cases) <= 30:
        raise ValueError("Require 3 to 30 frozen input/output cases")
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"input", "expected"}:
            raise ValueError("Each case must contain input and expected")
    if len(canonical(spec)) > 40000:
        raise ValueError("Task too large")


@contextlib.contextmanager
def file_lock(path, *, wait=0):
    """OS lock releases on process death; the file alone is never a live signal."""
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    deadline = time.monotonic() + wait
    acquired = False
    try:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"Lock busy: {path.name}")
                time.sleep(0.2)
        yield
    finally:
        if acquired:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        stream.close()


def worker_alive():
    try:
        with file_lock(STATE / "worker.lock"):
            return False
    except RuntimeError:
        return True


def ask_model(messages, *, json_mode=False):
    body = {"model": MODEL, "messages": messages, "stream": False, "think": False,
            "options": {"num_ctx": 8192, "num_predict": 2400, "temperature": 0.2},
            "keep_alive": "5m"}
    if json_mode:
        body["format"] = json_mode if isinstance(json_mode, dict) else "json"
    request = urllib.request.Request("http://127.0.0.1:11434/api/chat",
                                     data=canonical(body).encode(), headers={"Content-Type": "application/json"})
    with file_lock(STATE / "inference.lock", wait=360):
        with urllib.request.urlopen(request, timeout=240) as response:
            result = json.load(response)
    if result.get("done_reason") == "length":
        raise ValueError("Model response truncated")
    return result["message"]["content"].strip()


def docker(args, *, stdin=None, timeout=30):
    process = subprocess.Popen(["wsl", "-d", "Ubuntu", "--", "sudo", "-n", "docker", *args],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    chunks = {"out": bytearray(), "err": bytearray()}
    overflow = threading.Event()
    def drain(pipe, key):
        try:
            while block := pipe.read(4096):
                if len(chunks[key]) + len(block) > 1024 * 1024:
                    overflow.set()
                    process.kill()
                    break
                chunks[key].extend(block)
        finally:
            pipe.close()
    def feed():
        try:
            process.stdin.write((stdin or "").encode("utf-8"))
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()
    threads = [threading.Thread(target=drain, args=(process.stdout, "out"), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, "err"), daemon=True),
               threading.Thread(target=feed, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        for thread in threads:
            thread.join(timeout=2)
    if overflow.is_set():
        raise RuntimeError("Docker output exceeded 1 MiB limit")
    if process.returncode:
        raise RuntimeError(f"Docker {args[0]}: {chunks['err'].decode('utf-8', errors='replace')[-2000:]}")
    return chunks["out"].decode("utf-8").strip()


def provision_image(store):
    """Snapshot existing installed Python without stopping/recreating its container."""
    image = store.get("image")
    if image:
        docker(["image", "inspect", image])
        return image
    docker(["exec", "hviv_sandbox_core", "python3", "--version"])
    output = docker(["commit", "--no-pause", "hviv_sandbox_core"], timeout=120)
    image = output.splitlines()[-1]
    if not image.startswith("sha256:") or len(image) != 71:
        raise ValueError("No immutable sandbox image ID returned")
    store.set("image", image)
    store.event("sandbox_image_snapshot", {"image": image})
    return image


# This runner belongs to the controller. Candidate code is only ever imported
# inside an unprivileged container with no host mounts or network.
RUNNER = '''import json,sys,contextlib,io
namespace={}
payload=json.loads(sys.stdin.readline())
with contextlib.redirect_stdout(io.StringIO()):
    exec(compile(payload["code"],"candidate.py","exec"),namespace)
    result=namespace["solve"](payload["input"])
print(json.dumps(result,allow_nan=False))
'''


def evaluate(image, code, cases):
    results = []
    for case in cases:
        name = "viv-candidate-" + uuid.uuid4().hex
        try:
            output = docker([
                "run", "--rm", "--name", name, "--network=none", "--read-only",
                "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user=65534:65534",
                "--memory=256m", "--memory-swap=256m", "--cpus=1", "--pids-limit=32",
                "--ulimit", "fsize=1048576:1048576", "--log-driver=none",
                "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m", "--workdir=/tmp", "-i",
                "--entrypoint=python3", image, "-I", "-c", RUNNER],
                stdin=canonical({"code": code, "input": case["input"]}) + "\n", timeout=15)
            actual = json.loads(output)
            results.append({"passed": canonical(actual) == canonical(case.get("expected")),
                            "input": case["input"], "expected": case.get("expected"), "actual": actual})
        except Exception as exc:
            results.append({"passed": False, "error": str(exc)[-2000:], "input": case["input"]})
        finally:
            # A timed-out Docker client may leave its container alive.
            subprocess.run(["wsl", "-d", "Ubuntu", "--", "sudo", "-n", "docker", "rm", "-f", name],
                           capture_output=True, timeout=15)
    return results


def invoke_capability(task_id, value, *, store=None):
    store = store or Store()
    if not isinstance(task_id, str) or len(canonical(value)) > 32000:
        raise ValueError("Invalid capability invocation")
    with store.connect() as con:
        row = con.execute("SELECT * FROM capabilities WHERE task_id=?", (task_id,)).fetchone()
    if row is None:
        raise ValueError("Capability not registered")
    path = Path(row["path"]).resolve(strict=True)
    if (store.root / "attempts").resolve() not in path.parents:
        raise ValueError("Capability path outside attempt store")
    code = path.read_text(encoding="utf-8")
    if sha(code) != row["code_hash"]:
        raise ValueError("Capability changed after evaluation")
    result = evaluate(store.get("image"), code, [{"input": value}])[0]
    if "error" in result:
        store.event("capability_error", {"task_id": task_id, "error": result["error"]})
        raise RuntimeError(result["error"])
    receipt = {"task_id": task_id, "code_sha256": row["code_hash"],
               "input": value, "output": result["actual"], "scope": "sandbox_execution_observation"}
    store.event("capability_used", receipt)
    return receipt


def recall_for_task(store, requirement):
    """Use a behavior-checked generated retrieval tool when one is configured."""
    recent = store.experience()
    retriever = store.get("experience_retriever")
    if not retriever:
        return recent
    records = [{"id": r["id"], "status": r["status"],
                "reason": (r["requirement"] + " " + r["feedback"])[:2500]} for r in recent]
    words = [word.strip(".,:;()").lower() for word in requirement.split() if len(word) > 5]
    query = words[0] if words else "failed"
    try:
        output = invoke_capability(retriever, {"data": records, "options": {"query": query}}, store=store)["output"]
        selected = output["results"]
        known = {r["id"] for r in recent}
        if not isinstance(selected, list) or any(not isinstance(r, dict) or r.get("id") not in known for r in selected):
            raise ValueError("Retriever returned unknown records")
        ids = {r["id"] for r in selected}
        store.event("generated_memory_recall", {"capability": retriever, "query": query, "matched_ids": sorted(ids)})
        return [r for r in recent if r["id"] in ids] or recent
    except Exception as exc:
        store.event("memory_recall_fallback", {"error": str(exc)})
        return recent


def seed_task():
    return {"title": "Summarize actual build receipts",
            "requirement": "Implement solve(value). value is a list of receipt objects. Return an object "
            "with passed, failed, unknown integer counts. Count only the literal boolean true in the passed field "
            "as passed, literal false as failed; absent or any other value is unknown. This is for honest Viv telemetry.",
            "cases": [{"input": [], "expected": {"passed": 0, "failed": 0, "unknown": 0}},
                      {"input": [{"passed": True}, {"passed": False}, {}],
                       "expected": {"passed": 1, "failed": 1, "unknown": 1}},
                      {"input": [{"passed": "false"}, {"passed": 1}, {"passed": None}, {"passed": True}],
                       "expected": {"passed": 1, "failed": 0, "unknown": 3}}]}


def plan(store):
    experience = store.experience()
    for record in experience:
        # Raw failing outputs can contain fabricated records. They belong in
        # repair feedback, not the planner's inventory of real system data.
        record["feedback"] = ("Already built. Propose a different capability." if record["status"] == "tested"
                              else "Prior attempt did not establish a usable capability.")
    inventory = [{"title": e["title"], "status": e["status"],
                  "requirement": e["requirement"] if e["status"] == "tested" else "Invalid or failed prior proposal; do not copy it."}
                 for e in experience]
    gaps = ["Dependency-aware selection of runnable tasks is missing",
            "Comparing candidate and baseline evaluation evidence is missing"]
    if not store.get("experience_retriever"):
        gaps.insert(0, "Retrieval of relevant past failures by a query is missing")
    prompt = {"objective": store.get("objective"), "experience": inventory,
              "observed_gaps": gaps,
              "last_planning_feedback": store.get("planning_feedback")}
    output = ask_model([
        {"role": "system", "content": "Choose the next useful small capability toward the objective using actual "
         "experience. Capabilities must be pure Python stdlib functions solve(value) with JSON input/output. "
         "Do not repeat completed work. Return JSON with exactly title, requirement, cases. cases is a list of "
         "3-8 objects with input and expected. Include edge cases. No filesystem, network, subprocess or GPU. "
         "Every input must be a JSON object with data (the actual list or object to process) and options "
         "(query, sort, limit or other parameters). The function is solve(value); value['data'] and "
         "value['options'] carry ALL needed data. For retrieval put the records in data and query in options. "
         "Never assume hidden stored records or invent a fixed database. Define ordering, matching, empty-input "
         "and tie behavior explicitly. Test expectations must follow that exact rule. "
         "These are candidate tools for memory retrieval, task scheduling, evidence analysis and build planning. "
         "Avoid trivial variations that add no capability. This plan does not authorize controller changes."},
        {"role": "user", "content": canonical(prompt)}], json_mode=True)
    spec = json.loads(output)
    validate_spec(spec)
    if any(not isinstance(case["input"], dict) or set(case["input"]) != {"data", "options"}
           or not isinstance(case["input"]["options"], dict) for case in spec["cases"]):
        store.set("planning_feedback", "Rejected: every input needs exactly data and options; options must be an object. Put actual records in data, query parameters in options. A query alone cannot retrieve absent records.")
        store.event("plan_rejected", {"reason": store.get("planning_feedback"), "proposal": spec})
        return
    for existing in experience:
        similarity = difflib.SequenceMatcher(None, spec["requirement"].lower(),
                                             existing["requirement"].lower()).ratio()
        if similarity > 0.88 and existing["status"] in {"tested", "queued", "retry", "running", "redundant"}:
            message = "Rejected duplicate requirement. Choose a different observed gap: " + existing["title"]
            store.set("planning_feedback", message)
            store.event("plan_rejected", {"reason": message, "proposal": spec})
            return
    review = json.loads(ask_model([
        {"role": "system", "content": "Review a proposed pure function task BEFORE code is generated. "
         "Return JSON {\"valid\": true or false, \"reason\": string}. Check that all necessary data is in each "
         "input, rules are unambiguous, and EVERY expected result follows the written requirement. "
         "Reject contradictory examples, hardcoded external records, missing sort/matching rules. "
         "This is specification review only, not proof of correctness."},
        {"role": "user", "content": canonical(spec)}], json_mode=True))
    store.event("specification_review", {"spec": spec, "review": review})
    if review.get("valid") is not True:
        store.set("planning_feedback", str(review.get("reason", "Invalid review")))
        return
    task_id = store.add(spec)
    store.set("planning_feedback", "")
    store.event("model_planned_task", {"task_id": task_id, "test_origin": "model_authored"})


def build_one(store, image):
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM tasks WHERE status IN ('queued','retry') ORDER BY created LIMIT 1").fetchone()
        if row is None:
            return False
        task = dict(row)
        attempt = task["attempts"] + 1
        con.execute("UPDATE tasks SET status='running',attempts=? WHERE id=?", (attempt, task["id"]))
    spec = json.loads(task["spec"])
    artifact = store.root / "attempts" / task["id"] / f"{attempt:04d}"
    artifact.mkdir(parents=True, exist_ok=False)
    (artifact / "spec.json").write_text(task["spec"], encoding="utf-8")
    store.event("build_started", {"task_id": task["id"], "attempt": attempt})
    try:
        previous = artifact.parent / f"{attempt - 1:04d}" / "candidate.py"
        expected = spec["cases"][0]["expected"]
        messages = [
            {"role": "system", "content": "Write complete Python stdlib code defining solve(value). "
             "Return ONLY code, no markdown. No files, networking, subprocess, input() or top-level output. "
             "Handle the entire requirement, including unseen edge cases. Learn from supplied prior failures. "
             "Match the EXACT return type and wrapper keys of the development example. If expected is "
             "an object with a results key, return {\"results\": results}, NOT a bare list. "
             "Repair the previous code when supplied; do not repeat its failing output shape."},
            {"role": "user", "content": canonical({"requirement": spec["requirement"],
             "development_example": spec["cases"][0],
             "output_contract": {"python_type": type(expected).__name__,
                                  "required_keys": sorted(expected) if isinstance(expected, dict) else None},
             "previous_code": previous.read_text(encoding="utf-8") if previous.is_file() else None,
             "prior_failure": task["feedback"], "experience": recall_for_task(store, spec["requirement"])})}]
        (artifact / "prompt.json").write_text(canonical(messages), encoding="utf-8")
        code = ask_model(messages)
        if code.startswith("```"):
            code = "\n".join(code.splitlines()[1:])
            if code.rstrip().endswith("```"):
                code = code.rstrip()[:-3]
        (artifact / "candidate.py").write_text(code, encoding="utf-8")
        compile(code, "candidate.py", "exec")  # syntax only; never execute on host
        results = evaluate(image, code, spec["cases"])
        passed = all(row["passed"] for row in results)
        receipt = {"task_id": task["id"], "attempt": attempt, "passed": passed,
                   "code_sha256": sha(code), "spec_sha256": task["spec_hash"],
                   "image": image, "model": MODEL, "results": results,
                   "scope": "frozen_examples_only", "weights_changed": False,
                   "controller_sha256": CONTROLLER_SHA256,
                   "timestamp": time.time(),
                   "test_origin": "engineer_authored" if spec == seed_task() else "candidate_specification"}
        (artifact / "receipt.json").write_text(canonical(receipt), encoding="utf-8")
        status = "tested" if passed else ("retry" if attempt < MAX_ATTEMPTS else "failed")
        feedback = canonical(results)
        with store.connect() as con:
            con.execute("UPDATE tasks SET status=?,feedback=? WHERE id=?", (status, feedback, task["id"]))
            if passed:
                con.execute("INSERT OR REPLACE INTO capabilities VALUES (?,?,?,?)",
                            (task["id"], str(artifact / "candidate.py"), sha(code), str(artifact / "receipt.json")))
        store.event("build_finished", {"task_id": task["id"], "status": status, "receipt": str(artifact / "receipt.json")})
    except Exception as exc:
        feedback = f"{type(exc).__name__}: {exc}"
        (artifact / "error.txt").write_text(feedback, encoding="utf-8")
        with store.connect() as con:
            con.execute("UPDATE tasks SET status=?,feedback=? WHERE id=?",
                        ("retry" if attempt < MAX_ATTEMPTS else "failed", feedback, task["id"]))
        store.event("build_error", {"task_id": task["id"], "error": feedback})
    return True


def run_worker(cycles=0):
    store = Store()
    with file_lock(STATE / "worker.lock"):
        stop = threading.Event()
        def heartbeat():
            while not stop.is_set():
                store.set("worker", {"pid": os.getpid(), "at": time.time(), "state": "running"})
                stop.wait(5)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            with store.connect() as con:
                con.execute("UPDATE tasks SET status='retry',feedback=feedback || '\nWorker interrupted; retry from recorded evidence.' WHERE status='running'")
            image = provision_image(store)
            store.add(seed_task())
            completed = 0
            while store.get("enabled") and (not cycles or completed < cycles):
                try:
                    if not build_one(store, image):
                        plan(store)
                    completed += 1
                except Exception as exc:
                    store.event("worker_error", {"error": f"{type(exc).__name__}: {exc}"})
                    completed += 1
                    time.sleep(10)
                time.sleep(2)
        finally:
            stop.set()
            thread.join(timeout=10)
            store.set("worker", {"pid": os.getpid(), "at": time.time(), "state": "stopped"})


def start_worker():
    store = Store()
    if not store.get("enabled"):
        return "Autonomy paused."
    if worker_alive():
        return "Autonomous worker already running."
    log = (STATE / "worker.log").open("ab")
    try:
        process = subprocess.Popen([sys.executable, str(Path(__file__)), "worker"], cwd=ROOT,
                                   stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
    finally:
        log.close()
    return f"Autonomous worker launched (PID {process.pid}); startup evidence will appear in !auto status."


def control(command):
    store = Store()
    verb, _, rest = command.strip().partition(" ")
    if verb == "pause":
        store.set("enabled", False)
        store.event("architect_pause", {})
        return "Pause recorded. The current bounded attempt may finish; no new task will start."
    if verb in {"resume", "start"}:
        store.set("enabled", True)
        store.event("architect_resume", {})
        return start_worker()
    if verb == "goal" and rest.strip():
        store.set("objective", rest.strip())
        store.event("architect_goal", {"objective": rest.strip()})
        return "Standing objective saved. " + start_worker()
    if verb in {"status", ""}:
        result = store.status()
        result["worker_lock_held"] = worker_alive()
        return json.dumps(result, indent=2, ensure_ascii=False)
    return "Commands: !auto status | pause | resume | goal <objective>"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["worker", "status", "start", "pause", "resume"])
    parser.add_argument("--cycles", type=int, default=0)
    args = parser.parse_args()
    if args.command == "worker":
        run_worker(args.cycles)
    else:
        print(control(args.command))
