"""Independent receipt-flag checks; reads the candidate store without changing it."""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import itertools
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path('L:/LocalCoder')
TARGET = ROOT / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
RECEIPT = ROOT / 'workspace/autonomy/learning/neural_runs/composition_receipts/typed_composition_execution_20261116T001444Z_62c3fffb.json'
OUTPUT = ROOT / '.opencode/evals/receipt_flags_20261117'
FIELDS = ('candidate_store_read_only', 'promoted', 'live_viv_modified', 'model_weights_changed')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    spec = importlib.util.spec_from_file_location('receipt_flags_target', TARGET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = digest(module.DB_PATH)
    with sqlite3.connect(f'file:{module.DB_PATH.as_posix()}?mode=ro', uri=True) as connection:
        connection.execute('PRAGMA query_only=ON')
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='typed_function_relays_v1'").fetchone()
    original = json.loads(RECEIPT.read_text(encoding='utf-8'))
    assert original['candidate_store_sha256'] == before, 'The historical fixture no longer binds the current DB; stop.'
    cases = [('valid', copy.deepcopy(original), True)]
    for values in itertools.product((False, True), repeat=4):
        candidate = copy.deepcopy(original)
        candidate.update(zip(FIELDS, values))
        cases.append(('bool_' + ''.join(str(int(v)) for v in values), candidate, values == (True, False, False, False)))
    for field in FIELDS:
        missing = copy.deepcopy(original)
        del missing[field]
        cases.append(('missing_' + field, missing, False))
        for index, value in enumerate((None, 0, 1, '', 'false', 'true', [], {})):
            candidate = copy.deepcopy(original)
            candidate[field] = value
            cases.append((f'nonbool_{field}_{index}', candidate, False))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []
    for name, candidate, expected in cases:
        candidate.pop('receipt_sha256', None)
        encoded = json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        candidate['receipt_sha256'] = hashlib.sha256(encoded).hexdigest()
        path = OUTPUT / (name + '.json')
        path.write_text(json.dumps(candidate, indent=2) + '\n', encoding='utf-8')
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status = module.audit_receipt(path, module.DB_PATH)
        text = captured.getvalue()
        accepted = status == 0 and 'PASS: 8 checks' in text
        # Rehashed negative fixtures must reach check 8, rather than fail an unrelated hash check.
        matches = accepted if expected else status == 1 and 'FAIL: check8_' in text
        results.append({'case': name, 'expected_accept': expected, 'exit': status,
                        'output': text.strip(), 'matched': matches})
    assert digest(module.DB_PATH) == before, 'Candidate store changed during a read-only audit.'
    failures = [row for row in results if not row['matched']]
    source_hash = digest(TARGET)
    summary = {'cases': len(cases), 'passed': len(cases) - len(failures), 'failed': failures,
               'db_unchanged': True, 'source_sha256': source_hash}
    path = OUTPUT / f'result_{source_hash[:16]}.json'
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(f"{'PASS' if not failures else 'FAIL'}: {summary['passed']}/{len(cases)} receipt flag cases; DB unchanged; receipt={path.as_posix()}")
    for failure in failures[:3]:
        print(json.dumps(failure))
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
