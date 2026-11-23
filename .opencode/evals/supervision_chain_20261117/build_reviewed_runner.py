"""Retain Viv's suite/hash helpers and copy her reviewed result validator."""
import ast
from pathlib import Path

root = Path('L:/LocalCoder')
evidence = root / '.opencode/evals/supervision_chain_20261117'
draft = (evidence / 'regression_runner_drone_attempt1.py').read_text(encoding='utf-8')
tree = ast.parse(draft)
suite_node = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SUITES' for t in n.targets))
suites = ast.get_source_segment(draft, suite_node)
hash_fn = ast.get_source_segment(draft, next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'hash_file'))
validator = (root / 'workspace/autonomy/composition_suite_result_candidate.py').read_text(encoding='utf-8')
validator_tree = ast.parse(validator)
functions = [n for n in validator_tree.body if isinstance(n, ast.FunctionDef)]
assert len(functions) == 1 and functions[0].name == 'valid_suite_result'
assert all(isinstance(n, ast.FunctionDef) or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)) for n in validator_tree.body)
validator_fn = ast.get_source_segment(validator, functions[0])
body = '''
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
        report_path.write_text(json.dumps(report, indent=2) + "\\n", encoding="utf-8")
    print(f"{'PASS' if report['ok'] else 'FAIL'}: {report_path}")
    if report["error"]:
        print(report["error"])
    return 0 if report["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
'''
source = '"""Supervised composition regression runner; no learned-state writes."""\nimport contextlib\nimport importlib.util\nimport json\nimport sys\nfrom pathlib import Path\nfrom uuid import uuid4\n\n' + suites + '\n\n' + hash_fn + '\n\n' + validator_fn + '\n\n' + body
ast.parse(source)
(root / 'workspace/autonomy/run_composition_audit_regressions_candidate.py').write_text(source, encoding='utf-8')
print('Retained Viv suite list/hash helper/result validator; repaired runner orchestration')
