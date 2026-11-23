"""Capture successful checks, exact change scope, and supervised authorship."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path('L:/LocalCoder')
out = root / '.opencode/evals/relay_identity_20261117'
source = root / 'workspace/autonomy/typed_composition_receipt_audit_v2_candidate.py'
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
source_hash = digest(source)
before = (out / 'audit_before.py').read_text(encoding='utf-8')
after = source.read_text(encoding='utf-8')
start = '            # Recompute relay_key'
end = '        # Check that provider_output_type equals consumer_input_type'
assert before.split(start)[0] == after.split(start)[0]
assert before.split(end)[1].rstrip('\r\n') == after.split(end)[1].rstrip('\r\n')
checks = {
 '.opencode/evals/verify_receipt_flags_20261117.py': 'e61ad08e67675ee3904fb7ec029290393b7f1e4f86db9370998c3a17912e0c05',
 '.opencode/evals/verify_relay_identity_20261117.py': '99ff7ec69a00f3b48f58a41a191d2475e6f22e0be28c1d106ef43f883c195efb',
}
for path, expected in checks.items():
    assert digest(root / path) == expected, path
relay = json.loads((out / ('result_' + source_hash[:16] + '.json')).read_text())
flags = json.loads((root / '.opencode/evals/receipt_flags_20261117' / ('result_' + source_hash[:16] + '.json')).read_text())
assert relay['cases'] == relay['passed'] == 11 and relay['db_unchanged'] is True
assert flags['cases'] == flags['passed'] == 53 and flags['db_unchanged'] is True
record = {
 'schema': 'localcoder_supervised_relay_identity_review_v1',
 'captured_at': datetime.now(timezone.utc).isoformat(),
 'session_id': 'ses_e17e97865ffeqBHUup02dTc68O',
 'source_sha256': source_hash,
 'checker_sha256': checks,
 'relay_identity_checks': relay,
 'state_flag_regression': flags,
 'scope_verified': 'Only the relay key and database evidence binding block changed, plus a final newline added by the patch transport.',
 'baseline': '2/11; nine resealed tampered edges were wrongly accepted.',
 'failed_drone_drafts': ['audit_drone_attempt1.py', 'audit_drone_attempt2.py', 'drone_attempt1.jsonl', 'drone_attempt2.jsonl'],
 'authorship': 'Viv authored the binding patch through localcoder_patch. Codex froze probes, supplied review corrections, then fixed one remaining comparison: computed payload digest must equal claimed key, not its rehash. See raw same-session attempts for exact provenance.',
 'limits': 'Candidate receipt auditor only; not a new circuit execution, model learning, or promotion.',
}
(out / 'review_receipt.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
entry = f'''
## Entry: 2026-11-17 — [Viv/Drone + QUEEN/Codex] Bind composition relay identities

- Architect continued supervised work in the existing OpenCode session. Queen reproduced a Check 7 defect: the auditor hashed the relay-key string instead of its payload and never compared the result. Resealing forged keys or altered metadata bypassed the audit: baseline 2/11, with nine false accepts.
- Viv's first patch failed (2/11), introducing unsupported sqlite3.Row.get and retaining incorrect hashing. Queen preserved it and supplied focused corrections. Her second patch reached 9/11; Queen corrected one remaining comparison (payload digest equals claimed key, rather than rehashing the key). Both failed drafts and raw same-session traces are retained.
- Final source SHA-256: `{source_hash}`. Scope comparison confirms that only the relay-key/database-evidence binding block changed, plus a final newline added by patch transport. Both independent checkers retain their frozen hashes.
- Verified: 11/11 identity cases (including valid and reordered valid edges) and 53/53 flag regressions; real candidate database unchanged. Forged keys and fully resealed edges absent from the recorded database evidence are rejected.
- Evidence/provenance: `.opencode/evals/relay_identity_20261117/review_receipt.json` and raw same-session outputs. No model settings, Rust source, learned memory, training, or daemon changes. This is a candidate audit repair, not a new circuit or learning result.
'''
with (root / 'BUILD_LOG.md').open('a', encoding='utf-8') as handle:
    handle.write('\n' + entry)
print('Recorded 11/11 relay checks, 53/53 regressions, frozen hashes, and exact scope')
