"""Versioned multi-file projects built locally and executed inside the sandbox.

The registry changes only after external input/output checks pass. Candidate
source stays in immutable attempt directories; revisions inherit the current
head's regression cases, and rollback changes one SQLite head pointer.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import time


def concise_feedback(text):
    try:
        rows = json.loads(text)
    except (ValueError, TypeError):
        return text
    if not isinstance(rows, list):
        return text
    failures = []
    signatures = set()
    for row in rows:
        if row.get("passed"):
            continue
        row = dict(row)
        if "error" in row:
            row["error"] = "\n".join(line for line in row["error"].splitlines() if "Failed to translate" not in line)[-1800:]
        signature = row.get("error") or json.dumps({"actual": row.get("actual"), "expected": row.get("expected")}, sort_keys=True)
        if signature not in signatures:
            failures.append(row)
            signatures.add(signature)
        if len(failures) >= 3:
            break
    return failures


def initialize(store):
    with store.connect() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS source_jobs(
                id TEXT PRIMARY KEY,spec TEXT NOT NULL,parent TEXT,
                status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,
                feedback TEXT NOT NULL DEFAULT '',created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS project_versions(
                project TEXT NOT NULL,version TEXT NOT NULL,parent TEXT,
                manifest TEXT NOT NULL,receipt TEXT NOT NULL,entrypoint TEXT NOT NULL,
                PRIMARY KEY(project,version));
            CREATE TABLE IF NOT EXISTS project_heads(project TEXT PRIMARY KEY,version TEXT NOT NULL);
        """)


