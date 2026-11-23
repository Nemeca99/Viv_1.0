"""Frozen node, entry, and dependency identity probes over a real receipt."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

ROOT = Path('L:/LocalCoder')
TARGET = ROOT / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
RECEIPT = ROOT / 'workspace/autonomy/learning/neural_runs/composition_receipts/typed_composition_execution_20261116T001444Z_62c3fffb.json'
OUT = ROOT / '.opencode/evals/supervision_chain_20261117/circuit_identity'

def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('circuit_identity_target', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = digest(module.DB_PATH)
    original = json.loads(RECEIPT.read_text(encoding='utf-8'))
    assert original['candidate_store_sha256'] == before
    cases = [('valid', copy.deepcopy(original), True)]
    for node in range(2):
        for field in ('task_id', 'function_name', 'code_sha256', 'tests_sha256', 'relay_count'):
            candidate = copy.deepcopy(original)
            candidate['node_gates'][node][field] = 99 if field == 'relay_count' else 'forged-identity'
            cases.append((f'node{node}_{field}', candidate, False))
            candidate = copy.deepcopy(original)
            del candidate['node_gates'][node][field]
            cases.append((f'node{node}_missing_{field}', candidate, False))
    for label, value in (('wrong', 'forged-entry'), ('missing', None), ('number', 17)):
        candidate = copy.deepcopy(original)
        if label == 'missing':
            del candidate['entry_function']
        else:
            candidate['entry_function'] = value
        cases.append((f'entry_function_{label}', candidate, False))
    for field in ('entry_version_id', 'node_count', 'relay_count'):
        candidate = copy.deepcopy(original)
        candidate[field] = float(candidate[field])
        cases.append((f'float_{field}', candidate, False))
    candidate = copy.deepcopy(original)
    candidate['execution_order'] = [float(v) for v in candidate['execution_order']]
    cases.append(('float_execution_ids', candidate, False))
    for label, value in (('null', None), ('scalar', 6), ('string', '6,17'), ('dict', {'a':6,'b':17})):
        candidate = copy.deepcopy(original)
        candidate['execution_order'] = value
        cases.append((f'execution_order_{label}', candidate, False))
    candidate = copy.deepcopy(original)
    candidate['execution_order'] = [99, 100]
    candidate['entry_version_id'] = 100
    for node, vid in zip(candidate['node_gates'], (99, 100)):
        node['version_id'] = vid
    cases.append(('invented_circuit_ids', candidate, False))
    candidate = copy.deepcopy(original)
    candidate['execution_order'].reverse()
    candidate['node_gates'].reverse()
    candidate['entry_version_id'] = candidate['execution_order'][-1]
    candidate['entry_function'] = candidate['node_gates'][-1]['function_name']
    cases.append(('consumer_before_provider', candidate, False))
    candidate = copy.deepcopy(original)
    candidate['typed_relays'].reverse()
    cases.append(('same_relays_reordered', candidate, True))
    results = []
    for name, candidate, expected in cases:
        candidate.pop('receipt_sha256', None)
        candidate['receipt_sha256'] = canonical(candidate)
        path = OUT / (name + '.json')
        path.write_text(json.dumps(candidate, indent=2) + '\n', encoding='utf-8')
        capture = io.StringIO()
        status = None
        try:
            with contextlib.redirect_stdout(capture):
                status = module.audit_receipt(path, module.DB_PATH)
            accepted = status == 0 and capture.getvalue().strip() == 'PASS: 8 checks'
            matched = accepted if expected else status == 1 and 'FAIL: check' in capture.getvalue()
        except Exception as exc:
            matched = False
            capture.write(f'UNCAUGHT: {type(exc).__name__}: {exc}')
        results.append({'case': name, 'expected_accept': expected, 'exit': status,
                        'output': capture.getvalue().strip(), 'matched': matched})
    assert digest(module.DB_PATH) == before
    source_hash = digest(TARGET)
    failed = [row for row in results if not row['matched']]
    result = {'cases': len(results), 'passed': len(results)-len(failed), 'failed': failed,
              'db_unchanged': True, 'source_sha256': source_hash}
    path = OUT / ('result_' + source_hash[:16] + '.json')
    assert not path.exists(), 'Keep existing source-bound evidence'
    path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'cases': result['cases'], 'passed': result['passed'], 'db_unchanged': True,
                      'failed_examples': failed[:4], 'receipt': str(path)}, indent=2))
    return bool(failed)

if __name__ == '__main__':
    raise SystemExit(main())
