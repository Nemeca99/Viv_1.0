"""Replay a rejected INN candidate and its admitted parent with action traces."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

from autonomy.inn_candidate_lease import InnCandidateLease, LeaseAwareRuntimeGuard
from autonomy.train_neural_inn import LEARNING, digest, frozen_probe, language_probe
from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard


def first_action_divergence(parent_trace, candidate_trace):
    differences = 0
    first = None
    outcome_differences = 0
    first_outcome = None
    state_differences = 0
    first_state = None
    for index, (parent, candidate) in enumerate(zip(parent_trace, candidate_trace)):
        parent_action = parent['action']
        candidate_action = candidate['action']
        parent_identity = tuple(parent_action.get(key) for key in ('t', 'a', 'b'))
        candidate_identity = tuple(candidate_action.get(key) for key in ('t', 'a', 'b'))
        if parent_identity != candidate_identity:
            differences += 1
            if first is None:
                first = {'index': index, 'step': parent['step'],
                         'parent_action': parent_action, 'candidate_action': candidate_action,
                         'parent_outcome': parent['outcome'], 'candidate_outcome': candidate['outcome']}
        if parent['outcome'] != candidate['outcome']:
            outcome_differences += 1
            if first_outcome is None:
                first_outcome = {'index': index, 'step': parent['step'],
                                 'parent_outcome': parent['outcome'],
                                 'candidate_outcome': candidate['outcome']}
        if parent['state'] != candidate['state']:
            state_differences += 1
            if first_state is None:
                first_state = {'index': index, 'step': parent['step'],
                               'parent_state': parent['state'], 'candidate_state': candidate['state']}
    if len(parent_trace) != len(candidate_trace):
        differences += abs(len(parent_trace) - len(candidate_trace))
        if first is None:
            first = {'index': min(len(parent_trace), len(candidate_trace)),
                     'parent_trace_length': len(parent_trace),
                     'candidate_trace_length': len(candidate_trace)}
    return {'action_identity_differences': differences, 'first_divergence': first,
            'outcome_differences': outcome_differences, 'first_outcome_divergence': first_outcome,
            'state_differences': state_differences, 'first_state_divergence': first_state}


def persist_trace(lease, path, seed, case, metrics, trace):
    payload = {'schema': 'inn_neural_probe_trace_v1', 'seed': seed,
               'steps': case['steps'], 'farm_config': case.get('farm_config') or {},
               'metrics': metrics, 'trace': trace}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
    lease.write_artifact(path, encoded)
    return hashlib.sha256(encoded).hexdigest()


def main():
    from autonomy.train_neural_inn import _load_training_stack
    from inn.language import LanguageEngine

    candidate_pointer = json.loads((LEARNING / 'neural_candidate.json').read_text())
    admitted_pointer = json.loads((LEARNING / 'neural_admitted.json').read_text())
    candidate_run = Path(candidate_pointer['run'])
    parent_run = Path(admitted_pointer['run'])
    candidate_eval_path = candidate_run / 'evaluation.json'
    candidate_manifest = json.loads((candidate_run / 'manifest.json').read_text())
    candidate_eval = json.loads(candidate_eval_path.read_text())
    protocol = candidate_eval['protocol']
    parent_data = json.loads((candidate_run / 'parent.json').read_text())
    parent_manifest = json.loads((parent_run / 'manifest.json').read_text())

    if candidate_pointer['passed'] or candidate_eval['passed']:
        raise ValueError('Diagnostic requires a rejected candidate')
    if candidate_pointer['run'] != str(candidate_run) or protocol.get('resume') != str(parent_run):
        raise ValueError('Candidate lineage does not match the current admitted parent')
    if candidate_pointer['engine_sha256'] != digest(candidate_run / 'engine.pt'):
        raise ValueError('Candidate checkpoint hash mismatch')
    if candidate_pointer['evaluation_sha256'] != digest(candidate_eval_path):
        raise ValueError('Candidate evaluation hash mismatch')
    if candidate_manifest['engine_sha256'] != candidate_pointer['engine_sha256']:
        raise ValueError('Candidate manifest hash mismatch')
    if admitted_pointer['engine_sha256'] != digest(parent_run / 'engine.pt'):
        raise ValueError('Admitted parent checkpoint hash mismatch')
    if parent_manifest['engine_sha256'] != admitted_pointer['engine_sha256']:
        raise ValueError('Admitted parent manifest hash mismatch')
    if protocol.get('parent_checkpoint_sha256') != admitted_pointer['engine_sha256']:
        raise ValueError('Candidate was not trained from the admitted parent checkpoint')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    diagnostic_run_id = f'diagnostic-{stamp}'
    runtime_guard = RuntimeBodyGuard(requested_threads=2, candidate_run_id=diagnostic_run_id)
    body_verdict = runtime_guard.check(force=True)
    source_paths = (
        Path(__file__).resolve(),
        Path(__file__).with_name('train_neural_inn.py'),
        WORKSPACE / 'autonomy' / 'inn_candidate_lease.py',
        WORKSPACE / 'aios_rebuild' / 'main_core' / 'mind_runtime_gate.py',
        WORKSPACE / 'aios_rebuild' / 'main_core' / 'body_runtime_client.py',
        WORKSPACE / 'INN' / 'inn' / 'language.py',
        WORKSPACE / 'INN' / 'inn' / 'transformer.py',
        WORKSPACE / 'INN' / 'inn' / 'farm.py',
        WORKSPACE / 'INN' / 'farm_rust' / 'target' / 'release' / 'inn_farm.dll',
        WORKSPACE / 'aios_rebuild' / 'local_security_core' / 'target' / 'debug' / 'security_core.dll',
    )
    diagnostic_lease = InnCandidateLease.begin(
        diagnostic_run_id, [digest(path) for path in source_paths],
        float(body_verdict['stability_sn']), body_verdict.pop('body_runtime_permit', None),
        body_verdict.get('requested_threads'))
    runtime_guard = LeaseAwareRuntimeGuard(runtime_guard, diagnostic_lease)
    body_evidence = dict(body_verdict)
    body_evidence.pop('body_runtime_permit', None)
    body_evidence['candidate_run_id'] = diagnostic_lease.run_id
    diagnostic_lease.write_json(diagnostic_lease.stage_root / 'body_gate.json', body_evidence)
    _load_training_stack()

    config = parent_data['config']
    candidate = LanguageEngine(copy.deepcopy(config), parent_data['engine'])
    candidate.load(candidate_run / 'engine.pt')
    parent = LanguageEngine(copy.deepcopy(config), parent_data['engine'])
    parent.load(parent_run / 'engine.pt')
    training_data = json.loads((candidate_run / 'training_data.json').read_text())['language']
    training_prompts = {example['prompt'] for example in training_data}
    heldout_examples = [{'prompt': row['prompt'], 'target': row['expected']}
                        for row in candidate_eval['language']['examples']]
    heldout_prompts = {example['prompt'] for example in heldout_examples}
    overlap = training_prompts & heldout_prompts
    if overlap:
        raise ValueError('Held-out language prompts overlap the training corpus')
    candidate_language = language_probe(candidate, heldout_examples, runtime_guard)
    if candidate_language != candidate_eval['language']:
        raise RuntimeError('Candidate language replay differs from recorded evaluation')
    parent_language = language_probe(parent, heldout_examples, runtime_guard)

    diagnostic_dir = diagnostic_lease.stage_root / 'diagnostics'
    final_diagnostic_dir = diagnostic_lease.final_root / 'diagnostics'
    seed_reports = []
    for index, case in enumerate(protocol['final']):
        candidate_trace_path = diagnostic_dir / f'seed-{case["seed"]}-candidate.json'
        parent_trace_path = diagnostic_dir / f'seed-{case["seed"]}-parent.json'
        candidate_trace = []
        parent_trace = []
        candidate_metrics = frozen_probe(candidate, config, **case,
                                         runtime_guard=runtime_guard, trace_sink=candidate_trace)
        parent_metrics = frozen_probe(parent, config, **case,
                                      runtime_guard=runtime_guard, trace_sink=parent_trace)
        recorded = candidate_eval['farm'][index]
        if candidate_metrics != recorded['candidate'] or parent_metrics != recorded['parent']:
            raise RuntimeError(f'Rust replay differs from recorded evaluation for seed {case["seed"]}')
        candidate_trace_hash = persist_trace(
            diagnostic_lease, candidate_trace_path, case['seed'], case, candidate_metrics, candidate_trace)
        parent_trace_hash = persist_trace(
            diagnostic_lease, parent_trace_path, case['seed'], case, parent_metrics, parent_trace)
        trace_comparison = first_action_divergence(parent_trace, candidate_trace)
        first_divergence = trace_comparison['first_divergence']
        decision_context = None
        case_regressed = (candidate_metrics['score'] < parent_metrics['score']
                          or candidate_metrics['decays'] > parent_metrics['decays']
                          or candidate_metrics['invalid'] > parent_metrics['invalid'])
        if first_divergence is not None and case_regressed:
            divergent_step = first_divergence['step']
            first_state_divergence = trace_comparison['first_state_divergence']
            context_end = (first_state_divergence['step'] if first_state_divergence
                           else divergent_step)
            detail_steps = set(range(divergent_step, context_end + 1))
            candidate_detail_path = diagnostic_dir / f'seed-{case["seed"]}-candidate-decision.json'
            parent_detail_path = diagnostic_dir / f'seed-{case["seed"]}-parent-decision.json'
            candidate_detail_trace = []
            parent_detail_trace = []
            detailed_candidate_metrics = frozen_probe(
                candidate, config, **case, detail_steps=detail_steps,
                runtime_guard=runtime_guard, trace_sink=candidate_detail_trace)
            detailed_parent_metrics = frozen_probe(
                parent, config, **case, detail_steps=detail_steps,
                runtime_guard=runtime_guard, trace_sink=parent_detail_trace)
            if detailed_candidate_metrics != candidate_metrics or detailed_parent_metrics != parent_metrics:
                raise RuntimeError(f'Detailed replay differs for seed {case["seed"]}')
            candidate_detail_hash = persist_trace(
                diagnostic_lease, candidate_detail_path, case['seed'], case,
                detailed_candidate_metrics, candidate_detail_trace)
            parent_detail_hash = persist_trace(
                diagnostic_lease, parent_detail_path, case['seed'], case,
                detailed_parent_metrics, parent_detail_trace)
            decision_context = {
                'start_step': divergent_step,
                'end_step': context_end,
                'rankings': [{
                    'step': step,
                    'parent_top_candidates': parent_detail_trace[step - 1].get('candidate_ranking', []),
                    'candidate_top_candidates': candidate_detail_trace[step - 1].get('candidate_ranking', []),
                } for step in sorted(detail_steps)],
                'parent_trace_sha256': parent_detail_hash,
                'candidate_trace_sha256': candidate_detail_hash,
            }
        seed_reports.append({
            'seed': case['seed'],
            'metrics_match_recorded_evaluation': True,
            'candidate_metrics': candidate_metrics,
            'parent_metrics': parent_metrics,
            'trace_comparison': trace_comparison,
            'first_divergence_decision_context': decision_context,
            'candidate_trace_sha256': candidate_trace_hash,
            'parent_trace_sha256': parent_trace_hash,
            'candidate_trace_path': str(final_diagnostic_dir / candidate_trace_path.name),
            'parent_trace_path': str(final_diagnostic_dir / parent_trace_path.name),
        })

    receipt = {
        'schema': 'inn_failed_candidate_diagnostic_v1',
        'at_utc': datetime.now(timezone.utc).isoformat(),
        'diagnostic_run': str(diagnostic_lease.final_root),
        'candidate_run': str(candidate_run),
        'candidate_sha256': candidate_pointer['engine_sha256'],
        'evaluation_sha256': candidate_pointer['evaluation_sha256'],
        'diagnostic_source_sha256': digest(Path(__file__).resolve()),
        'trainer_source_sha256': digest(Path(__file__).with_name('train_neural_inn.py')),
        'rust_farm_sha256': digest(Path(__file__).parents[1] / 'INN' / 'farm_rust' / 'target' / 'release' / 'inn_farm.dll'),
        'admitted_parent_run': str(parent_run),
        'admitted_parent_sha256': admitted_pointer['engine_sha256'],
        'language_comparison': {
            'heldout_prompt_count': len(heldout_examples),
            'training_prompt_overlap': len(overlap),
            'candidate_exact': candidate_language['exact'],
            'candidate_accuracy': candidate_language['accuracy'],
            'parent_exact': parent_language['exact'],
            'parent_accuracy': parent_language['accuracy'],
            'exact_accuracy_delta': candidate_language['accuracy'] - parent_language['accuracy'],
            'candidate_examples': candidate_language['examples'],
            'parent_examples': parent_language['examples'],
        },
        'replay_matches_recorded_evaluation': True,
        'active_policy_changed': False,
        'seed_reports': seed_reports,
    }
    receipt_path = diagnostic_lease.stage_root / 'diagnosis.json'
    diagnostic_lease.write_json(receipt_path, receipt)
    final_root = diagnostic_lease.commit()
    final_receipt = final_root / 'diagnosis.json'
    print(json.dumps({'diagnosis': str(final_receipt), 'sha256': digest(final_receipt),
                      'language_comparison': receipt['language_comparison'],
                      'seed_reports': seed_reports}), flush=True)


if __name__ == '__main__':
    main()