def validate_request(spec):
    from viv_autonomy import validate_spec
    if not isinstance(spec, dict) or set(spec) != {"project", "title", "requirement", "entrypoint", "cases"}:
        raise ValueError("Project request needs project, title, requirement, entrypoint and cases")
    if not isinstance(spec["project"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", spec["project"]):
        raise ValueError("Project name must be a lowercase identifier")
    if not isinstance(spec["entrypoint"], str) or not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*:[a-zA-Z_]\w*", spec["entrypoint"]):
        raise ValueError("Entrypoint must be module:function")
    validate_spec({key: spec[key] for key in ("title", "requirement", "cases")})


def validate_files(files):
    if not isinstance(files, dict) or not 1 <= len(files) <= 16:
        raise ValueError("Project needs 1 to 16 Python source files")
    if sum(len(text) for text in files.values() if isinstance(text, str)) > 100000:
        raise ValueError("Project exceeds 100000 source characters")
    for name, source in files.items():
        if not isinstance(name, str) or not isinstance(source, str):
            raise ValueError("Source file names and contents must be strings")
        path = PurePosixPath(name)
        if path.is_absolute() or str(path) != name or not re.fullmatch(r"(?:[A-Za-z_]\w*/)*[A-Za-z_]\w*\.py", name):
            raise ValueError("Source path must be a relative Python module path")
        compile(source, name, "exec")


def extract_files(answer):
    """Normalize the model's two observed names for its module map."""
    if not isinstance(answer, dict) or set(answer) - {"files", "modules"}:
        raise ValueError("Expected a project files mapping")
    files = {}
    for key in ("files", "modules"):
        mapping = answer.get(key, {})
        if not isinstance(mapping, dict):
            raise ValueError(f"Project {key} must be a file-to-source object")
        for name, source in mapping.items():
            if name in files and files[name] != source:
                raise ValueError(f"Conflicting source for {name}")
            files[name] = source
    validate_files(files)
    return files


def head(store, project):
    initialize(store)
    with store.connect() as con:
        row = con.execute("SELECT v.* FROM project_heads h JOIN project_versions v "
                          "ON h.project=v.project AND h.version=v.version WHERE h.project=?", (project,)).fetchone()
        return dict(row) if row else None


def load_manifest(store, version):
    from viv_autonomy import canonical, sha
    path = Path(version["manifest"]).resolve(strict=True)
    if (store.root / "project_attempts").resolve() not in path.parents:
        raise ValueError("Manifest outside project attempt store")
    content = path.read_text(encoding="utf-8")
    manifest = json.loads(content)
    if sha(canonical(manifest)) != version["version"]:
        raise ValueError("Project source differs from registered version")
    validate_files(manifest["files"])
    return manifest


def queue_project(store, spec):
    from viv_autonomy import canonical, sha
    validate_request(spec)
    initialize(store)
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT version FROM project_heads WHERE project=?", (spec["project"],)).fetchone()
        parent = existing[0] if existing else None
        job_id = sha(canonical({"spec": spec, "parent": parent}))[:20]
        con.execute("INSERT OR IGNORE INTO source_jobs(id,spec,parent,status,created) VALUES (?,?,?,?,?)",
                    (job_id, canonical(spec), parent, "queued", time.time()))
    store.event("source_job_queued", {"id": job_id, "project": spec["project"], "parent": parent})
    return job_id


def project_snapshot(store):
    initialize(store)
    with store.connect() as con:
        return {"heads": [dict(r) for r in con.execute("SELECT * FROM project_heads")],
                "jobs": [dict(r) for r in con.execute("SELECT id,status,attempts,parent FROM source_jobs ORDER BY created DESC LIMIT 8")]}


def source_wrapper(manifest):
    """The returned code is passed to Docker, never executed by the host."""
    validate_files(manifest["files"])
    return '''import importlib,json,pathlib,sys,tempfile
_manifest=json.loads(%r)
def solve(value):
    with tempfile.TemporaryDirectory() as directory:
        root=pathlib.Path(directory)
        for name,source in _manifest["files"].items():
            target=root / name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(source,encoding="utf-8")
        sys.path.insert(0,directory)
        module,function=_manifest["entrypoint"].split(":")
        return getattr(importlib.import_module(module),function)(value)
''' % json.dumps(manifest, ensure_ascii=False)


def invoke_project(store, project, value):
    from viv_autonomy import evaluate
    version = head(store, project)
    if not version:
        raise ValueError("Project has no tested active version")
    manifest = load_manifest(store, version)
    result = evaluate(store.get("image"), source_wrapper(manifest), [{"input": value}])[0]
    if "error" in result:
        store.event("source_project_runtime_failure", {"project": project, "version": version["version"], "error": result["error"]})
        raise RuntimeError(result["error"])
    receipt = {"project": project, "version": version["version"], "output": result["actual"],
               "input": value, "scope": "sandbox_execution_observation"}
    store.event("source_project_used", receipt)
    return receipt


def rollback(store, project, expected=None):
    current = head(store, project)
    if not current or not current["parent"]:
        raise ValueError("No previous project version")
    if expected is not None and current["version"] != expected:
        raise ValueError("Project head changed before rollback")
    with store.connect() as con:
        parent = con.execute("SELECT * FROM project_versions WHERE project=? AND version=?",
                             (project, current["parent"])).fetchone()
    if not parent:
        raise ValueError("Previous version missing")
    load_manifest(store, parent)
    with store.connect() as con:
        changed = con.execute("UPDATE project_heads SET version=? WHERE project=? AND version=?",
                              (current["parent"], project, current["version"])).rowcount
        if changed != 1:
            raise ValueError("Concurrent project head change")
    store.event("source_project_rollback", {"project": project, "from": current["version"], "to": current["parent"]})
    return current["parent"]


def recover_interrupted(store):
    initialize(store)
    with store.connect() as con:
        count = con.execute("UPDATE source_jobs SET status='retry',feedback=feedback || '\nInterrupted worker; resume from saved evidence.' WHERE status='running'").rowcount
    if count:
        store.event("source_jobs_recovered", {"count": count})


def build_project_once(store, image, job_id=None):
    from viv_autonomy import ask_model, canonical, sha, evaluate, MODEL, MAX_ATTEMPTS, CONTROLLER_SHA256
    initialize(store)
    with store.connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM source_jobs WHERE status IN ('queued','retry') "
                          "AND (? IS NULL OR id=?) ORDER BY created LIMIT 1", (job_id, job_id)).fetchone()
        if row is None:
            return False
        job = dict(row)
        attempt = job["attempts"] + 1
        con.execute("UPDATE source_jobs SET status='running',attempts=? WHERE id=?", (attempt, job["id"]))
    spec = json.loads(job["spec"])
    artifact = store.root / "project_attempts" / job["id"] / f"{attempt:04d}"
    artifact.mkdir(parents=True, exist_ok=False)
    (artifact / "request.json").write_text(job["spec"], encoding="utf-8")
    store.event("source_build_started", {"job": job["id"], "attempt": attempt, "parent": job["parent"]})
    try:
        parent = head(store, spec["project"])
        if (parent["version"] if parent else None) != job["parent"]:
            with store.connect() as con:
                con.execute("UPDATE source_jobs SET status='stale_parent',feedback=? WHERE id=?",
                            ("Head changed; explicit replan required", job["id"]))
            return True
        inherited = load_manifest(store, parent) if parent else {"files": {}, "cases": []}
        previous = artifact.parent / f"{attempt - 1:04d}" / "manifest.json"
        previous_response = artifact.parent / f"{attempt - 1:04d}" / "response.json"
        prior = json.loads(previous.read_text(encoding="utf-8")) if previous.is_file() else inherited
        if not previous.is_file() and previous_response.is_file():
            try:
                prior = {"files": extract_files(json.loads(previous_response.read_text(encoding="utf-8")))}
            except (ValueError, json.JSONDecodeError):
                pass
        messages = [
            {"role": "system", "content": "Build or revise a real Python project. Return JSON {\"files\": {\"module.py\": \"complete source\", ...}}. "
             "Use Python stdlib. For a helper module use the same response shape: every module belongs inside the files object as a filename and full source string. "
             "Write complete replacements for changed files; unchanged parent files are preserved automatically. "
             "The entrypoint receives the input value itself, never the test-case wrapper. Preserve existing behavior "
             "while adding the requirement. Match the exact expected output type and keys. Do not hardcode example data. "
             "All execution and file writes happen in an isolated temporary project inside Docker. No network or subprocess."},
            {"role": "user", "content": canonical({"requirement": spec["requirement"], "entrypoint": spec["entrypoint"],
             "development_example": spec["cases"][0], "parent_files": prior["files"], "failure_feedback": concise_feedback(job["feedback"])})}]
        (artifact / "prompt.json").write_text(canonical(messages), encoding="utf-8")
        raw = ask_model(messages, json_mode={"type": "object", "properties": {
            "files": {"type": "object", "additionalProperties": {"type": "string"}}},
            "required": ["files"], "additionalProperties": False})
        (artifact / "response.json").write_text(raw, encoding="utf-8")
        answer = json.loads(raw)
        generated_files = extract_files(answer)
        files = {**inherited["files"], **generated_files}
        validate_files(files)
        module = spec["entrypoint"].split(":")[0].replace(".", "/")
        if module + ".py" not in files and module + "/__init__.py" not in files:
            raise ValueError("Entrypoint source absent")
        cases = list(inherited["cases"])
        for case in spec["cases"]:
            if case not in cases:
                cases.append(case)
        if len(cases) > 100:
            raise ValueError("Regression suite exceeds current 100-case runtime budget")
        manifest = {"files": files, "entrypoint": spec["entrypoint"], "cases": cases}
        manifest_path = artifact / "manifest.json"
        manifest_path.write_text(canonical(manifest), encoding="utf-8")
        # Human-readable files are evidence copies. Invocation reads the hashed manifest.
        for name, source in files.items():
            path = artifact / "source" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        results = evaluate(image, source_wrapper(manifest), cases)
        passed = all(result["passed"] for result in results)
        version = sha(canonical(manifest))
        receipt_path = artifact / "receipt.json"
        receipt = {"passed": passed, "project": spec["project"], "version": version, "parent": job["parent"],
                   "job": job["id"], "attempt": attempt, "model": MODEL, "image": image, "results": results,
                   "regressions_inherited": len(inherited["cases"]), "source_files": sorted(files),
                   "controller_sha256": CONTROLLER_SHA256, "builder_sha256": sha(Path(__file__).read_text(encoding="utf-8")),
                   "scope": "frozen_examples_only", "weights_changed": False}
        receipt_path.write_text(canonical(receipt), encoding="utf-8")
        status = "tested" if passed else ("retry" if attempt < MAX_ATTEMPTS else "failed")
        with store.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT version FROM project_heads WHERE project=?", (spec["project"],)).fetchone()
            if (current[0] if current else None) != job["parent"]:
                status = "stale_parent"
            elif passed:
                con.execute("INSERT OR IGNORE INTO project_versions VALUES (?,?,?,?,?,?)",
                            (spec["project"], version, job["parent"], str(manifest_path), str(receipt_path), spec["entrypoint"]))
                con.execute("INSERT OR REPLACE INTO project_heads VALUES (?,?)", (spec["project"], version))
            con.execute("UPDATE source_jobs SET status=?,feedback=? WHERE id=?", (status, canonical(results), job["id"]))
        store.event("source_build_finished", {"job": job["id"], "status": status, "receipt": str(receipt_path)})
    except Exception as exc:
        feedback = f"{type(exc).__name__}: {exc}"
        (artifact / "error.txt").write_text(feedback, encoding="utf-8")
        with store.connect() as con:
            con.execute("UPDATE source_jobs SET status=?,feedback=? WHERE id=?",
                        ("retry" if attempt < MAX_ATTEMPTS else "failed", feedback, job["id"]))
        store.event("source_build_error", {"job": job["id"], "error": feedback})
    return True


def scheduler_spec():
    return {"project": "viv_task_scheduler", "title": "Dependency-aware task scheduling", "entrypoint": "scheduler:solve",
            "requirement": "Build scheduler.py with solve(value), plus a helper module. value is {data: tasks, options: {}}. "
            "Each task has id (string), status, priority (integer, default 0), dependencies (list of ids, default []). "
            "Return {order: [ids]} containing only queued or retry tasks whose every dependency exists and has status exactly tested. "
            "Queued and retry dependencies are NOT complete, even if they appear earlier in the output. Missing or failed dependencies "
            "block the task. Sort eligible tasks by descending priority, then ascending id. Never include running, tested, "
            "failed or cancelled tasks. Do not mutate input.",
            "cases": [
                {"input": {"data": [], "options": {}}, "expected": {"order": []}},
                {"input": {"data": [{"id": "b", "status": "queued"}, {"id": "a", "status": "retry"}], "options": {}}, "expected": {"order": ["a", "b"]}},
                {"input": {"data": [{"id": "a", "status": "tested"}, {"id": "b", "status": "queued", "dependencies": ["a"]}, {"id": "c", "status": "queued", "dependencies": ["b"]}], "options": {}}, "expected": {"order": ["b"]}},
                {"input": {"data": [{"id": "x", "status": "queued", "dependencies": ["missing"]}, {"id": "y", "status": "running"}], "options": {}}, "expected": {"order": []}},
                {"input": {"data": [{"id": "a", "status": "queued", "priority": 1}, {"id": "z", "status": "retry", "priority": 9}, {"id": "b", "status": "queued", "priority": 1}], "options": {}}, "expected": {"order": ["z", "a", "b"]}},
                {"input": {"data": [{"id": "a", "status": "failed"}, {"id": "b", "status": "queued", "dependencies": ["a"]}, {"id": "c", "status": "cancelled"}], "options": {}}, "expected": {"order": []}}]}
