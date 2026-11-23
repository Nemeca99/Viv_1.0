"""Persist current, scoped readiness evidence; never claim learning from setup."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

root = Path('L:/LocalCoder')
out = root / '.opencode/evals/measured_learning_20261117'
target = root / 'workspace/autonomy/terminal_neuron_learning.py'
tree = ast.parse(target.read_text(encoding='utf-8'))
selector = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'next_autonomous_lesson')
parent = root / 'workspace/autonomy/learning/neural_runs/language-routes-20261109T063634670033Z'
record = json.loads((parent / 'learning.json').read_text(encoding='utf-8'))
digests = {name: hashlib.sha256((parent/name).read_bytes()).hexdigest() for name in ('neuron_graph.sqlite3','curriculum.sqlite3')}
assert all(value == record['snapshot_hashes'][name] for name,value in digests.items())
report = {
 'schema': 'viv_measured_learning_readiness_v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
 'objective': 'Continue supervising viv and guide her to work autonomously. End goal, real measured self improvement and learning.',
 'goal_complete': False,
 'turn_classification': 'progress',
 'progress': ['Removed post-commit automatic move/delete from native learner; frozen AST check proves all other logic unchanged.',
              'Current WSL Rust Body preflight observed ALLOW_MIND_RUNTIME, stability 1.0, all 19 cores bound.',
              'Located verified parent and exposed missing native dependency plus unimplemented autonomous lesson selector.'],
 'source_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
 'verified_parent': str(parent), 'parent_snapshot_hashes': digests,
 'parent_input': record['input'], 'parent_counts_before': record['counts_before'], 'parent_counts_after': record['counts_after'],
 'parent_reloaded_recall': record.get('reloaded_recall'),
 'parent_evidence_limit': 'Retained recall and equal graph counts do not by themselves prove new learning or measured gain; weights not compared here.',
 'nn_local_spec': str(importlib.util.find_spec('nn_local')),
 'configured_native_root_exists': Path('L:/Standalone/NN').exists(),
 'lesson_selector': ast.get_source_segment(target.read_text(encoding='utf-8'), selector),
 'new_learning_this_turn': 'Not yet executed; restore the exact substrate and prove eligibility before candidate training.',
 'source_admission_findings': ['VERIFIED queue status is insufficient; current category-tag gate can admit false relations.',
                               'Galjoen fish source inspected as a possible bounded observed-route lesson, not yet taught.'],
 'next': ['Locate complete original nn_local source and verify compatibility.',
          'Restore dependencies reversibly without replacing architecture.',
          'Run a novel source-reviewed bounded lesson with before samples, persisted deltas and fresh-instance recall.',
          'Repair source-backed autonomous lesson selection, then measure repeated cycles and held-out transfer.'],
}
(out/'readiness.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
with (root/'BUILD_LOG.md').open('a',encoding='utf-8') as handle:
    handle.write('\n## Entry: 2026-11-17 — [QUEEN/Codex + Viv/Drone] Real-learning readiness\n\n'
      '- Active objective remains autonomous measured self-improvement, not audit-only completion. Current WSL Rust preflight allowed runtime with 19 cores.\n'
      '- Native learner contained post-commit history moves and deletion; Viv patch failed and proposed deleting lease.commit too. Queen removed only retention cleanup, preserving commit; frozen AST comparison and parse passed. No history/data was moved or deleted.\n'
      '- Latest intact parent language-routes-20261109T063634670033Z has hash-verified snapshots and retained recall; equal graph counts do not establish new learning.\n'
      '- Current nn_local dependency is missing and next_autonomous_lesson is a None stub. Complete native source restoration is being investigated; partial Aug source archive must not replace the native NN.\n'
      '- Existing Wikipedia VERIFIED rows can contain false category relations; no blind factual admission or training was started. A source-reviewed novel lesson is pending substrate restoration.\n'
      '- Current evidence and remaining full objective: .opencode/evals/measured_learning_20261117/readiness.json. Goal stays active.\n')
print('Recorded real-learning readiness and unresolved requirements; goal remains active')
