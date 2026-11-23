"""Record actual supervised implementation provenance and live evidence."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path('L:/LocalCoder')
evidence = root / '.opencode/evals/failure_lookup_20261117'
session = 'ses_e17e97865ffeqBHUup02dTc68O'
events = [json.loads(line) for line in (evidence / 'drone_live.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.startswith('{')]
calls = [e['part'] for e in events if e.get('type') == 'tool_use']
lookup = [p for p in calls if p['tool'] == 'localcoder_failure_lookup']
assert len(lookup) == 1 and lookup[0]['state']['status'] == 'completed'
result = json.loads(lookup[0]['state']['output'])
assert result['total_matches'] == 2
assert all(not row['source_matches_current'] for row in result['failures'])
assert result['current_results'][0]['passed'] == result['current_results'][0]['cases'] == 53
body_path = root / '.opencode/receipts/1794902764619-99dcbfd9-e5e2-4c2c-ad93-9ddf4a932987-body-gate.json'
body = json.loads(body_path.read_text())
assert body['allowed'] is True and body['source'] == 'tool:localcoder_failure_lookup' and body['session_id'] == session
before = json.loads((evidence / 'before_integration/opencode.json').read_text(encoding='utf-8-sig'))
after = json.loads((root / 'opencode.json').read_text(encoding='utf-8-sig'))
assert before.get('provider') == after.get('provider')
assert before.get('model') == after.get('model')
for agent in before['agents']:
    for key, value in before['agents'][agent].items():
        if key != 'permissions':
            assert after['agents'][agent][key] == value, (agent, key)
files = [
 'workspace/autonomy/receipt_failure_lookup_candidate.py',
 '.opencode/plugins/localcoder-failure-lookup.ts',
 '.opencode/plugins/localcoder-drone-assignment-gate.ts',
 '.opencode/plugins/lmstudio-toolbridge.ts',
 'opencode.json', 'AGENTS.md',
 '.opencode/evals/failure_lookup_20261117/verify_validation.py',
 '.opencode/evals/failure_lookup_20261117/verify_core.py',
 '.opencode/evals/failure_lookup_20261117/verify_cli.py',
 '.opencode/evals/failure_lookup_20261117/verify_tool.mjs',
]
receipt = {
 'schema': 'localcoder_supervised_failure_lookup_review_v1',
 'captured_at': datetime.now(timezone.utc).isoformat(),
 'session_id': session,
 'result': 'live_lookup_verified',
 'authorship': {
   'viv_drone': 'Validator, lookup function, CLI proposal, and TS adapter drafts; visible tool calls retained.',
   'codex_queen': 'Frozen independent checks, review, repairs, workflow integration, and final verification.',
 },
 'supervisor_repairs': [
   'Strict record types, validator API, missing imports and hash helper references.',
   'CLI defaults and argument parsing; preserved rejected patch proposal.',
   'V2 adapter registration, exec import, argv, fixed Python path, input validation and schema guard.',
   'New-assignment inspection-budget reset and explicit task-access mode in gate and bridge.',
 ],
 'checks': [
   '37 validation cases; inputs unchanged',
   '7 lookup behavior groups; real receipts unchanged',
   'CLI filtering, bounds and missing-root errors; real inputs unchanged',
   'Tool registration, literal argv, input bounds and error propagation',
   '7 normal-conversation hook groups, 9 capability checks, 14 task-mode cases',
   'Live same-session seed lookup -> localcoder_failure_lookup -> one ordinary final reply',
 ],
 'live_result': result,
 'body_receipt': str(body_path),
 'failed_attempts_preserved': ['validator_attempt1.py', 'lookup_attempt1.py', 'tool_attempt1.ts', 'tool_attempt2.ts', 'cli_rejected_proposal.json', 'drone_*.jsonl'],
 'inference_configuration_unchanged': True,
 'limitations': [
   'Saved current-source result is recorded evidence, not a fresh execution by the lookup.',
   'Viv incorrectly called old failures unreproducible; supervisor corrected that in the same session.',
   'Retrieval does not train model weights or admit new learned facts.',
   'Fixed local paths and validation are not OS confinement against concurrent junction replacement.',
 ],
 'sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in files},
}
(evidence / 'review_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
entry = '''
## Entry: 2026-11-17 — [Viv/Drone + QUEEN/Codex] Supervised failure-evidence lookup

- Architect directed Codex to set bounded goals, let Viv author changes, review and repair them, and give feedback in the same OpenCode session `ses_e17e97865ffeqBHUup02dTc68O`.
- Viv drafted `workspace/autonomy/receipt_failure_lookup_candidate.py` and its TypeScript adapter. Queen froze independent checks and repaired validator API/type errors, unresolved dependencies, CLI defaults/argv parsing, and V2 adapter registration/import/argv/input validation. Failed drafts and rejected tool proposals are retained rather than counted as successes.
- Connected `localcoder_failure_lookup` through `.opencode/plugins/localcoder-failure-lookup.ts`, three agent permission lists, and the conversation tool allowlist. Lookup reads existing result JSON only, includes raw-document/source SHA-256, uses exact case matching, and separates historical failures from saved current-source results. No learned-memory/SQLite write, model reload, training, or daemon was introduced.
- Corrected an old inspection-budget carryover into new assignments. Explicit `Task access: read|write` supports supervised assignments without treating historical prose as the current access mode. Existing Body, PrivacyCore, tool-order, and C-drive checks remain. Isolated mode checks pass; no claim that every possible serialized-history classification is solved.
- Verification passed: 37 validator cases, 7 lookup behavior groups, CLI/error tests, adapter registration/argv/input/error tests; 7 normal-conversation groups, 9 capability boundary checks, and 14 task-mode checks. Real receipt inputs stayed unchanged. Provider, model, and non-permission agent settings compare unchanged to the integration snapshot.
- Live verification: Rust Body allowed `tool:localcoder_failure_lookup`; Viv called `{case:"valid",limit:2}` and received two historical failure rows plus the saved current audit result of 53/53 for source `0792aa952751ed4c588e612c9789afed3ee21b50e5b1fcc7fbab3ae4608f39f7`. One ordinary final reply, no verbose self-prompt ritual. Her claim that old failures were unreproducible exceeded the record; Queen corrected this in-session. Empty saved output records no cause. Lookup does not rerun the audit or train weights.
- Evidence, snapshots, contracts, raw chat, frozen checks, hashes and review receipt: `.opencode/evals/failure_lookup_20261117/`. Integration remains a supervised candidate workflow; path checks do not establish OS-level isolation.
'''
with (root / 'BUILD_LOG.md').open('a', encoding='utf-8') as handle:
    handle.write('\n' + entry)
print('Recorded live verification, source hashes, provenance, limits, and BUILD_LOG entry')
