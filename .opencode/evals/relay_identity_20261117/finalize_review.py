import hashlib
import json
from pathlib import Path

root = Path('L:/LocalCoder')
out = root / '.opencode/evals/relay_identity_20261117'
path = out / 'review_receipt.json'
record = json.loads(path.read_text())
events = [json.loads(line) for line in (out / 'drone_final_check.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.startswith('{')]
shells = [e['part']['state'] for e in events if e.get('type') == 'tool_use' and e['part']['tool'] == 'shell']
assert len(shells) == 1 and shells[0]['status'] == 'completed'
assert shells[0]['output'].strip() == 'PASS: 8 checks'
assert shells[0]['metadata']['metadata']['exit'] == 0
summary = root / '.opencode/session_summaries/20261117-relay-identity-supervision.md'
record['live_self_check'] = {'output': shells[0]['output'].strip(), 'exit': 0, 'raw': str(out / 'drone_final_check.jsonl')}
record['handoff'] = {'path': str(summary), 'sha256': hashlib.sha256(summary.read_bytes()).hexdigest(), 'review': 'Viv authored; Codex corrected draft provenance and added candidate/history boundary. Original retained as handoff_drone.md.'}
assert hashlib.sha256((root / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py').read_bytes()).hexdigest() == record['source_sha256']
path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
with (root / 'BUILD_LOG.md').open('a', encoding='utf-8') as handle:
    handle.write('\n- Same-session final check: Viv executed the repaired audit CLI, exit 0, `PASS: 8 checks`, then wrote and read the handoff. Queen retained the original summary and corrected its draft-provenance wording and candidate/history boundary. Final hashes and raw output are in the review receipt.\n')
print('Recorded fresh same-session self-check and reviewed handoff')
