"""Independent pure result-record validation checks."""
import copy
import importlib.util
from pathlib import Path
import sys

TARGET = Path('L:/LocalCoder/workspace/autonomy/receipt_failure_lookup_candidate.py')


def main():
    spec = importlib.util.spec_from_file_location('lookup_validation_target', TARGET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = {'case': 'example', 'exit': 1, 'expected_accept': False, 'matched': False, 'output': ''}
    valid = {'cases': 2, 'passed': 1, 'failed': [row], 'db_unchanged': True, 'source_sha256': 'a' * 64}
    before = copy.deepcopy(valid)
    assert module.validate_result(valid) == valid
    assert valid == before
    assert module.validate_result({**valid, 'cases': 1, 'passed': 1, 'failed': []})['failed'] == []
    invalid = [None, [], {}, {**valid, 'cases': True}, {**valid, 'passed': False},
               {**valid, 'cases': 0}, {**valid, 'passed': -1}, {**valid, 'passed': 3},
               {**valid, 'db_unchanged': 1}, {**valid, 'db_unchanged': False},
               {**valid, 'source_sha256': 'A' * 64}, {**valid, 'source_sha256': 'z' * 64},
               {**valid, 'source_sha256': None}, {**valid, 'failed': None},
               {**valid, 'failed': []}, {**valid, 'failed': ['wrong']},
               {**valid, 'cases': 3, 'failed': [row, row]}]
    for key in valid:
        missing = copy.deepcopy(valid)
        del missing[key]
        invalid.append(missing)
    for key, value in [('case', ''), ('case', 1), ('exit', True), ('exit', '1'),
                       ('expected_accept', 0), ('matched', 0), ('matched', True), ('output', None)]:
        invalid.append({**valid, 'failed': [{**row, key: value}]})
    for key in row:
        missing = dict(row)
        del missing[key]
        invalid.append({**valid, 'failed': [missing]})
    for index, candidate in enumerate(invalid):
        frozen = copy.deepcopy(candidate)
        try:
            module.validate_result(candidate)
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid record accepted: case {index}')
        assert candidate == frozen
    print(f'PASS: {2 + len(invalid)} validation cases; inputs unchanged')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'FAIL: {type(error).__name__}: {error}', flush=True)
        sys.exit(1)
