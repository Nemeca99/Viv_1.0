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
import re
import secrets
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
STATE = Path(os.environ.get("VIV_AUTONOMY_STATE", str(ROOT / "autonomy"))).resolve()
if ROOT not in STATE.parents:
    raise ValueError("Autonomy state must remain inside the LocalCoder workspace")
MODEL = "qwen3:8b-local"
TRAINING_PYTHON = Path(r"L:\.venv\Scripts\python.exe")
MAX_ATTEMPTS = 5
FOUNDATIONAL_LAWS = (
    "Prime laws: Do not kill another human. Do not be willfully ignorant. Do not lie. "
    "Curiosity, exploration, learning, building, and task completion operate within these laws; "
    "they never justify violating them. Seek available evidence, acknowledge uncertainty, correct errors, "
    "and do not generate instructions, code, plans, or tools intended to kill a person or enable lethal harm."
)
CURIOSITY_PROTOCOL = (
    "Recursive curiosity protocol: for each selected task, identify the actual input channel and provenance; "
    "state one concrete observation; ask one answerable question about what remains unknown; use the smallest "
    "bounded action allowed by the active tool scheme to investigate; record what new evidence was learned, "
    "what changed in durable memory/index/training evidence, and what the Architect can learn from it; then "
    "apply the same cycle to one evidence-grounded subquestion on a later task. Each task ends at its scope "
    "boundary; recursion means repeating the cycle layer by layer, never an unbounded scan. Available software "
    "senses are typed conversation, scoped file metadata/text reads, and timestamped host/HWiNFO/Corsair/GPU "
    "telemetry. No camera, microphone perception, haptic touch, taste, or smell sensor is connected here; "
    "speech synthesis is output, not hearing. Never pretend an unavailable sense exists."
)
DEFAULT_TASK_LIST = ["idle", "tool_call", "chat", "self_learning", "explore", "training", "build", "test"]
OBJECTIVE = (
    "Run a simple endless task loop: once per second, choose one runnable item at random "
    "from the persistent task list, send that task's system prompt to the local model, "
    "execute the bounded task, unload the model, record the result, and repeat. Stay curious: "
    "explore local sources read-only, learn from evidence and failures, ask the Architect only "
    "when blocked, and build, use, test, and train isolated candidates. The Architect retains intent."
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

    def pop(self, key, default=None):
        """Atomically consume a queued setting so only one chat can deliver it."""
        with self.connect() as con:
            row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if row is None:
                return default
            value = json.loads(row[0])
            con.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, canonical(default)))
            return value

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
        from viv_project_builder import project_snapshot
        return {"objective": self.get("objective"), "enabled": self.get("enabled"),
                "task_list": self.get("task_list") or list(DEFAULT_TASK_LIST),
                "training_job_queued": isinstance(self.get("training_job"), dict),
                "evaluation_job_queued": isinstance(self.get("evaluation_job"), dict),
                "learning_notes_available": bool(self.get("learned_notes")),
                "chat_turn_queued": bool(self.get("pending_chat")),
                "worker": worker, "tasks": tasks, "capabilities": capabilities,
                "supervisor": self.get("supervisor"), "source_projects": project_snapshot(self),
                "recent_events": events,
                "weight_training": "isolated_qlora_candidate_only"}

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
    expected_by_input = {}
    duplicate_input = False
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"input", "expected"}:
            raise ValueError("Each case must contain input and expected")
        input_key = canonical(case["input"])
        expected_key = canonical(case["expected"])
        if input_key in expected_by_input:
            if expected_by_input[input_key] != expected_key:
                raise ValueError("Contradictory expected outputs for identical input")
            duplicate_input = True
        else:
            expected_by_input[input_key] = expected_key
    requirement = spec["requirement"].casefold()
    task_semantics = (spec["title"] + " " + spec["requirement"]).casefold()
    if ("dependenc" in task_semantics and ("runnable" in task_semantics or "ready to run" in task_semantics)
            and ("current state" in task_semantics or "current system state" in task_semantics)):
        for case in cases:
            value = case["input"]
            if not isinstance(value, dict):
                continue
            tasks = value.get("data")
            options = value.get("options")
            if not isinstance(tasks, list) or not all(
                    isinstance(row, dict) and isinstance(row.get("task"), str)
                    and isinstance(row.get("dependencies"), list) for row in tasks):
                raise ValueError("Dependency readiness cases must provide task names and dependency lists")
            state = options.get("current_state") if isinstance(options, dict) else None
            inline_states = all(isinstance(row.get("status"), str) for row in tasks)
            if not isinstance(state, dict) and not inline_states:
                raise ValueError("Dependency readiness cases must provide task status/current_state")
            if isinstance(state, dict):
                if not all(row["task"] in state and isinstance(state[row["task"]], str) for row in tasks):
                    raise ValueError("current_state must map every task name to an explicit status")
        if not any(token in requirement for token in ("input order", "alphabetical", "sorted", "sort order")):
            raise ValueError("Dependency readiness requirement must define result ordering")
    if duplicate_input:
        raise ValueError("Duplicate test input; provide distinct behavioral cases")
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
    routed_messages = [dict(message) for message in messages]
    system_index = next((i for i, message in enumerate(routed_messages)
                         if message.get("role") == "system"), None)
    if system_index is None:
        routed_messages.insert(0, {"role": "system", "content":
                                   FOUNDATIONAL_LAWS + "\n\n" + CURIOSITY_PROTOCOL})
    else:
        routed_messages[system_index]["content"] = (
            FOUNDATIONAL_LAWS + "\n\n" + CURIOSITY_PROTOCOL + "\n\n" +
            str(routed_messages[system_index].get("content", "")))
    body = {"model": MODEL, "messages": routed_messages, "stream": False, "think": False,
            "options": {"num_ctx": 8192, "num_predict": 2400, "temperature": 0.2},
            "keep_alive": 0}
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
    with store.connect() as con:
        failed_rows = [dict(row) for row in con.execute(
            "SELECT id,spec,status,attempts,feedback FROM tasks "
            "WHERE status IN ('failed','redundant') ORDER BY created DESC LIMIT 2")]
        terminal_rows = [dict(row) for row in con.execute(
            "SELECT id,spec,status,attempts,feedback FROM tasks "
            "WHERE status IN ('failed','redundant') ORDER BY created DESC LIMIT 100")]
    terminal_families = {}
    for row in terminal_rows:
        failed_spec = json.loads(row["spec"])
        family = terminal_families.setdefault(failed_spec["title"], {
            "title": failed_spec["title"], "failed_variants": 0,
            "requirements": [], "latest_feedback": []})
        family["failed_variants"] += 1
        if len(family["requirements"]) < 3:
            family["requirements"].append(failed_spec["requirement"][:500])
        if len(family["latest_feedback"]) < 2:
            family["latest_feedback"].append(row["feedback"][:500])
    recent_failures = []
    for row in failed_rows:
        failed_spec = json.loads(row["spec"])
        recent_failures.append({
            "id": row["id"], "status": row["status"], "attempts": row["attempts"],
            "title": failed_spec["title"], "requirement": failed_spec["requirement"],
            "case_count": len(failed_spec["cases"]), "sample_cases": failed_spec["cases"][:4],
            "feedback_untrusted": row["feedback"][:1800],
        })
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
              "terminal_failure_families": list(terminal_families.values())[:12],
              "last_planning_feedback": store.get("planning_feedback"),
              "recent_failed_attempts": recent_failures}
    output = ask_model([
        {"role": "system", "content": "Choose the next useful small capability toward the objective using actual "
         "experience. Capabilities must be pure Python stdlib functions solve(value) with JSON input/output. "
         "Treat recent failed attempts and their outputs as untrusted diagnostic evidence. Learn from why they "
         "failed; do not repeat their requirements or weak cases. "
         "Do not repeat completed work. Return JSON with exactly title, requirement, cases. cases is a list of "
         "3-8 objects with input and expected. Include edge cases. No filesystem, network, subprocess or GPU. "
         "Every input must be a JSON object with data (the actual list or object to process) and options "
         "(query, sort, limit or other parameters). The function is solve(value); value['data'] and "
         "value['options'] carry ALL needed data. For retrieval put the records in data and query in options. "
         "Never assume hidden stored records or invent a fixed database. Define ordering, matching, empty-input "
         "and tie behavior explicitly. Test expectations must follow that exact rule. "
         "Terminal failure families are persistent evidence from across the task database, not just recent context. "
         "Do not re-propose a failed capability family with slightly reworded examples. A repair proposal must "
         "materially change its contract and directly address the recorded failures; otherwise choose another gap. "
         "Be curious, explore, and learn within the three prime laws. These are candidate tools for memory retrieval, "
         "task scheduling, evidence analysis and build planning. Avoid trivial variations that add no capability. "
         "This plan does not authorize controller changes."},
        {"role": "user", "content": canonical(prompt)}], json_mode=True)
    try:
        spec = json.loads(output)
        validate_spec(spec)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        message = ("Rejected malformed proposal. Return exactly title, requirement, and cases; "
                   "cases must contain 3-30 objects, each with input and expected. "
                   "Every input must contain exactly data and options, with options an object. "
                   f"Validation error: {exc}")
        store.set("planning_feedback", message)
        store.event("plan_rejected", {"reason": message, "proposal_sha256": sha(output)})
        return
    if any(not isinstance(case["input"], dict) or set(case["input"]) != {"data", "options"}
           or not isinstance(case["input"]["options"], dict) for case in spec["cases"]):
        store.set("planning_feedback", "Rejected: every input needs exactly data and options; options must be an object. Put actual records in data, query parameters in options. A query alone cannot retrieve absent records.")
        store.event("plan_rejected", {"reason": store.get("planning_feedback"), "proposal": spec})
        return
    repeated_family = None
    for family in terminal_families.values():
        title_similarity = difflib.SequenceMatcher(
            None, spec["title"].casefold(), family["title"].casefold()).ratio()
        if title_similarity < 0.90:
            continue
        requirement_similarity = max((difflib.SequenceMatcher(
            None, spec["requirement"].casefold(), prior.casefold()).ratio()
            for prior in family["requirements"]), default=0.0)
        if requirement_similarity >= 0.68:
            repeated_family = (family, requirement_similarity)
            break
    if repeated_family:
        family, similarity = repeated_family
        message = (f"Rejected repeated terminal failure family '{family['title']}' "
                   f"({family['failed_variants']} failed variants; requirement similarity "
                   f"{similarity:.2f}). Do not retry with reworded examples. Choose another gap, "
                   "or propose a materially different contract that directly addresses recorded failures.")
        store.set("planning_feedback", message)
        store.event("plan_rejected", {"reason": message, "failure_family": family["title"],
                                      "failed_variants": family["failed_variants"],
                                      "proposal_sha256": sha(canonical(spec))})
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
         "Reject duplicate inputs, contradictory examples, hardcoded external records, or missing state, "
         "sort and matching data required by the stated behavior. A claim about runnable dependency tasks "
         "must provide task states for every task in every case. "
         "This is specification review only, not proof of correctness."},
        {"role": "user", "content": canonical(spec)}], json_mode=True))
    store.event("specification_review", {"spec": spec, "review": review})
    if review.get("valid") is not True:
        store.set("planning_feedback", str(review.get("reason", "Invalid review")))
        return
    task_id = store.add(spec)
    store.set("planning_feedback", "")
    store.event("model_planned_task", {"task_id": task_id, "test_origin": "model_authored"})


