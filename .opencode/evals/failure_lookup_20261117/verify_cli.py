"""Independent CLI checks; existing result/source files must stay unchanged."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path('L:/LocalCoder')
TARGET = ROOT / 'workspace/autonomy/receipt_failure_lookup_candidate.py'
RECORDS = ROOT / '.opencode/evals/receipt_flags_20261117'
SOURCE = ROOT / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'


def main():
    paths = [SOURCE, *RECORDS.glob('result_*.json')]
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    command = [sys.executable, '-B', str(TARGET)]
    result = subprocess.run(command + ['--case', 'valid', '--limit', '1'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout)
    assert data['schema'] == 'localcoder_failure_lookup_v1'
    assert data['total_matches'] == 2 and len(data['failures']) == 1
    assert data['failures'][0]['case'] == 'valid'
    assert data['failures'][0]['source_matches_current'] is False
    assert any(row['passed'] == 53 and row['failed_count'] == 0 for row in data['current_results'])
    result = subprocess.run(command + ['--case', 'ABSENT_QUERY'], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    absent = json.loads(result.stdout)
    assert absent['total_matches'] == 0 and absent['failures'] == []
    for value in ('0', '21', 'true'):
        result = subprocess.run(command + ['--limit', value], capture_output=True, text=True, timeout=15)
        assert result.returncode != 0, f'Invalid limit accepted: {value}'
    result = subprocess.run(command + ['--root', str(RECORDS / 'missing-directory')], capture_output=True, text=True, timeout=15)
    assert result.returncode != 0
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == value for p, value in before.items())
    print('PASS: CLI filtering, bounds, missing-root errors; real inputs unchanged')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'FAIL: {type(error).__name__}: {error}', flush=True)
        sys.exit(1)
