"""Frozen independent tests for the Drone's read-only failure lookup."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path('L:/LocalCoder')
TARGET = ROOT / 'workspace/autonomy/receipt_failure_lookup_candidate.py'
OUTPUT = ROOT / '.opencode/evals/failure_lookup_20261117'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    spec = importlib.util.spec_from_file_location('drone_failure_lookup', TARGET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lookup = module.lookup_failures
    checks = []
    with tempfile.TemporaryDirectory(dir=OUTPUT) as temporary:
        work = Path(temporary)
        assert work.resolve().is_relative_to(OUTPUT.resolve())
        receipts = work / 'results'
        receipts.mkdir()
        source = work / 'source.py'
        source.write_text('current source\n', encoding='utf-8')
        current_hash = digest(source)
        old = {'cases': 3, 'passed': 1, 'source_sha256': 'a' * 64, 'db_unchanged': True,
               'failed': [{'case': 'absent_flag', 'exit': 1, 'expected_accept': False,
                           'matched': False, 'output': ''},
                          {'case': 'wrong_type', 'exit': 1, 'expected_accept': False,
                           'matched': False, 'output': 'actual gate output ' + 'x' * 700}]}
        current = {'cases': 3, 'passed': 3, 'source_sha256': current_hash,
                   'db_unchanged': True, 'failed': []}
        (receipts / 'result_01.json').write_text(json.dumps(old), encoding='utf-8')
        (receipts / 'result_02.json').write_text(json.dumps(current), encoding='utf-8')
        (receipts / 'ignored.json').write_text('{broken', encoding='utf-8')
        nested = receipts / 'nested'
        nested.mkdir()
        (nested / 'result_other.json').write_text(json.dumps(old), encoding='utf-8')
        before = {str(path): digest(path) for path in work.rglob('*') if path.is_file()}
        result = lookup(receipts, source)
        assert result['schema'] == 'localcoder_failure_lookup_v1'
        assert result['current_source_sha256'] == current_hash
        assert result['scanned_results'] == 2
        assert result['total_matches'] == 2
        assert len(result['failures']) == 2
        assert not result['invalid_results']
        first, second = result['failures']
        assert first['case'] == 'absent_flag' and first['output'] == ''
        assert first['exit'] == 1 and first['expected_accept'] is False
        assert first['source_sha256'] == 'a' * 64 and first['source_matches_current'] is False
        assert first['record_sha256'] == digest(receipts / 'result_01.json')
        assert Path(first['result_path']).resolve() == (receipts / 'result_01.json').resolve()
        assert len(second['output']) == 500 and second['output'] == old['failed'][1]['output'][:500]
        assert 'reason' not in first and 'resolved' not in first
        assert len(result['current_results']) == 1
        assert result['current_results'][0]['passed'] == 3
        assert result['current_results'][0]['failed_count'] == 0
        assert result['current_results'][0]['record_sha256'] == digest(receipts / 'result_02.json')
        checks.append('observed facts, provenance, source association, bounded output, no inferred reasons')
        selected = lookup(str(receipts), str(source), case='wrong_type', limit=1)
        assert selected['total_matches'] == 1 and len(selected['failures']) == 1
        assert selected['failures'][0]['case'] == 'wrong_type'
        assert len(selected['current_results']) == 1
        assert not lookup(receipts, source, case='Wrong_type')['failures']
        limited = lookup(receipts, source, limit=1)
        assert limited['total_matches'] == 2 and len(limited['failures']) == 1
        assert lookup(receipts, source) == result
        checks.append('exact filters, limits, strings and Path inputs, deterministic order')
        for bad_limit in (0, 21, True, 2.5, '2'):
            try:
                lookup(receipts, source, limit=bad_limit)
            except (ValueError, TypeError):
                pass
            else:
                raise AssertionError(f'Invalid limit accepted: {bad_limit!r}')
        checks.append('invalid limits rejected including bool')
        malformed = receipts / 'result_03.json'
        for bad in ('not JSON', [], {**current, 'passed': True}, {**current, 'db_unchanged': 1},
                    {**current, 'source_sha256': 'invalid'}, {**current, 'failed': old['failed']},
                    {**old, 'failed': [old['failed'][0], old['failed'][0]]},
                    {**old, 'failed': [{**old['failed'][0], 'exit': True}, old['failed'][1]]}):
            malformed.write_text(bad if isinstance(bad, str) else json.dumps(bad), encoding='utf-8')
            observed = lookup(receipts, source)
            assert len(observed['invalid_results']) == 1
            assert observed['invalid_results'][0]['error']
            assert observed['total_matches'] == 2
        malformed.write_bytes(b' ' * (1024 * 1024 + 1))
        assert lookup(receipts, source)['invalid_results']
        checks.append('malformed, oversized, and inconsistent records reported')
        malformed.unlink()
        after = {str(path): digest(path) for path in work.rglob('*') if path.is_file()}
        assert before == after, 'Lookup modified its source/result inputs'
        checks.append('input bytes unchanged')
        many = work / 'many'
        many.mkdir()
        for index in range(129):
            (many / f'result_{index:03}.json').write_text(json.dumps(current), encoding='utf-8')
        try:
            lookup(many, source)
        except ValueError:
            pass
        else:
            raise AssertionError('More than 128 result files were accepted')
        checks.append('scan bound enforced')
    live_root = ROOT / '.opencode/evals/receipt_flags_20261117'
    live_source = ROOT / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
    original_hashes = {str(path): digest(path) for path in [live_source, *live_root.glob('result_*.json')]}
    live = lookup(live_root, live_source, case='valid')
    assert live['total_matches'] == 2
    assert len(live['failures']) == 2 and all(row['case'] == 'valid' for row in live['failures'])
    assert all(not row['source_matches_current'] for row in live['failures'])
    assert any(row['passed'] == 53 and row['failed_count'] == 0 for row in live['current_results'])
    assert all(digest(Path(path)) == value for path, value in original_hashes.items())
    checks.append('real historical failures and current 53/53 result retrieved without writes')
    report = {'result': 'passed', 'checks': checks, 'source_sha256': digest(TARGET)}
    (OUTPUT / ('core_result_' + report['source_sha256'][:16] + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'PASS: {len(checks)} failure lookup groups; real receipts unchanged')


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        print(f'FAIL: {type(error).__name__}: {error}', flush=True)
        sys.exit(1)