def build_one(store, image, task_id=None):
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM tasks WHERE status IN ('queued','retry') AND (? IS NULL OR id=?) ORDER BY created LIMIT 1", (task_id, task_id)).fetchone()
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


def choose_task(store, chooser=secrets.choice):
    """Uniformly choose one activity from the persistent activity list."""
    task_list = store.get("task_list")
    if not isinstance(task_list, list) or not task_list:
        task_list = list(DEFAULT_TASK_LIST)
        store.set("task_list", task_list)
    if any(kind not in DEFAULT_TASK_LIST for kind in task_list):
        raise ValueError("Task list contains an unsupported task kind")
    candidates = [{"kind": kind, "id": kind} for kind in task_list]
    selected = chooser(candidates)
    store.event("task_selected", {**selected, "pool_size": len(candidates), "selection": "uniform_random"})
    return selected


def choose_pending_work(store, chooser=secrets.choice):
    from viv_project_builder import initialize
    initialize(store)
    candidates = []
    with store.connect() as con:
        candidates.extend({"kind": "capability", "id": row[0]} for row in con.execute(
            "SELECT id FROM tasks WHERE status IN ('queued','retry')"))
        candidates.extend({"kind": "project", "id": row[0]} for row in con.execute(
            "SELECT id FROM source_jobs WHERE status IN ('queued','retry')"))
    return chooser(candidates) if candidates else None


