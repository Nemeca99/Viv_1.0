"""Seal the three verified milestones using source-bound and live receipts."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path('L:/LocalCoder')
out = root / '.opencode/evals/supervision_chain_20261117'
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
audit = root / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
runner = root / 'workspace/autonomy/run_composition_audit_regressions_candidate.py'
source_hash = digest(audit)
assert source_hash == 'f5a85a1b32fc238d86b06d878bcaee2f692f1045f08240003b41b20c3fcb54c4'
assert digest(runner) == '2db399f396c8aedd289c8af97b0ce029f713331699ae7954651c14eaa75caf74'
frozen = json.loads((out / 'frozen_checkers.json').read_text())
assert all(digest(root / path) == expected for path, expected in frozen.items())
events = [json.loads(line) for line in (out / 'drone_final_verification.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.startswith('{')]
shells = [event['part']['state'] for event in events if event.get('type') == 'tool_use' and event['part']['tool'] == 'shell']
assert len(shells) == 1 and shells[0]['status'] == 'completed'
assert shells[0]['metadata']['metadata']['exit'] == 0
receipt_path = Path(shells[0]['output'].strip().removeprefix('PASS: '))
assert receipt_path.is_relative_to(root / '.opencode/evals/composition_regression_runs')
live = json.loads(receipt_path.read_text())
assert live['ok'] is True and live['source_sha256'] == source_hash
assert live['source_unchanged'] is True and live['database_unchanged'] is True
assert len(live['suites']) == 4 and sum(row['cases'] for row in live['suites']) == 131
assert all(row['ok'] is True and row['passed'] == row['cases'] for row in live['suites'])
controls = [json.loads(path.read_text()) for path in (out / 'workflow_checks').glob('*/result.json')]
assert len(controls) == 1 and controls[0]['passed'] is True and len(controls[0]['checks']) == 6
before_agents = (out / 'AGENTS_before_runner_note.md').read_text(encoding='utf-8').rstrip()
after_agents = (root / 'AGENTS.md').read_text(encoding='utf-8').rstrip()
assert after_agents.startswith(before_agents), 'Preserve existing instructions'
assert 'run_composition_audit_regressions_candidate.py' in after_agents[len(before_agents):]
summary = root / '.opencode/session_summaries/20261117-supervised-goal-chain.md'
assert summary.is_file()
chain = json.loads((out / 'chain.json').read_text())
chain['milestones'][2].update(status='verified', checks='131/131 fresh cases plus six independent workflow controls',
    live_receipt=str(receipt_path), review='Viv authored suite list, streaming hash helper and result validator; Queen corrected strict types, repaired runner orchestration and added the usage note after Viv exact-match failure.')
chain.update(completed_at=datetime.now(timezone.utc).isoformat(), result='three_linked_milestones_verified')
(out / 'chain.json').write_text(json.dumps(chain, indent=2) + '\n')
paths = [audit, runner, root/'AGENTS.md', summary,
         root/'workspace/autonomy/composition_node_identity_candidate.py',
         root/'workspace/autonomy/composition_suite_result_candidate.py']
record = {'schema': 'localcoder_supervised_goal_chain_review_v1', 'chain': chain,
          'live_receipt': str(receipt_path), 'live_result': live, 'workflow_controls': controls[0],
          'checker_hashes': frozen, 'sha256': {str(path): digest(path) for path in paths},
          'authorship': 'Viv authored bounded drafts and pure helpers. Queen froze independent probes, rejected broken drafts, restored verified relay logic, corrected types, and supplied database/runner integration. Raw same-session traces retain exact provenance.',
          'failed_attempts_preserved': ['node_gates_drone_attempt1.py','node_gates_drone_attempt2.py','circuit_identity_drone_attempt1.py','node_comparator_drone.py','regression_runner_drone_attempt1.py','suite_validator_drone.py'],
          'limits': 'Candidate audit/workflow verification only; not a new circuit execution, learned weights, promotion or 24/7 daemon.'}
(out / 'review_receipt.json').write_text(json.dumps(record, indent=2) + '\n')
entry = f'''
## Entry: 2026-11-17 — [Viv/Drone + QUEEN/Codex] Three linked supervised goals

- Architect requested chained goals with Viv doing bounded changes and Queen reviewing in the same session `ses_e17e97865ffeqBHUup02dTc68O`. Planning/evidence chain: `.opencode/evals/supervision_chain_20261117/chain.json`; this is not a replacement for Rust runtime task authority.
- Goal 1: node-gate validation. Baseline 3/32; denied/malformed gates could pass or crash. Viv authored validation guards. First draft reached 30/32; second removed status/output checks. Queen preserved both and restored those checks. Verified 32/32 plus previous 64 cases.
- Goal 2: circuit/node/entry identity. Baseline 3/35; invented metadata and dependency ordering were accepted. Large Drone draft failed parsing and removed relay code; Queen retained it and restored the verified parent. Viv then authored a pure comparator. Queen corrected two strict-type checks, copied that function into the audit and added read-only SQL/version/endpoint/order binding. All 35 new cases pass; aggregate 131/131. Actual stored-version task IDs remain distinct from requested curriculum task IDs.
- Goal 3: repeatable regression command `L:/.venv/Scripts/python.exe -B L:/LocalCoder/workspace/autonomy/run_composition_audit_regressions_candidate.py`. Rejected full Drone runner retained without execution. Queen kept Viv's fixed suite list, streaming hash helper and result validator, corrected integer/bool checks, and repaired root/manifest/import/output/logging/failure/integrity handling. Frozen checker bytes are unchanged; every run gets a new UUID evidence directory.
- Six independent workflow controls pass: strict result types, reject checker changes before imports, reject false success and stop at first failure, detect database mutation despite passing suite claims (isolated fixture only), refuse -O, and preserve previous evidence while completing another 131-case run. Real source and candidate database stayed unchanged.
- Viv's AGENTS patch failed its exact-text match and changed nothing; Queen added the usage note. Viv then ran the reviewed command through live tool gates, wrote/read the handoff, and reported its actual result. Fresh live receipt: `{receipt_path}`. Final source SHA-256 `{source_hash}`. All failed drafts and raw chats are retained.
- Full hashes, authorship, controls, chain, and live results: `.opencode/evals/supervision_chain_20261117/review_receipt.json`. No inference settings, learned-store writes, promotion, schedules or daemons were introduced. Verification remains scoped to this candidate audit and four frozen fixture suites.
'''
with (root / 'BUILD_LOG.md').open('a', encoding='utf-8') as handle:
    handle.write('\n' + entry)
print('Sealed three linked goals; fresh live 131-case run and six workflow controls verified')
