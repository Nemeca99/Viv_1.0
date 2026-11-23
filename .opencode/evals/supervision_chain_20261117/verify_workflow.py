"""Black-box workflow controls in retained, isolated fixture projects."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path('L:/LocalCoder')
RUNNER = ROOT / 'workspace/autonomy/run_composition_audit_regressions_candidate.py'
OUT = ROOT / '.opencode/evals/supervision_chain_20261117/workflow_checks' / uuid4().hex
SUITES = [('flags','verify_receipt_flags_20261117.py',53), ('relays','verify_relay_identity_20261117.py',11),
          ('nodes','verify_node_gates_20261117.py',32), ('circuit','verify_circuit_identity_20261117.py',35)]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def report_after(root, runner, *flags):
    outputs = root / '.opencode/evals/composition_regression_runs'
    before = set(outputs.glob('*/run_result.json')) if outputs.exists() else set()
    process = subprocess.run([sys.executable, '-B', *flags, str(runner)], cwd=root,
                             capture_output=True, text=True, timeout=30)
    created = set(outputs.glob('*/run_result.json')) - before
    assert len(created) == 1, (process.stdout, process.stderr)
    path = created.pop()
    return process, json.loads(path.read_text()), path

def fixture(label, invalid_hash=False, invalid_result=False, mutate_database=False):
    root = OUT / label
    target = root / 'workspace/autonomy' / RUNNER.name
    target.parent.mkdir(parents=True)
    shutil.copy2(RUNNER, target)
    (target.parent / 'typed_composition_receipt_audit_v2_candidate.py').write_text('# isolated source\n')
    db = target.parent / 'learning/neural_runs/candidate_verified_functions.sqlite3'
    db.parent.mkdir(parents=True)
    db.write_bytes(b'isolated integrity fixture, not the live SQLite store')
    frozen = {}
    for name, basename, count in SUITES:
        path = root / '.opencode/evals' / basename
        path.parent.mkdir(parents=True, exist_ok=True)
        code = '''from pathlib import Path
import hashlib,json
Path(__file__).with_suffix('.imported').write_text('imported')
OUT=OUTPUT=None
def main():
    root=Path(__file__).resolve().parents[2]
    output=OUTPUT if OUTPUT is not None else OUT
    output.mkdir(parents=True,exist_ok=True)
    source=root/'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
    record={'cases': COUNT, 'passed': COUNT, 'failed': [], 'db_unchanged': True,
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    (output/'result_fixture.json').write_text(json.dumps(record))
    MUTATION
    return 0
'''
        code = code.replace('COUNT', str(0 if invalid_result else count))
        mutation = "(root/'workspace/autonomy/learning/neural_runs/candidate_verified_functions.sqlite3').write_bytes(b'changed fixture')" if mutate_database and name == 'flags' else 'pass'
        path.write_text(code.replace('MUTATION', mutation), encoding='utf-8')
        frozen['.opencode/evals/' + basename] = '0' * 64 if invalid_hash else digest(path)
    manifest = root / '.opencode/evals/supervision_chain_20261117/frozen_checkers.json'
    manifest.parent.mkdir()
    manifest.write_text(json.dumps(frozen))
    return root, target

def main():
    OUT.mkdir(parents=True)
    source = ROOT / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
    database = ROOT / 'workspace/autonomy/learning/neural_runs/candidate_verified_functions.sqlite3'
    original = digest(source), digest(database)
    spec = importlib.util.spec_from_file_location('workflow_runner_probe', RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    valid = {'cases': 1, 'passed': 1, 'failed': [], 'db_unchanged': True, 'source_sha256': 'a'*64}
    assert module.valid_suite_result(valid, 1, 'a'*64) is True
    for field, value in [('cases',True),('passed',True),('failed',()),('db_unchanged',1),('source_sha256',None)]:
        record = copy.deepcopy(valid)
        record[field] = value
        assert module.valid_suite_result(record, 1, 'a'*64) is False
    assert module.valid_suite_result(valid, True, 'a'*64) is False
    tests = ['strict result types']
    root, runner = fixture('invalid_hash', invalid_hash=True)
    process, report, path = report_after(root, runner)
    assert process.returncode != 0 and report['ok'] is False
    assert 'hash mismatch' in report['error'].lower()
    assert not list(root.rglob('*.imported')), 'Hash failure must precede every checker import'
    tests.append('reject changed checkers before imports')
    root, runner = fixture('invalid_result', invalid_result=True)
    process, report, path = report_after(root, runner)
    assert process.returncode != 0 and report['ok'] is False
    assert 'result failed validation' in report['error'].lower()
    assert (root / '.opencode/evals/verify_receipt_flags_20261117.imported').exists()
    assert len(list(root.rglob('*.imported'))) == 1, 'Stop after first failed suite'
    tests.append('reject false success and stop at first failure')
    root, runner = fixture('changed_database', mutate_database=True)
    process, report, path = report_after(root, runner)
    assert process.returncode != 0 and report['ok'] is False and report['database_unchanged'] is False
    assert all(suite['ok'] is True for suite in report['suites']), 'Independent final integrity check must catch false unchanged claims'
    tests.append('detect database change despite passing suite claims')
    process, report, path = report_after(ROOT, RUNNER, '-O')
    assert process.returncode != 0 and report['ok'] is False and 'optimization' in report['error'].lower()
    assert report['suites'] == []
    tests.append('refuse optimized assertion-free execution')
    previous = {path: digest(path) for path in (ROOT / '.opencode/evals/composition_regression_runs').rglob('*') if path.is_file()}
    process, report, path = report_after(ROOT, RUNNER)
    assert process.returncode == 0 and report['ok'] is True
    assert report['source_unchanged'] is True and report['database_unchanged'] is True
    assert sum(row['cases'] for row in report['suites']) == 131
    assert all(digest(path) == value for path,value in previous.items()), 'Earlier run evidence changed'
    assert original == (digest(source), digest(database))
    tests.append('fresh 131-case run preserves prior evidence and live inputs')
    result = {'schema': 'localcoder_regression_workflow_checks_v1', 'passed': True, 'checks': tests,
              'success_receipt': str(path), 'runner_sha256': digest(RUNNER), 'live_inputs_unchanged': True}
    (OUT / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
