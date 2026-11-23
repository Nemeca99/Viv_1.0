"""Frozen relay-identity probes: re-seal negatives to reach nested validation."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

ROOT = Path('L:/LocalCoder')
TARGET = ROOT / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
ORIGINAL = ROOT / 'workspace/autonomy/learning/neural_runs/composition_receipts/typed_composition_execution_20261116T001444Z_62c3fffb.json'
OUT = ROOT / '.opencode/evals/relay_identity_20261117'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def seal_edge(edge):
    edge.pop('receipt_sha256', None)
    edge['receipt_sha256'] = canonical(edge)

def main():
    OUT.mkdir(exist_ok=True)
    spec = importlib.util.spec_from_file_location('relay_identity_target', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db_hash = digest(module.DB_PATH)
    original = json.loads(ORIGINAL.read_text(encoding='utf-8'))
    assert original['candidate_store_sha256'] == db_hash
    cases = [('valid', copy.deepcopy(original), True)]
    for index, value in enumerate(('0' * 64, 'forged-relay-id', '', None, 7)):
        receipt = copy.deepcopy(original)
        receipt['typed_relays'][0]['relay_key'] = value
        seal_edge(receipt['typed_relays'][0])
        cases.append((f'relay_key_tamper_{index}', receipt, False))
    missing = copy.deepcopy(original)
    del missing['typed_relays'][0]['relay_key']
    seal_edge(missing['typed_relays'][0])
    cases.append(('missing_relay_key', missing, False))
    for field in ('provider_code_sha256', 'consumer_tests_sha256', 'direction'):
        receipt = copy.deepcopy(original)
        edge = receipt['typed_relays'][0]
        edge[field] = 'forged-but-resealed'
        edge.pop('receipt_sha256')
        edge.pop('relay_key')
        edge['relay_key'] = canonical(edge)
        seal_edge(edge)
        cases.append((f'resealed_unbound_{field}', receipt, False))
    reordered = copy.deepcopy(original)
    reordered['typed_relays'].reverse()
    cases.append(('same_edges_reordered', reordered, True))
    results = []
    for name, receipt, expected in cases:
        receipt.pop('receipt_sha256', None)
        receipt['receipt_sha256'] = canonical(receipt)
        path = OUT / (name + '.json')
        path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        stdout = io.StringIO()
        status = None
        try:
            with contextlib.redirect_stdout(stdout):
                status = module.audit_receipt(path, module.DB_PATH)
            accepted = status == 0 and stdout.getvalue().strip() == 'PASS: 8 checks'
            matched = accepted if expected else status == 1 and 'FAIL: check' in stdout.getvalue()
        except Exception as exc:
            matched = False
            stdout.write(f'UNCAUGHT: {type(exc).__name__}: {exc}')
        results.append({'case': name, 'expected_accept': expected, 'exit': status,
                        'output': stdout.getvalue().strip(), 'matched': matched})
    assert digest(module.DB_PATH) == db_hash, 'Read-only candidate store changed'
    source_hash = digest(TARGET)
    failed = [row for row in results if not row['matched']]
    record = {'cases': len(results), 'passed': len(results)-len(failed), 'failed': failed,
              'db_unchanged': True, 'source_sha256': source_hash}
    path = OUT / ('result_' + source_hash[:16] + '.json')
    assert not path.exists(), 'Retain existing evidence instead of overwriting it'
    path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, indent=2))
    return bool(failed)

if __name__ == '__main__':
    raise SystemExit(main())
