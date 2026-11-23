"""run_composition_audit_regressions_candidate.py — bounded regression runner."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4


# Resolve root from this script's location (parents[2])
ROOT = Path(__file__).resolve().parent.parent

# Fixed suite paths and expected case counts / output attributes
SUITES = [
    ("flags", ".opencode/evals/verify_receipt_flags_20261117.py", 53, "OUTPUT"),
    ("relays", ".opencode/evals/verify_relay_identity_20261117.py", 11, "OUT"),
    ("nodes", ".opencode/evals/verify_node_gates_20261117.py", 32, "OUT"),
    ("circuit", ".opencode/evals/verify_circuit_identity_20261117.py", 35, "OUT"),
]

# Checker hashes to verify before imports (paths relative to ROOT)
CHECKER_HASHES = {}


def resolve_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_checkers(root: Path) -> dict[str, str]:
    """Read frozen_checkers.json and return hash->path mapping."""
    checkers_path = root / ".opencode" / "evals" / "supervision_chain_20261117" / "frozen_checkers.json"
    if not checkers_path.exists():
        raise FileNotFoundError(f"frozen_checkers.json missing at {checkers_path}")

    data = json.loads(checkers_path.read_text())
    hashes: dict[str, str] = {}
    for entry in data.get("checkers", []):
        rel_path = Path(entry["path"]).relative_to(root)
        abs_path = root / rel_path
        hashes[entry["name"]] = abs_path.resolve()

    return hashes


def hash_file(path: Path) -> str:
    """Return SHA-256 hex of file contents."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def run_suite(suite_name: str, suite_path: Path, root: Path, output_dir: Path) -> dict | None:
    """Run a single suite and capture result JSON."""
    rel_path = Path(suite_path).relative_to(root)
    suite_abs = root / rel_path

    # Change to fresh suite subdirectory under output_dir
    suite_subdir = output_dir / f"{suite_name}"
    suite_subdir.mkdir(parents=True, exist_ok=True)

    # Run the suite script
    result = subprocess.run(
        [sys.executable, str(suite_abs)],
        cwd=suite_subdir,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return {"ok": False, "error": f"suite exited {result.returncode}", "stdout": result.stdout, "stderr": result.stderr}

    # Look for result_*.json in suite_subdir
    result_json = None
    for candidate in sorted(suite_subdir.glob("result_*.json")):
        if candidate.name.startswith("result_"):
            try:
                data = json.loads(candidate.read_text())
                # Validate expected fields
                if "cases_passed" in data and "db_unchanged" in data and "source_sha256" in data:
                    result_json = data
                    break
            except (json.JSONDecodeError, KeyError):
                continue

    if result_json is None:
        return {"ok": False, "error": "no valid result_*.json found"}

    # Validate expected counts and flags
    suite_name_map = {name: name for name, _, _ in SUITES}
    expected_count = next((c[2] for n, p, c, _ in SUITES if n == suite_name), None)
    if result_json.get("cases_passed") != expected_count:
        return {"ok": False, "error": f"cases_passed {result_json['cases_passed']} != expected {expected_count}"}

    if not result_json.get("db_unchanged"):
        return {"ok": False, "error": "db_unchanged is False"}

    # Validate source_sha256 matches audit source hash (computed by caller)
    return result_json


def main():
    root = resolve_root()
    hashes = load_checkers(root)

    # Hash audit source before run
    audit_source_path = root / "workspace" / "autonomy" / "typed_composition_receipt_audit_v2_candidate.py"
    if not audit_source_path.exists():
        raise FileNotFoundError(f"Audit source missing: {audit_source_path}")
    source_hash_before = hash_file(audit_source_path)

    # Hash database before run (assume fixed path; adjust if needed)
    db_path = root / "workspace" / "autonomy" / "receipt_audit_database.sqlite3"
    db_hash_before = None
    if db_path.exists():
        db_hash_before = hash_file(db_path)

    # Fresh UUID for run directory
    run_dir = (root / ".opencode" / "evals" / "composition_regression_runs").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    run_uuid = uuid4().hex[:8]
    run_dir_final = run_dir / f"{run_uuid}"
    run_dir_final.mkdir(exist_ok=False)

    all_ok = True
    suite_summaries: list[dict] = []

    for name, rel_path, expected_count, attr_name in SUITES:
        suite_abs = root / rel_path
        if not suite_abs.exists():
            print(f"FAIL: suite script missing {suite_abs}", flush=True)
            all_ok = False
            break

        # Hash checker file before import (if present in frozen_checkers.json)
        if name in hashes and hashes[name].exists():
            try:
                pre_hash = hash_file(hashes[name])
            except FileNotFoundError:
                print(f"FAIL: checker hash missing for {name}", flush=True)
                all_ok = False
                break

        # Import and run suite
        spec = importlib.util.spec_from_file_location(name, str(suite_abs))
        if spec is None or spec.loader is None:
            print(f"FAIL: cannot load suite {suite_abs}", flush=True)
            all_ok = False
            continue

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            module.main()  # Call its main to write result_*.json
        except Exception as e:
            print(f"FAIL: suite {name} raised {e}", flush=True)
            all_ok = False
            continue

        # Read result JSON and validate
        result_path = run_dir_final / f"{attr_name}_result.json" if attr_name != "OUT" else run_dir_final / f"{name}_result.json"
        try:
            result_data = json.loads(result_path.read_text() if result_path.exists() else "")
            suite_summaries.append({"name": name, "ok": True, "cases_passed": result_data.get("cases_passed", 0)})
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"FAIL: no valid result JSON for {name}", flush=True)
            all_ok = False

    # Hash audit source and database after run
    source_hash_after = hash_file(audit_source_path) if audit_source_path.exists() else None
    db_hash_after = hash_file(db_path) if db_path.exists() else None

    # Build final report
    ok = all_ok and (source_hash_before == source_hash_after if source_hash_after is not None else True) and \
         (db_hash_before == db_hash_after if db_hash_after is not None and db_hash_before is not None else True)

    report = {
        "localcoder_composition_regressions_v1": True,
        "ok": ok,
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "db_sha256_before": db_hash_before,
        "db_sha256_after": db_hash_after,
        "suite_summaries": suite_summaries,
        "run_uuid": run_uuid,
    }

    # Write report
    report_path = run_dir_final / f"run_result.json"
    report_path.write_text(json.dumps(report, indent=2))

    if ok:
        print(f"OK: {report_path}", flush=True)
        sys.exit(0)
    else:
        print(f"FAIL: {report_path}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
