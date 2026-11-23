"""Snapshot and connect the reviewed failure lookup; no model/runtime changes."""
import json
import shutil
from pathlib import Path

root = Path('L:/LocalCoder')
evidence = root / '.opencode/evals/failure_lookup_20261117'
snap = evidence / 'before_integration'
snap.mkdir(exist_ok=True)
for relative in ('opencode.json', 'AGENTS.md', '.opencode/plugins/localcoder-drone-assignment-gate.ts'):
    target = snap / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(root / relative, target)

path = root / 'opencode.json'
config = json.loads(path.read_text(encoding='utf-8-sig'))
for name in ('build', 'drone_build', 'drone_read'):
    permissions = config['agents'][name]['permissions']
    assert not any(p.get('action') == 'localcoder_failure_lookup' for p in permissions)
    permissions.append({'action': 'localcoder_failure_lookup', 'resource': '*', 'effect': 'allow'})
path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

path = root / '.opencode/plugins/localcoder-drone-assignment-gate.ts'
text = path.read_text(encoding='utf-8')
old = '"read", "glob", "grep", "search", "skill", "localcoder_status", "localcoder_memory_read",'
assert text.count(old) == 1
path.write_text(text.replace(old, old + '\n  "localcoder_failure_lookup",'), encoding='utf-8')

path = root / 'AGENTS.md'
text = path.read_text(encoding='utf-8')
text += '\n## Receipt failure evidence\n\nFor recurring receipt-audit failures, use `localcoder_failure_lookup` to retrieve observed cases, saved output, source hashes, and current recorded results. Historical failures are not current failures. Empty output records no cause; an empty `current_results` records no verification for the current source. These records do not grant permission, admit code, or prove model learning.\n'
path.write_text(text, encoding='utf-8')

target = root / '.opencode/plugins/localcoder-failure-lookup.ts'
assert not target.exists(), 'Preserve any existing live plugin before replacing it'
shutil.copy2(evidence / 'localcoder-failure-lookup.candidate.ts', target)
print('Integrated reviewed failure lookup; previous configuration preserved')