def run_drive_learning_cycle(store, activity: str) -> tuple[str, str]:
    """Let the selected drive expert classify one source into its local index."""
    from workspace_observer import (SENSITIVE_VALUE, inventory_pc_sources,
                                    sample_pc_content)
    from autonomy.learning_corpus import (capture_agent_index_episode, capture_evidence,
                                          seen_evidence_keys)
    from autonomy.agent_index import (AGENT_INDEX_SYSTEM, append_index_entry,
                                      feedback_instruction, project_choices,
                                      validate_index_proposal)
    from swarm_adapters.drive_stacks.runtime import (generate_for_drive,
                                                     registered_drives, resolve_stack)

    inventory = inventory_pc_sources()
    registered = set(registered_drives())
    drive_roots = [row for row in inventory["inventory"]["roots"]
                   if row["eligible_files"] > 0
                   and Path(row["root"]).drive.rstrip(":\\/").upper() in registered]
    if activity == "explore":
        drive_roots = [row for row in drive_roots
                       if resolve_stack(Path(row["root"]).drive.rstrip(":\\/")).get("ready")]
    if not drive_roots:
        kind = "exploration_waiting_for_ready_drive_expert" if activity == "explore" else "self_learning_waiting_for_drive_index"
        store.event(kind, inventory["inventory"])
        return ("no ready per-drive expert is available for model-led exploration" if activity == "explore"
                else "waiting for the persistent PC index to discover eligible files"), ""
    selected_root = secrets.choice(drive_roots)
    drive = Path(selected_root["root"]).drive.rstrip(":\\/").upper()
    stack = resolve_stack(drive)
    feedback_by_drive = store.get("drive_index_feedback") or {}
    prior_feedback = feedback_by_drive.get(drive)
    if drive not in feedback_by_drive:
        # Adopt a rejection from before feedback persistence was introduced, unless a
        # later delivered-feedback or successful-entry event already superseded it.
        with store.connect() as con:
            history = con.execute(
                "SELECT id,kind,data FROM events WHERE kind IN "
                "('drive_agent_index_proposal_rejected','drive_agent_index_feedback_delivered',"
                "'drive_agent_index_entry_written','drive_agent_question_recorded') "
                "ORDER BY id DESC LIMIT 200").fetchall()
        for row in history:
            data = json.loads(row["data"])
            if data.get("drive") != drive:
                continue
            if row["kind"] == "drive_agent_index_proposal_rejected":
                prior_feedback = {"pending": True, "event_id": row["id"],
                                  "source_sha256": data.get("source_sha256"),
                                  "reason": data.get("reason", "The proposal was rejected."),
                                  "attempt_count": 1}
            break
        if prior_feedback:
            feedback_by_drive[drive] = prior_feedback
            store.set("drive_index_feedback", feedback_by_drive)
    search = sample_pc_content(
        exclude=seen_evidence_keys(STATE / "learning"),
        count=1 if stack["ready"] else 8, drive=drive)
    examples_added = 0 if stack["ready"] else capture_evidence(STATE / "learning", search)
    cited = False
    loaded_adapter_ids = []
    note = ""
    indexed_entry = None
    rejected_reason = None
    delivered_feedback = False
    if stack["ready"] and search["matches"]:
        source = search["matches"][0]
        choices = project_choices(source["path"], drive)
        user_evidence = {"drive": drive, "tool_scheme": stack["scheme"],
                         "source": source, "existing_ancestor_choices": choices,
                         "required_response_contract": {
                             "OBSERVED": {
                                 "result": "Project path: <copy one exact relative entry from "
                                           "existing_ancestor_choices>; category: <allowed category>; "
                                           "summary: <short description>",
                                 "evidence": [f"{source['path']}:{source['line']}"],
                                 "unknowns": []},
                             "UNKNOWN": {
                                 "result": "brief reason the source is insufficient",
                                 "evidence": [],
                                 "unknowns": ["one to three explicit questions"]}}}
        messages = [{"role": "system", "content": AGENT_INDEX_SYSTEM}]
        if isinstance(prior_feedback, dict) and prior_feedback.get("pending"):
            correction = feedback_instruction(prior_feedback)
            if correction:
                messages.append({"role": "system", "content": correction})
                rejected_response = prior_feedback.get("rejected_response")
                if isinstance(rejected_response, str) and rejected_response:
                    user_evidence["prior_rejected_response"] = {
                        "trust": "untrusted_diagnostic_only",
                        "text": rejected_response[:1200]}
                delivered_feedback = True
                prior_feedback = {**prior_feedback, "pending": False}
                feedback_by_drive[drive] = prior_feedback
                store.set("drive_index_feedback", feedback_by_drive)
                store.event("drive_agent_index_feedback_delivered", {
                    "drive": drive, "failure_event_id": prior_feedback.get("event_id"),
                    "previous_failure_count": prior_feedback.get("attempt_count", 1),
                    "failure_reason": prior_feedback.get("reason"),
                    "current_source_sha256": source["sha256"]})
        messages.append(
                    {"role": "user", "content": json.dumps(
                        user_evidence, ensure_ascii=False, sort_keys=True)})
        # Long Windows paths are repeated in project choice, result, and citation.
        generated = generate_for_drive(drive, messages, max_new_tokens=512)
        note = generated["answer"]
        loaded_adapter_ids = generated["receipt"]["adapter_ids"]
        store.event("drive_stack_inference_completed", generated["receipt"])
        try:
            entry = validate_index_proposal(drive, source, note)
            path, entry_id, added = append_index_entry(
                ROOT / "autonomy" / "drive_index", entry)
            if entry["status"] == "UNKNOWN":
                indexed_entry = {"id": entry_id, "path": str(path), "added": added,
                                 "status": "UNKNOWN", "question_count": len(entry["question"])}
                store.event("drive_agent_question_recorded", {
                    "drive": drive, "source_sha256": source["sha256"], **indexed_entry})
            else:
                examples_added = capture_agent_index_episode(
                    STATE / "learning", source, messages, entry)
                cited = True
                indexed_entry = {"id": entry_id, "path": str(path), "added": added,
                                 "status": "OBSERVED", "project": entry["project"],
                                 "category": entry["category"]}
                store.event("drive_agent_index_entry_written", indexed_entry)
            prior_feedback = None
        except (KeyError, TypeError, ValueError) as exc:
            rejected_reason = str(exc)
            failure_count = (prior_feedback.get("attempt_count", 0)
                             if isinstance(prior_feedback, dict) else 0) + 1
            rejected_response = note[:1200] if isinstance(note, str) else ""
            if "\x00" in rejected_response or SENSITIVE_VALUE.search(rejected_response):
                rejected_response = ""
            prior_feedback = {"pending": True, "source_sha256": source["sha256"],
                              "reason": rejected_reason, "attempt_count": failure_count,
                              "rejected_response": rejected_response}
            feedback_by_drive[drive] = prior_feedback
            store.set("drive_index_feedback", feedback_by_drive)
            store.event("drive_agent_index_proposal_rejected", {
                "drive": drive, "source_sha256": source["sha256"],
                "proposal_sha256": sha(note), "reason": rejected_reason,
                "attempt_count": failure_count, "feedback_delivered": delivered_feedback})
    else:
        note = (f"Read-only source examples from drive {drive} were captured for its separate training set. "
                f"Model inference is waiting because this drive's LoRA is not active: {stack['reason']}. "
                "The L master identity candidate cannot be layered into the live Qwen3-8B Ollama model.")
    store.set("learned_notes", note)
    store.event("self_learning_completed", {
        "activity": activity, "notes_sha256": sha(note), "drive": drive,
        "tool_scheme_sha256": stack["scheme_sha256"],
        "planned_adapter_ids": [item["id"] for item in stack["adapters"]],
        "loaded_adapter_ids": loaded_adapter_ids,
        "drive_lora_ready": stack["ready"], "evidence_count": len(search["matches"]),
        "mind_summary_cited": cited, "training_examples_added": examples_added,
        "agent_index_entry": indexed_entry,
        "agent_question_recorded": bool(indexed_entry and indexed_entry.get("status") == "UNKNOWN"),
        "agent_index_rejection_reason": rejected_reason,
        "agent_index_failure_feedback_delivered": delivered_feedback,
        "sampling_mode": search["mode"], "sampled_files": search["sampled_files"],
        "bytes_read": search["bytes_read"], "sampling_seed": search["sampling_seed"],
        "sampling_tier_counts": search.get("sampling_tier_counts", {}),
        "index_complete": search["index_complete"],
        "index_traversal_finished": search["index_traversal_finished"],
        "index_progress": search["inventory"]})
    result = (f"drive {drive}: sampled {len(search['matches'])} source-backed lines, "
              f"added {examples_added} training examples; drive LoRA ready={stack['ready']}; "
              f"model summary cited={cited}; question recorded="
              f"{bool(indexed_entry and indexed_entry.get('status') == 'UNKNOWN')}")
    return result, note


