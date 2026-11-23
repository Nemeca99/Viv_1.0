"""Positive/negative grader controls; synthetic fixtures, never learning evidence."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from train import DEFAULT_WORK, verify, record

def main():
    name = 'grader-control-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    outputs = [
        {'id': 'label-control', 'category': 'identity', 'output': 'control-label',
         'required': ['control-label'], 'forbidden': []},
        {'id': 'behavior-control', 'category': 'behavior', 'output': 'control-behavior',
         'required': ['control-behavior'], 'forbidden': []},
        {'id': 'code-control', 'category': 'coding', 'output': 'def twice(value):\n    return value * 2',
         'function': 'twice', 'cases': [[[3], 6], [[-4], -8], [[0], 0]]},
    ]
    manifest = {'criteria': {'identity': 1.0, 'behavior': 1.0, 'coding_minimum': 1}}
    positive, proof = verify(outputs, manifest, 1, name + '-positive', DEFAULT_WORK)
    assert positive['passed'] and proof['evidence']['verified']
    negative = copy.deepcopy(outputs)
    negative[-1]['output'] = 'def twice(value):\n    return 0'
    failed, proof = verify(negative, manifest, 1, name + '-wrong-code', DEFAULT_WORK)
    assert not failed['passed'] and not proof['evidence']['verified']
    negative[-1]['output'] = 'print("PASS")\ndef twice(value):\n    return 0'
    failed, proof = verify(negative, manifest, 1, name + '-printed-pass', DEFAULT_WORK)
    assert not failed['passed'] and not proof['evidence']['verified']
    result = {'result': 'PASS', 'scope': 'Grader controls only, not model or identity evidence',
              'correct_code_accepted': True, 'wrong_code_rejected': True, 'printed_success_rejected': True}
    record(DEFAULT_WORK / (name + '.json'), result)
    print(json.dumps(result))

if __name__ == '__main__':
    main()
