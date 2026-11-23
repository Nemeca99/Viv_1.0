"""Seal this bounded release's evidence and append its operational handoff."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('L:/LocalCoder')

def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8-sig'))

def main():
    audit = read_json('.opencode/evals/completion-release-audit.json')
    assert audit['result'] == 'PASS' and all(audit['checks'].values())
    for relative in (audit['live_evidence'], audit['native_evidence']):
        assert read_json(relative)['result'] == 'PASS'
    logs = [
        '.opencode/evals/completion-task-binding-final.txt',
        '.opencode/evals/completion-hooks-final.txt',
        '.opencode/evals/completion-continuity-regression-final.txt',
    ]
    for relative in logs:
        assert 'PASS:' in (ROOT / relative).read_text(encoding='utf-8-sig')
    reload_log = '.opencode/evals/completion-live-reload-20261118.txt'
    assert 'Configuration reloaded' in (ROOT / reload_log).read_text(encoding='utf-8-sig')
    build_log = '.opencode/evals/completion-frozen-final-build.log'
    assert '10 passed; 0 failed' in (ROOT / build_log).read_text(encoding='utf-8-sig')
    source_root = 'workspace/autonomy/aios_router_mcp_v3_postal_candidate/'
    sources = [source_root + item for item in (
        'Cargo.toml', 'Cargo.lock', 'src/completion.rs', 'src/continuity.rs',
        'src/lib.rs', 'src/main.rs', 'src/postal.rs',
        'completion_authority.py', 'continuity_client.py',
    )] + [
        'workspace/autonomy/privacy_core_router_db_gate_queen_v1_candidate.py',
        '.opencode/lib/completion.mjs', '.opencode/lib/task-binding.mjs',
        '.opencode/lib/continuity.mjs',
        '.opencode/plugins/lmstudio-toolbridge.ts',
        '.opencode/plugins/localcoder-drone-assignment-gate.ts',
        '.opencode/plugins/architect-body-gate.ts',
        '.opencode/completion.json', '.opencode/continuity.json',
        '.opencode/staging/continuity.Dockerfile',
        'opencode.json', 'AGENTS.md', '.opencode/COMPLETION_VERIFIER.md',
    ]
    evidence = [
        '.opencode/evals/completion-release-audit.json', audit['live_evidence'],
        audit['native_evidence'], '.opencode/evals/completion-wikipedia-regression.json',
        '.opencode/receipts/' + audit['body_receipt'], build_log, reload_log,
    ] + logs
    now = datetime.now(timezone.utc)
    stamp = now.strftime('%Y%m%dT%H%M%SZ')
    receipt_relative = '.opencode/receipts/completion-release-' + stamp + '.json'
    receipt = {
        'kind': 'bounded_release_evidence_manifest', 'timestamp': now.isoformat(),
        'result': 'PASS', 'task_id': audit['task_id'], 'image': audit['image'],
        'verification_sha256': audit['verification_sha256'],
        'scope': 'Frozen-criteria completion verification through actual local OpenCode and Rust MCP',
        'limits': 'Declared checks and tracked files only; no model learning or general reliability claim',
        'files': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources + evidence},
    }
    receipt_path = ROOT / receipt_relative
    with receipt_path.open('x', encoding='utf-8', newline='\n') as output:
        output.write(json.dumps(receipt, indent=2) + '\n')
    receipt_hash = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    statement = (
        f"{now.isoformat()} Completion verifier release PASS. Rust owns frozen criteria, actual isolated "
        "checks, hashes and completion state; OpenCode relays trusted bindings/results; the local model "
        "reasons and proposes code. Ten Rust tests, the native negative/recovery lifecycle, full real "
        "OpenCode lane, final release audit and three frontend/continuity regression suites passed. "
        "Prose-only success, nonzero exits, stale artifacts and rewritten check inputs were rejected; "
        "failed verification required a fresh proof after restoration. Shared OpenCode reload exited 0 "
        "with Configuration reloaded. Earlier failures, snapshots and receipts remain preserved. "
        f"Evidence: {receipt_relative}; SHA256 {receipt_hash}. "
        "No training or scheduled jobs were enabled. Verification covers declared criteria and tracked files."
    )
    for relative in ('.opencode/STM.md', 'BUILD_LOG.md'):
        with (ROOT / relative).open('a', encoding='utf-8', newline='\n') as output:
            output.write('\n- ' + statement + '\n')
    summary_relative = '.opencode/session_summaries/' + stamp + '-rust-completion-verifier.md'
    handoff = (
        '# Rust completion verifier\n\n' + statement + '\n\n'
        'Current operator guide: `.opencode/COMPLETION_VERIFIER.md`. '
        'Release audit: `.opencode/evals/completion-release-audit.json`. '
        'The current image is `' + audit['image'] + '`. '
        'Build assignments need one frozen `Acceptance JSON:` contract, artifacts and declared verification inputs. '
        'The existing MCP exposes acceptance-contract reads and re-verification. '
        'Compaction/STM/LTM behavior remains covered by its regression suite. '
        'The shared runtime was reloaded after the full live test. '
        'No further engineering, inference or learning job is pending from this assignment.\n'
    )
    with (ROOT / summary_relative).open('x', encoding='utf-8', newline='\n') as output:
        output.write(handoff)
    print(json.dumps({'result': 'PASS', 'receipt': receipt_relative, 'sha256': receipt_hash,
                      'summary': summary_relative, 'hashed_files': len(receipt['files'])}))

if __name__ == '__main__':
    main()