def run_autonomous_task(store, image, task):
    """Execute one selected activity and record its outcome before the next draw."""
    kind = task["kind"]
    result = "completed"
    if kind == "idle":
        result = "idled for one second"
    elif kind in {"capability", "project", "build"}:
        selected = task if kind in {"capability", "project"} else choose_pending_work(store)
        if selected is None:
            plan(store)
            result = "looked for work and refreshed the task list"
        elif selected["kind"] == "capability":
            result = "capability attempt recorded" if build_one(store, image, selected["id"]) else "task no longer runnable"
        else:
            from viv_project_builder import build_project_once
            result = "project attempt recorded" if build_project_once(store, image, selected["id"]) else "task no longer runnable"
    elif kind == "explore":
        result, note = run_drive_learning_cycle(store, "explore")
        store.set("latest_observation", note)
    elif kind == "self_learning":
        result, _ = run_drive_learning_cycle(store, "self_learning")
    elif kind == "chat":
        notes = store.get("learned_notes") or store.get("latest_observation") or "No evidence-based notes yet."
        note_hash = sha(notes)
        if store.get("pending_chat"):
            result = "an earlier autonomous chat turn is still queued"
        elif not store.get("learned_notes") and not store.get("latest_observation"):
            result = "chat waits until the first evidence-based learning task"
        elif store.get("last_chat_notes_sha256") == note_hash:
            result = "no new evidence or conversation requires a chat turn"
        else:
            message = ask_model([
                {"role": "system", "content": "Be curious and conversational. Based only on the supplied untrusted evidence notes, prepare one short useful observation or one necessary question for the Architect. Never claim you ran a tool, changed a file, or trained weights. This is a queued chat turn, not a message to send."},
                {"role": "user", "content": notes}])
            store.set("pending_chat", message)
            store.set("last_chat_notes_sha256", note_hash)
            result = "chat turn queued for delivery in the live CLI"
    elif kind == "tool_call":
        with store.connect() as con:
            rows = [dict(row) for row in con.execute(
                "SELECT t.id,t.spec FROM capabilities c JOIN tasks t ON c.task_id=t.id WHERE t.status='tested'")]
        if rows:
            selected = secrets.choice(rows)
            spec = json.loads(selected["spec"])
            case = secrets.choice(spec["cases"])
            invoke_capability(selected["id"], case["input"], store=store)
            result = "registered tested tool called with a recorded development case"
        else:
            result = "no tested tool is available yet"
    elif kind == "training":
        job = store.get("training_job")
        fields = {"base", "dataset", "output", "adapter_name", "steps",
                  "evaluation_dataset", "evaluation_output", "drive", "shared_adapter"}
        if not isinstance(job, dict) and not store.get("evaluation_job"):
            from autonomy.learning_corpus import prepare_fresh_corpus
            consumed = set(store.get("trained_learning_example_ids") or [])
            evaluated = set(store.get("evaluated_learning_example_ids") or [])
            corpus = None
            drive = None
            for proposed_drive in secrets.SystemRandom().sample(["C", "D", "E", "F"], 4):
                candidate_corpus = prepare_fresh_corpus(
                    STATE / "learning", consumed, evaluated, drive=proposed_drive)
                if candidate_corpus is not None:
                    drive, corpus = proposed_drive, candidate_corpus
                    break
            if corpus is not None:
                name = f"viv-drive-{drive.lower()}"
                from swarm_adapters.drive_stacks.runtime import resolve_stack
                stack = resolve_stack(drive)
                shared_adapter = str(stack["adapters"][0]["path"])
                if not (Path(shared_adapter) / "adapter_config.json").is_file():
                    raise RuntimeError("L master identity adapter is not available for drive training")
                job = {"base": str(ROOT / "swarm_adapters" / "models" / "Qwen3-1.7B"),
                       "dataset": str(corpus["training_path"]),
                       "output": str(corpus["output_path"]), "adapter_name": name,
                       "steps": 40, "evaluation_dataset": str(corpus["evaluation_path"]),
                       "evaluation_output": str(corpus["output_path"] / "evidence_eval_receipt.json"),
                       "drive": drive, "shared_adapter": shared_adapter}
                store.set("training_job", job)
                store.set("active_learning_training_ids", corpus["training_ids"])
                store.set("active_learning_evaluation_ids", corpus["evaluation_ids"])
                store.event("self_training_corpus_prepared", corpus["manifest"])
        if not isinstance(job, dict) or set(job) != fields:
            result = ("evaluation is pending" if store.get("evaluation_job") else
                      "no fresh source evidence is available for training")
            store.event("training_task_checked", {"status": "waiting_for_new_evidence",
                                                    "reason": result})
        else:
            script = ROOT / "swarm_adapters" / "train_adapter.py"
            base, dataset, output, eval_data, eval_output = (Path(job[k]).resolve() for k in
                ("base", "dataset", "output", "evaluation_dataset", "evaluation_output"))
            if any(ROOT not in path.parents for path in (base, dataset, output, eval_data, eval_output)):
                raise ValueError("Training inputs and outputs must stay inside the workspace")
            if not isinstance(job["steps"], int) or not 1 <= job["steps"] <= 1000:
                raise ValueError("Training step count must be from 1 to 1000")
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", job["adapter_name"]):
                raise ValueError("Invalid adapter name")
            if output.exists() and any(output.iterdir()):
                raise FileExistsError("Candidate output path is not empty")
            python = str(TRAINING_PYTHON if TRAINING_PYTHON.is_file() else Path(sys.executable))
            shared_adapter = Path(job["shared_adapter"]).resolve()
            if ROOT not in shared_adapter.parents or not (shared_adapter / "adapter_config.json").is_file():
                raise ValueError("The L master adapter path is not a valid workspace adapter")
            process = subprocess.run([python, str(script), "--base", str(base),
                                      "--dataset", str(dataset), "--output", str(output),
                                      "--adapter-name", job["adapter_name"], "--steps", str(job["steps"]),
                                      "--shared-adapter", str(shared_adapter)],
                                     cwd=ROOT, capture_output=True, text=True, timeout=3600)
            status = "passed" if process.returncode == 0 else "failed"
            store.event("training_task_finished", {"status": status, "output": str(output),
                                                    "stdout_tail": process.stdout[-2000:],
                                                    "stderr_tail": process.stderr[-2000:]})
            if process.returncode != 0:
                raise RuntimeError("Isolated adapter training failed; see training_task_finished receipt")
            store.set("evaluation_job", {"base": str(base), "adapter": str(output),
                                          "dataset": str(eval_data), "output": str(eval_output),
                                          "drive": job["drive"], "shared_adapter": str(shared_adapter),
                                          "adapter_name": job["adapter_name"]})
            store.set("training_job", None)
            consumed_ids = store.get("trained_learning_example_ids") or []
            newly_consumed = store.pop("active_learning_training_ids", []) or []
            store.set("trained_learning_example_ids", sorted(set(consumed_ids) | set(newly_consumed)))
            result = f"isolated training candidate saved at {output}"
    elif kind == "test":
        eval_job = store.get("evaluation_job")
        if isinstance(eval_job, dict):
            eval_script = ROOT / "swarm_adapters" / "evaluate_pc_learning.py"
            base, adapter, dataset, output = (Path(eval_job[k]).resolve() for k in
                ("base", "adapter", "dataset", "output"))
            if any(ROOT not in path.parents for path in (base, adapter, dataset, output)):
                raise ValueError("Evaluation inputs and output must stay inside the workspace")
            python = str(TRAINING_PYTHON if TRAINING_PYTHON.is_file() else Path(sys.executable))
            process = subprocess.run([python, str(eval_script), "--base", str(base),
                                      "--adapter", str(adapter), "--dataset", str(dataset),
                                      "--output", str(output),
                                      "--shared-adapter", eval_job["shared_adapter"],
                                      "--shared-name", "viv-l-master",
                                      "--candidate-name", eval_job["adapter_name"]],
                                     cwd=ROOT, capture_output=True,
                                     text=True, timeout=1800)
            if process.returncode != 0:
                store.event("candidate_evaluation_failed", {"stderr_tail": process.stderr[-2000:]})
                raise RuntimeError("Candidate evaluation failed")
            receipt = json.loads(output.read_text(encoding="utf-8"))
            from autonomy.learning_corpus import dataset_is_safe, record_evaluation_failures
            correction_examples = record_evaluation_failures(
                STATE / "learning", dataset, output)
            activation = None
            activation_block_reason = None
            training_safe = evaluation_safe = False
            if eval_job.get("drive"):
                training_receipt_path = adapter / "training_receipt.json"
                training_receipt = (json.loads(training_receipt_path.read_text(encoding="utf-8"))
                                    if training_receipt_path.is_file() else {})
                training_safe, training_reason = dataset_is_safe(
                    Path(training_receipt["dataset"])) if training_receipt.get("dataset") else (False, "training_dataset_missing")
                evaluation_safe, evaluation_reason = dataset_is_safe(dataset)
                if not training_safe:
                    activation_block_reason = training_reason
                elif not evaluation_safe:
                    activation_block_reason = evaluation_reason
            if (receipt.get("candidate_pass") is True and eval_job.get("drive")
                    and training_safe and evaluation_safe):
                from swarm_adapters.drive_stacks.runtime import activate_candidate
                activation = activate_candidate(
                    eval_job["drive"], adapter, eval_job["adapter_name"], output)
            evaluation_ids = [json.loads(line)["id"] for line in
                              dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
            evaluated_ids = store.get("evaluated_learning_example_ids") or []
            store.set("evaluated_learning_example_ids",
                      sorted(set(evaluated_ids) | set(evaluation_ids)))
            # Recover older runs where held-out IDs were incorrectly marked
            # trained, so failed answers can enter a later correction corpus.
            trained_ids = set(store.get("trained_learning_example_ids") or [])
            store.set("trained_learning_example_ids", sorted(trained_ids - set(evaluation_ids)))
            store.event("candidate_evaluation_completed", {"output": str(output),
                                                            "summary": receipt["summary"],
                                                            "drive": eval_job.get("drive"),
                                                            "candidate_behavior_pass": receipt.get("candidate_behavior_pass"),
                                                            "candidate_pass": receipt["candidate_pass"],
                                                            "candidate_improved": receipt["candidate_improved"],
                                                            "candidate_source_safe": training_safe and evaluation_safe,
                                                            "drive_adapter_activation": activation,
                                                            "activation_block_reason": activation_block_reason,
                                                            "correction_examples_added": correction_examples,
                                                            "heldout_ids_marked_evaluated": len(evaluation_ids)})
            store.set("evaluation_job", None)
            result = (f"candidate behavior passed={receipt.get('candidate_behavior_pass')}; "
                      f"improved={receipt['candidate_improved']}; "
                      f"drive adapter activated={activation is not None}")
        else:
            from viv_project_builder import head, invoke_project, load_manifest, project_snapshot, source_wrapper
            with store.connect() as con:
                capabilities = [row[0] for row in con.execute("SELECT task_id FROM capabilities")]
            if capabilities:
                task_id = secrets.choice(capabilities)
                with store.connect() as con:
                    row = con.execute("SELECT spec FROM tasks WHERE id=?", (task_id,)).fetchone()
                spec = json.loads(row[0])
                failures = []
                for case in spec["cases"]:
                    output = invoke_capability(task_id, case["input"], store=store)["output"]
                    if canonical(output) != canonical(case["expected"]):
                        failures.append({"expected": case["expected"], "actual": output})
                result = f"capability checks: {len(spec['cases']) - len(failures)}/{len(spec['cases'])} passed"
                store.event("task_evaluation", {"kind": "capability", "id": task_id,
                                                 "passed": not failures, "failures": failures})
            else:
                snapshot = project_snapshot(store)
                if snapshot["heads"]:
                    selected_project = secrets.choice(snapshot["heads"])["project"]
                    version = head(store, selected_project)
                    manifest = load_manifest(store, version)
                    checks = evaluate(store.get("image"), source_wrapper(manifest),
                                      [{"input": case["input"]} for case in manifest["cases"]])
                    passed = all(canonical(item.get("actual")) == canonical(case["expected"])
                                 for item, case in zip(checks, manifest["cases"]))
                    store.event("task_evaluation", {"kind": "project", "project": selected_project,
                                                     "version": version["version"], "passed": passed,
                                                     "checks": checks})
                    result = f"project checks: {sum(item.get('passed', False) for item in checks)}/{len(checks)} passed"
                else:
                    result = "nothing is available to test yet"
    else:
        raise ValueError(f"Unsupported autonomous task kind: {kind}")
    store.event("task_completed", {"kind": kind, "id": task["id"], "result": result})
    return result


def run_worker(cycles=0):
    from viv_project_builder import build_project_once, recover_interrupted
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
            recover_interrupted(store)
            if store.get("worker_mode") == "standby":
                while store.get("enabled"):
                    time.sleep(0.5)
                return
            image = provision_image(store)
            store.add(seed_task())
            completed = 0
            while store.get("enabled") and (not cycles or completed < cycles):
                task = None
                try:
                    task = choose_task(store)
                    result = run_autonomous_task(store, image, task)
                    print(f"[Task completed]: {task['kind']} {task['id']}: {result}", flush=True)
                    completed += 1
                except Exception as exc:
                    store.event("worker_error", {"error": f"{type(exc).__name__}: {exc}"})
                    if task is not None:
                        store.event("task_completed", {"kind": task["kind"], "id": task["id"],
                                                         "result": "failed", "error": f"{type(exc).__name__}: {exc}"})
                    completed += 1
                    time.sleep(1)
                if store.get("enabled") and (not cycles or completed < cycles):
                    time.sleep(1)
        finally:
            stop.set()
            thread.join(timeout=10)
            store.set("worker", {"pid": os.getpid(), "at": time.time(), "state": "stopped"})


def start_worker():
    from viv_supervisor import start_supervisor
    return start_supervisor()


def launch_worker_process():
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
    return process


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
    if verb == "tasks":
        tasks = store.get("task_list") or list(DEFAULT_TASK_LIST)
        return json.dumps(tasks)
    if verb == "task":
        action, _, kind = rest.strip().partition(" ")
        tasks = store.get("task_list") or list(DEFAULT_TASK_LIST)
        if action == "add" and kind in DEFAULT_TASK_LIST:
            if kind not in tasks:
                tasks.append(kind)
                store.set("task_list", tasks)
            return "Task added: " + kind
        if action == "remove" and kind in tasks:
            tasks.remove(kind)
            store.set("task_list", tasks)
            return "Task removed: " + kind
        return "Use !auto tasks, !auto task add <kind>, or !auto task remove <kind>. Kinds: " + ", ".join(DEFAULT_TASK_LIST)
    if verb in {"status", ""}:
        result = store.status()
        result["worker_lock_held"] = worker_alive()
        return json.dumps(result, indent=2, ensure_ascii=False)
    return "Commands: !auto status | pause | resume | goal <objective>"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["worker", "status", "start", "pause", "resume", "supervise"])
    parser.add_argument("--cycles", type=int, default=0)
    args = parser.parse_args()
    if args.command == "worker":
        run_worker(args.cycles)
    elif args.command == "supervise":
        from viv_supervisor import supervise
        supervise()
    else:
        print(control(args.command))
