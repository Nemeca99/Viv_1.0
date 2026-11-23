"""Run only inside the existing isolated, read-only Rust verification container."""
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

BANNED = {'eval', 'exec', 'compile', 'open', 'input', '__import__', 'globals', 'locals',
          'getattr', 'setattr', 'delattr', 'vars', 'dir', 'breakpoint', 'print', 'help'}

def code_check(row, folder):
    source = row['output'].strip()
    if source.startswith('```'):
        lines = source.splitlines()
        if lines[-1].strip() != '```':
            return False
        source = '\n'.join(lines[1:-1])
    try:
        tree = ast.parse(source)
        if any(isinstance(n, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef)) or
               (isinstance(n, ast.Name) and (n.id in BANNED or n.id.startswith('__'))) or
               (isinstance(n, ast.Attribute) and n.attr.startswith('__')) for n in ast.walk(tree)):
            return False
        if any(not isinstance(n, (ast.FunctionDef, ast.Assign, ast.AnnAssign)) for n in tree.body):
            return False
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.decorator_list:
                return False
        candidate = folder / (row['id'] + '.py')
        # The candidate source is read directly from the frozen evaluation fixture, never written here.
        wrapper = (
            'import json\n'
            'payload=json.loads(input())\n'
            'namespace={}\n'
            'exec(compile(payload["source"], "candidate", "exec"), namespace)\n'
            'function=namespace[payload["function"]]\n'
            'for arguments, expected in payload["cases"]:\n'
            '    before=json.dumps(arguments,sort_keys=True)\n'
            '    assert function(*arguments)==expected\n'
            '    assert json.dumps(arguments,sort_keys=True)==before\n'
        )
        result = subprocess.run([sys.executable, '-I', '-B', '-c', wrapper],
                                input=json.dumps({'source': source, 'function': row['function'], 'cases': row['cases']}),
                                capture_output=True, text=True, timeout=2)
        return result.returncode == 0
    except (SyntaxError, ValueError, subprocess.TimeoutExpired):
        return False

def main():
    path = Path(sys.argv[1])
    suite = json.loads(path.read_text(encoding='utf-8'))
    scores = {k: {'passed': 0, 'total': 0} for k in ('identity', 'behavior', 'coding')}
    outcomes = {}
    for row in suite['outputs']:
        if row['category'] == 'coding':
            passed = code_check(row, path.parent)
        else:
            text = row['output'].casefold().replace('\u2019', "'")
            passed = (all(term in text for term in row['required']) and
                      not any(re.search(pattern, text) for pattern in row['forbidden']))
        outcomes[row['id']] = passed
        scores[row['category']]['total'] += 1
        scores[row['category']]['passed'] += int(passed)
    criteria = suite['criteria']
    passed = all(scores[k]['passed'] / scores[k]['total'] >= criteria[k] for k in ('identity', 'behavior'))
    passed = passed and scores['coding']['passed'] >= max(criteria['coding_minimum'], suite['baseline_coding'])
    print(json.dumps({'passed': passed, 'scores': scores, 'outcomes': outcomes}, separators=(',', ':')))
    return 0 if passed else 1

if __name__ == '__main__':
    raise SystemExit(main())
