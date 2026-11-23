"""Supervised composition regression runner; no learned-state writes."""
import contextlib
import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4

SUITES = [
    ("flags", ".opencode/evals/verify_receipt_flags_20261117.py", 53, "OUTPUT"),
    ("relays", ".opencode/evals/verify_relay_identity_20261117.py", 11, "OUT"),
    ("nodes", ".opencode/evals/verify_node_gates_20261117.py", 32, "OUT"),
    ("circuit", ".opencode/evals/verify_circuit_identity_20261117.py", 35, "OUT"),
]

def hash_file(path: Path) -> str:
    """Return SHA-256 hex of file contents."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def valid_suite_result(record: dict, expected_count: int, source_sha256: str) -> bool:
    """Validate a suite result record against schema and counts.

    Returns True only if all checks pass; False otherwise.
    No I/O, imports with side effects, prints, or main block.
    """
    # Require record to be a dict
    if not isinstance(record, dict):
        return False

    # Required keys must exist
    required_keys = ("cases", "passed", "failed", "db_unchanged", "source_sha256")
    for key in required_keys:
        if key not in record:
            return False

    # Require expected_count to be int and positive
    if type(expected_count) is not int or expected_count <= 0:
        return False

    # Verify cases and passed are int, equal to each other, and equal to expected_count
    cases = record.get("cases")
    passed = record.get("passed")

    if type(cases) is not int or type(passed) is not int:
        return False
    if cases != passed:
        return False
    if cases != expected_count:
        return False

    # Require failed to be an empty list
    failed = record.get("failed")
    if not isinstance(failed, list) or len(failed) != 0:
        return False

    # Require db_unchanged to be exactly True
    if record.get("db_unchanged") is not True:
        return False

    # Require source_sha256 to be a string equal to the provided hash
    record_hash = record.get("source_sha256")
    if not isinstance(record_hash, str) or record_hash != source_sha256:
        return False

    return True


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    run_dir = root / ".opencode/evals/composition_regression_runs" / uuid4().hex
    run_dir.mkdir(parents=True, exist_ok=False)
    source = root / "workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py"
    database = root / "workspace/autonomy/learning/neural_runs/candidate_verified_functions.sqlite3"
    report = {"schema": "localcoder_composition_regressions_v1", "ok": False,
              "run_directory": str(run_dir), "suites": [], "error": None}
    source_before = database_before = None
    try:
        if sys.flags.optimize:
            raise RuntimeError("Python optimization disables required checker assertions")
        frozen = json.loads((root / ".opencode/evals/supervision_chain_20261117/frozen_checkers.json").read_text(encoding="utf-8"))
        expected_paths = {item[1] for item in SUITES}
        if not isinstance(frozen, dict) or set(frozen) != expected_paths:
            raise RuntimeError("Frozen checker manifest must name exactly the four fixed suites")
        for relative in expected_paths:
            if hash_file(root / relative) != frozen[relative]:
                raise RuntimeError(f"Checker hash mismatch before imports: {relative}")
        source_before, database_before = hash_file(source), hash_file(database)
        report.update(source_sha256=source_before, database_sha256=database_before)
        for name, relative, count, output_attribute in SUITES:
            suite_dir = run_dir / name
            suite_dir.mkdir()
            summary = {"name": name, "ok": False, "checker_sha256": frozen[relative]}
            report["suites"].append(summary)
            with (suite_dir / "stdout.log").open("x", encoding="utf-8") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    spec = importlib.util.spec_from_file_location("composition_regression_" + name, root / relative)
                    if spec is None or spec.loader is None:
                        raise RuntimeError(f"Cannot import checker: {name}")
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if not hasattr(module, output_attribute):
                        raise RuntimeError(f"Checker lacks output attribute: {name}")
                    setattr(module, output_attribute, suite_dir)
                    status = module.main()
            if status != 0:
                raise RuntimeError(f"Checker {name} exited {status}")
            results = list(suite_dir.glob("result_*.json"))
            if len(results) != 1:
                raise RuntimeError(f"Checker {name} produced {len(results)} results")
            result = json.loads(results[0].read_text(encoding="utf-8"))
            if not valid_suite_result(result, count, source_before):
                raise RuntimeError(f"Checker result failed validation: {name}")
            summary.update(ok=True, cases=result["cases"], passed=result["passed"], result_path=str(results[0]))
        report["ok"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            source_after, database_after = hash_file(source), hash_file(database)
            report.update(source_sha256_after=source_after, database_sha256_after=database_after,
                          source_unchanged=source_before is not None and source_before == source_after,
                          database_unchanged=database_before is not None and database_before == database_after)
            if report["ok"] and not (report["source_unchanged"] and report["database_unchanged"]):
                report.update(ok=False, error="Source or database changed during regression run")
        except Exception as exc:
            report.update(ok=False, error=f"Integrity check failed: {exc}")
        report_path = run_dir / "run_result.json"
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{'PASS' if report['ok'] else 'FAIL'}: {report_path}")
    if report["error"]:
        print(report["error"])
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
