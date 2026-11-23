"""Frozen node-gate acceptance probes; candidate DB is read only."""
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
OUT = ROOT / '.opencode/evals/supervision_chain_20261117/node_gates'

def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('node_gate_target', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    before = digest(module.DB_PATH)
    original = json.loads(RECEIPT.read_text(encoding='utf-8'))
    assert original['candidate_store_sha256'] == before
    cases = [('valid', copy.deepcopy(original), True)]
    for node in range(2):
        for index, value in enumerate(('DENY', 'allow', None, True, 1, [])):
            candidate = copy.deepcopy(original)
            candidate['node_gates'][node]['gate']['status'] = value
            cases.append((f'node{node}_status_{index}', candidate, False))
        for field in ('gate', 'version_id'):
            candidate = copy.deepcopy(original)
            del candidate['node_gates'][node][field]
            cases.append((f'node{node}_missing_{field}', candidate, False))
        for field in ('status', 'output'):
            candidate = copy.deepcopy(original)
            del candidate['node_gates'][node]['gate'][field]
            cases.append((f'node{node}_missing_gate_{field}', candidate, False))
        for label, value in (('gate_list', []), ('gate_null', None), ('output_number', 7)):
            candidate = copy.deepcopy(original)
            if label == 'output_number':
                candidate['node_gates'][node]['gate']['output'] = value
            else:
                candidate['node_gates'][node]['gate'] = value
            cases.append((f'node{node}_{label}', candidate, False))
        candidate = copy.deepcopy(original)
        candidate['node_gates'][node] = None
        cases.append((f'node{node}_null', candidate, False))
    for label, value in (('null', None), ('object', {}), ('short', original['node_gates'][:1])):
        candidate = copy.deepcopy(original)
        candidate['node_gates'] = value
        cases.append((f'node_gates_{label}', candidate, False))
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
            matched = accepted if expected else status == 1 and 'FAIL: check6_' in capture.getvalue()
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
