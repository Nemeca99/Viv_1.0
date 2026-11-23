"""Bounded CPU neural INN training with immutable parents and Rust-grounded text.

Validation is for selecting candidates. Final evaluation is a separate trajectory
and is recorded even on failure. This never changes the admitted live policy.
"""
from __future__ import annotations
import argparse
import copy
from collections import Counter
import hashlib
import io
import json
import math
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
VOICE_DIR = WORKSPACE / 'hive_voice'
sys.path.insert(0, str(WORKSPACE / 'INN'))
sys.path.insert(0, str(WORKSPACE))
for _thread_env in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    try:
        _thread_cap = max(1, min(4, int(os.environ.get(_thread_env, '4'))))
    except ValueError:
        _thread_cap = 4
    os.environ[_thread_env] = str(_thread_cap)
from autonomy.inn_hive import _atomic_json, _execution_request
from viv_autonomy import file_lock
from autonomy.farm_corpus import publish as publish_corpus, verify as verify_corpus
from autonomy.inn_candidate_lease import InnCandidateLease, LeaseAwareRuntimeGuard
from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold, RuntimeBodyGuard
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

LEARNING = WORKSPACE / 'autonomy' / 'learning'
STATUS = LEARNING / 'neural_status.json'
BODY_HOLD_RECEIPT_ROOT = WORKSPACE / 'aios_rebuild' / 'memory' / 'body_gate_holds' / 'inn_neural_training'
COUNTERFACTUAL_ROLLOUT_SEEDS = (812,)
COUNTERFACTUAL_EPSILON = 0.0


def _load_training_stack():
    global Farm, LanguageEngine, Simulation, StabilizedSourceEngine, TOOLS, torch
    import torch
    from inn.engine import Simulation, StabilizedSourceEngine, TOOLS
    from inn.farm import Farm
    from inn.language import LanguageEngine


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_candidate_pointer(lease, path, value):
    lease.publish_pointer(path, value)


def write_run_json(lease, path, value):
    lease.write_json(path, value)


def persist_body_gate(lease, run, verdict):
    evidence = dict(verdict)
    evidence.pop('body_runtime_permit', None)
    evidence['candidate_run_id'] = lease.run_id
    write_run_json(lease, Path(run) / 'body_gate.json', evidence)


def persist_body_hold(run, verdict):
    evidence = dict(verdict)
    evidence.pop('body_runtime_permit', None)
    receipt = {
        'schema': 'inn_neural_training_body_hold_v1',
        'run_id': Path(run).name,
        'stage': 'body_held',
        'active_policy_changed': False,
        'body_gate': evidence,
        'at_utc': datetime.now(timezone.utc).isoformat(),
    }
    target = BODY_HOLD_RECEIPT_ROOT / f'{Path(run).name}.json'
    PrivacyCore().write_text(
        target,
        json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n',
    )
    return target


def retention_after_failure(previous, parent_sha, current=.1):
    """Change one variable after a measured regression against this same parent."""
    receipt = previous.get('receipt') or {}
    protocol = receipt.get('protocol') or {}
    if (receipt.get('passed') is False and receipt.get('farm_retained') is False
            and protocol.get('parent_checkpoint_sha256') == parent_sha):
        return min(10., 2 * protocol.get('retention_weight', current))
    return current


def verifier_command(admit=False):
    command = [sys.executable, str(WORKSPACE / 'autonomy' / 'verify_neural_inn.py')]
    if admit:
        command.append('--admit')
    return command


class VoiceProgress:
    def __init__(self):
        voice_python = VOICE_DIR / '.venv' / 'Scripts' / 'python.exe'
        worker = VOICE_DIR / 'voice_progress_worker.py'
        if not voice_python.is_file() or not worker.is_file():
            raise FileNotFoundError('Hive voice progress worker is unavailable')
        environment = os.environ.copy()
        environment.update({key: '1' for key in
                            ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS')})
        self.process = subprocess.Popen(
            [str(voice_python), str(worker)], cwd=VOICE_DIR,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1, env=environment,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        ready = self.process.stdout.readline() if self.process.stdout else ''
        try:
            response = json.loads(ready)
        except json.JSONDecodeError as error:
            self.close()
            raise RuntimeError('Voice progress worker did not return READY') from error
        if response.get('status') != 'READY':
            self.close()
            raise RuntimeError('Voice progress worker did not return READY')

    def speak(self, text):
        if self.process.poll() is not None or self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError('Voice progress worker exited')
        self.process.stdin.write(json.dumps({'text': text}, ensure_ascii=False) + '\n')
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('Voice progress worker returned no receipt')
        response = json.loads(line)
        if response.get('status') == 'HOLD':
            raise BodyRuntimeHold(response.get('verdict', {
                'allowed': False, 'disposition': 'HOLD_MIND_RUNTIME',
                'authority': 'deterministic_aios_body_rust',
                'reasons': ['voice_progress_body_hold_receipt_invalid'],
            }))
        if response.get('status') != 'SPOKEN':
            print(json.dumps({'voice_progress': 'ERROR',
                              'reason': response.get('reason', 'invalid_worker_receipt')}),
                  flush=True)

    def close(self):
        process = getattr(self, 'process', None)
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.write(json.dumps({'command': 'stop'}) + '\n')
                process.stdin.flush()
                process.stdin.close()
            process.wait(timeout=180)
        except Exception:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def voice_progress_text(update, total_updates, validation=None):
    message = (f'INN drone training update {update} of {total_updates}. '
               'The candidate remains isolated; the Queen policy still controls execution.')
    if validation and validation.get('update') == update:
        language = validation['language']['accuracy']
        candidate_score = validation['farm']['score']
        parent_score = validation['parent']['score']
        message += (f' Interim exact language accuracy is {language:.0%}. '
                    f'Farm score is {candidate_score}; parent score is {parent_score}. '
                    'Final held-out evaluation is still pending.')
    return message


def voice_completion_text(receipt, admitted):
    outcome = 'passed' if receipt['passed'] else 'did not pass'
    disposition = 'was admitted' if admitted else 'remains isolated'
    improvement = 'yes' if receipt['farm_improved'] else 'no'
    return (f"INN drone training is complete. Held-out exact language accuracy was "
            f"{receipt['language']['accuracy']:.0%}. The candidate {outcome} its gates and {disposition}. "
            f"The farm strictly improved: {improvement}.")


def action_identity_group(sample):
    return tuple(sorted({int(item['a']) for item in sample['items'] if int(item['a']) > 0}))


def action_sampling_weights(samples):
    if not samples:
        raise ValueError('Action sample set is empty')
    counts = Counter(action_identity_group(sample) for sample in samples)
    return [1.0 / counts[action_identity_group(sample)] for sample in samples]


def center_counterfactual_scores(utilities, baseline_index):
    if not utilities:
        return None
    if not isinstance(baseline_index, int) or not 0 <= baseline_index < len(utilities):
        raise ValueError('Parent action index must identify a measured counterfactual')
    baseline_score = float(utilities[baseline_index][1])
    return [float(utility[1]) - baseline_score for utility in utilities]


def counterfactual_coverage(samples):
    measured = [sample for sample in samples if int(sample.get('oracle_horizon') or 0) > 0]
    improved = [sample for sample in measured if sample.get('oracle_improved')]
    horizons = Counter(int(sample['oracle_horizon']) for sample in measured)
    contexts = set()
    targets_by_tool = Counter()
    outcome_deltas = [float(value) for sample in measured
                      for value in sample.get('counterfactual_score_deltas', [])]
    trial_deltas = [float(value) for sample in measured
                    for action_trials in sample.get('counterfactual_score_trials', [])
                    for value in action_trials]
    advantages = [float(value) for sample in measured
                  for value in sample.get('counterfactual_score_advantages', [])]
    for sample in measured:
        context = [
            (item.get('t'), item.get('a'), item.get('b'), item.get('stage'), item.get('x'))
            for item in sample.get('items', [])
        ]
        contexts.add(json.dumps(context, sort_keys=True, separators=(',', ':')))
        best = sample.get('best')
        if sample.get('oracle_improved') and isinstance(best, int) and 0 <= best < len(sample.get('items', [])):
            targets_by_tool[str(sample['items'][best].get('t', 'unknown'))] += 1
    return {
        'total_action_samples': len(samples),
        'measured_counterfactual_samples': len(measured),
        'oracle_improved_samples': len(improved),
        'oracle_improvement_rate': len(improved) / len(measured) if measured else 0.0,
        'unique_model_contexts': len(contexts),
        'measured_action_outcomes': len(outcome_deltas),
        'measured_rollout_evaluations': len(trial_deltas),
        'score_delta_outcomes': {
            'negative': sum(value < 0 for value in outcome_deltas),
            'neutral': sum(value == 0 for value in outcome_deltas),
            'positive': sum(value > 0 for value in outcome_deltas),
        },
        'trial_score_delta_outcomes': {
            'negative': sum(value < 0 for value in trial_deltas),
            'neutral': sum(value == 0 for value in trial_deltas),
            'positive': sum(value > 0 for value in trial_deltas),
        },
        'parent_relative_advantages': {
            'negative': sum(value < 0 for value in advantages),
            'neutral': sum(value == 0 for value in advantages),
            'positive': sum(value > 0 for value in advantages),
        },
        'improved_targets_by_tool': dict(sorted(targets_by_tool.items())),
        'horizon_samples': {str(horizon): count for horizon, count in sorted(horizons.items())},
    }


def hive_simulation(farm, engine, state=None, seed=1):
    """Use the actual Hive single-action commitment and deterministic tie rule."""
    sim = Simulation(farm, engine, state, seed)
    sim.r['epsilon'] = 0.
    sim.r['rng'] = (seed & 0xffffffff) or 1
    sim.plan = lambda action: [action['t']]
    def choose(items, tick=None):
        allowed = [a for a in items if a['gate'] >= engine.config['threshold']]
        if not allowed:
            raise RuntimeError('No admitted action in Hive evaluation')
        return max(allowed, key=lambda a: (a['score'], a['t'], -a['a'], -a['b']))
    sim.choose = choose
    return sim


def frozen_probe(engine, config, steps, seed, farm_config=None, trace_path=None, detail_steps=None,
                 runtime_guard=None, trace_sink=None):
    frozen = copy.deepcopy(engine)
    frozen.config = dict(config, epsilonMin=0., epsilonStart=0.)
    frozen.learn = lambda *a, **k: None
    frozen.outcome = lambda *a, **k: None
    trace = []
    with Farm() as farm:
        state = farm.call('state')
        state['config'].update(farm_config or {})
        farm.call('load', state=state)
        sim = hive_simulation(farm, frozen, seed=seed)
        sim.r['epsilon'] = 0.
        for step_index in range(steps):
            if runtime_guard is not None:
                runtime_guard.check()
            result = sim.step()
            if trace_path is not None or trace_sink is not None:
                action = result['action']
                outcome = result['outcome']
                row = {
                    'step': step_index + 1,
                    'tick': result['tick'],
                    'action': {key: action.get(key) for key in
                               ('t', 'a', 'b', 'stage', 'x', 'raw', 'score', 'f1', 'f2', 'gate')},
                    'outcome': {key: outcome.get(key) for key in ('legal', 'executed', 'reward', 'note')},
                    'transition': result['transition'],
                    'state': {key: sim.r.get(key) for key in ('tick', 'harvests', 'decays', 'bank', 'invalid')},
                }
                if detail_steps and step_index + 1 in detail_steps:
                    row['candidate_ranking'] = [
                        {key: item.get(key) for key in
                         ('t', 'a', 'b', 'stage', 'x', 'raw', 'score', 'gate')}
                        for item in sim.last_candidates[:8]
                    ]
                trace.append(row)
        metrics = {k: sim.r[k] for k in ('harvests', 'decays', 'bank', 'invalid')} | {
            'score': sim.r['harvests'] - sim.r['decays'], 'steps': steps, 'seed': seed,
            'farm_config': farm_config or {}}
    trace_payload = {'schema': 'inn_neural_probe_trace_v1', 'seed': seed,
                     'steps': steps, 'farm_config': farm_config or {},
                     'metrics': metrics, 'trace': trace}
    if trace_path is not None:
        _atomic_json(trace_path, trace_payload)
    if trace_sink is not None:
        trace_sink.extend(trace)
    return metrics


def describe_prompt(item, plot):
    return f"plot={plot} stage={item['stage']} tool={item['t']}\nDescribe:\n"


def collect(parent, steps, seed, plot_offset=0, farm_config=None, lookahead=False,
            lookahead_horizon=12, runtime_guard=None):
    examples, samples = {}, []
    frozen = copy.deepcopy(parent)
    frozen.config.update(epsilonStart=0., epsilonMin=0.)
    frozen.learn = lambda *a, **k: None
    frozen.outcome = lambda *a, **k: None
    with Farm() as farm:
        fresh = farm.call('state')
        fresh['config'].update(farm_config or {})
        if plot_offset:
            fresh['p'][0]['active'] = 0
            fresh['p'][plot_offset]['active'] = 1
        farm.call('load', state=fresh)
        sim = hive_simulation(farm, frozen, seed=seed)
        sim.r['epsilon'] = 0.
        for step in range(steps):
            if runtime_guard is not None:
                runtime_guard.check()
            before = farm.call('state')
            result = sim.step()
            context = copy.deepcopy(sim.pending['context'])
            # Independently query all four tools at the real current stage, including
            # tools omitted by a FIFO commitment. Clear only the cloned queue.
            for plot in before['p']:
                if not plot['active'] or plot['stage'] in ('GROWING', 'HARVESTING'):
                    continue
                branch_state = copy.deepcopy(before)
                branch_state['p'][plot['id'] - 1]['queue'] = []
                with Farm(branch_state) as text_branch:
                    text_branch.call('begin')
                    text_candidates = text_branch.call('candidates')
                text_items, text_labels = [], []
                for item in text_candidates:
                    if item['t'] not in TOOLS[:4] or item['a'] != plot['id']:
                        continue
                    with Farm(branch_state) as text_branch:
                        text_branch.call('begin')
                        request = dict(_execution_request(item), gate=1.)
                        actual_text = text_branch.call('execute', **request, threshold=parent.config['threshold'])
                    prompt = describe_prompt(item, item['a'])
                    target = f"{item['t']} is {'legal' if actual_text['legal'] else 'illegal'} on {item['stage']}."
                    examples[prompt] = {'prompt': prompt, 'target': target,
                        'provenance': 'Rust execution on isolated queue-cleared clone', 'tick': result['tick'],
                        'state_sha256': hashlib.sha256(json.dumps(branch_state, sort_keys=True).encode()).hexdigest()}
                    text_items.append(item)
                    text_labels.append(int(actual_text['legal']))
                if text_items and step % 10 == 0:
                    samples.append({'items': text_items, 'legal': text_labels, 'best': None})
            legal = []
            utilities = []
            counterfactual_score_trials = []
            for item in context:
                with Farm(before) as branch:
                    branch.call('begin')
                    request = _execution_request(item)
                    request['gate'] = 1.
                    actual = branch.call('execute', **request, threshold=parent.config['threshold'])
                    legal.append(int(actual['legal']))
                    prompt = describe_prompt(item, item['a'])
                    target = f"{item['t']} is {'legal' if actual['legal'] else 'illegal'} on {item['stage']}."
                    examples[prompt] = {'prompt': prompt, 'target': target,
                        'provenance': 'Rust execution at actual FIFO boundary', 'tick': result['tick'],
                        'state_sha256': hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest()}
                    if lookahead and step % 10 == 0:
                        branch_state = branch.call('state')
                        score_trials = []
                        bank_trials = []
                        for rollout_seed in COUNTERFACTUAL_ROLLOUT_SEEDS:
                            with Farm(branch_state) as rollout_farm:
                                continuation = hive_simulation(
                                    rollout_farm, frozen, branch_state, seed=rollout_seed)
                                for _ in range(lookahead_horizon):
                                    if runtime_guard is not None:
                                        runtime_guard.check()
                                    continuation.r['epsilon'] = 0.
                                    continuation.step()
                                r = continuation.r
                            score_trials.append(r['harvests'] - before['r']['harvests']
                                                - (r['decays'] - before['r']['decays']))
                            bank_trials.append(r['bank'] - before['r']['bank'])
                        counterfactual_score_trials.append(score_trials)
                        mean_score = sum(score_trials) / len(score_trials)
                        mean_bank = sum(bank_trials) / len(bank_trials)
                        utilities.append((int(actual['legal']), mean_score, mean_bank))
            chosen = next(i for i, a in enumerate(context) if
                          (a['t'], a['a'], a['b']) == (result['action']['t'], result['action']['a'], result['action']['b']))
            # Only replace the parent target when Rust measures a strict advantage.
            best = chosen
            if utilities:
                winner = max(range(len(utilities)), key=lambda i: utilities[i])
                if utilities[winner] > utilities[chosen]:
                    best = winner
            if step % 10 == 0:
                samples.append({'items': context, 'legal': legal, 'best': best,
                                'parent_raw': [a['raw'] for a in context],
                                'parent_action_index': chosen,
                                'oracle_improved': best != chosen,
                                'oracle_horizon': lookahead_horizon if utilities else 0,
                                'counterfactual_score_deltas': [utility[1] for utility in utilities]
                                if utilities else None,
                                'counterfactual_score_trials': counterfactual_score_trials if utilities else None,
                                'counterfactual_rollout_seeds': list(COUNTERFACTUAL_ROLLOUT_SEEDS) if utilities else None,
                                'counterfactual_score_advantages': center_counterfactual_scores(utilities, chosen)})
    return list(examples.values()), samples


def language_probe(engine, examples, runtime_guard=None):
    rows = []
    for example in examples:
        if runtime_guard is not None:
            runtime_guard.check()
        rows.append({'prompt': example['prompt'], 'expected': example['target'],
                     'generated': engine.speak(example['prompt'])})
    hits = sum(r['generated'] == r['expected'] for r in rows)
    return {'exact': hits, 'total': len(rows), 'accuracy': hits / max(1, len(rows)), 'examples': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--updates', type=int, default=2000)
    parser.add_argument('--collect-steps', type=int, default=1200)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--admit', action='store_true',
                        help='allow the repeated verifier to admit a passing candidate')
    parser.add_argument('--voice-progress', action='store_true',
                        help='speak bounded progress updates through the Hive drone voice')
    parser.add_argument('--retention-weight', type=float,
                        help='override failure adaptation for a controlled candidate experiment')
    args = parser.parse_args()
    if min(args.updates, args.collect_steps, args.threads) < 1:
        parser.error('Counts must be positive')
    if args.retention_weight is not None and (not math.isfinite(args.retention_weight) or args.retention_weight < 0):
        parser.error('Retention weight must be finite and nonnegative')
    run = LEARNING / 'neural_runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    candidate_lease = None
    runtime_guard = RuntimeBodyGuard(requested_threads=args.threads, candidate_run_id=run.name)
    try:
        body_verdict = runtime_guard.check(force=True)
    except BodyRuntimeHold as hold:
        try:
            receipt_path = persist_body_hold(run, hold.verdict)
            print(f'[BODY HOLD] Durable hold receipt: {receipt_path}')
        except Exception as receipt_error:
            print(f'[BODY HOLD] Receipt write denied or unavailable: {receipt_error}', file=sys.stderr)
        raise
    sources = (Path(__file__), WORKSPACE / 'autonomy' / 'farm_corpus.py', WORKSPACE / 'INN' / 'inn' / 'language.py',
               WORKSPACE / 'INN' / 'inn' / 'transformer.py',
               WORKSPACE / 'INN' / 'farm_rust' / 'target' / 'release' / 'inn_farm.dll',
               WORKSPACE / 'autonomy' / 'verify_neural_inn.py',
               WORKSPACE / 'autonomy' / 'inn_candidate_lease.py',
               WORKSPACE / 'aios_rebuild' / 'main_core' / 'main_core.py',
               WORKSPACE / 'aios_rebuild' / 'main_core' / 'body_resources.py',
               WORKSPACE / 'aios_rebuild' / 'main_core' / 'mind_runtime_gate.py',
               WORKSPACE / 'aios_rebuild' / 'main_core' / 'body_runtime_client.py',
               WORKSPACE / 'aios_rebuild' / 'local_security_core' / 'src' / 'lib.rs',
               WORKSPACE / 'aios_rebuild' / 'local_security_core' / 'src' / 'body_authority.rs',
               WORKSPACE / 'aios_rebuild' / 'local_security_core' / 'src' / 'training_security.rs',
               WORKSPACE / 'aios_rebuild' / 'local_security_core' / 'target' / 'debug' / 'security_core.dll',
               WORKSPACE / 'aios_rebuild' / 'body_runtime' / 'Cargo.toml',
               WORKSPACE / 'aios_rebuild' / 'body_runtime' / 'Cargo.lock',
               WORKSPACE / 'aios_rebuild' / 'body_runtime' / 'core_manifest.json',
               WORKSPACE / 'aios_rebuild' / 'body_runtime' / 'Dockerfile',
               WORKSPACE / 'aios_rebuild' / 'body_runtime' / 'image_id.txt',
               WORKSPACE / 'aios_rebuild' / 'body_runtime' / 'src' / 'main.rs',
               WORKSPACE / 'aios_rebuild' / '.dockerignore')
    source_hashes = {str(source): digest(source) for source in sources}
    body_runtime_permit = body_verdict.pop('body_runtime_permit', None)
    candidate_lease = InnCandidateLease.begin(
        run.name, list(source_hashes.values()), float(body_verdict['stability_sn']),
        body_runtime_permit, body_verdict.get('requested_threads'))
    runtime_guard = LeaseAwareRuntimeGuard(runtime_guard, candidate_lease)
    run = candidate_lease.stage_root
    try:
        body_verdict = runtime_guard.check(force=True)
    except BodyRuntimeHold as hold:
        status = {'run': str(run), 'stage': 'body_held', 'active_policy_changed': False,
                  'body_gate': hold.verdict, 'at_utc': datetime.now(timezone.utc).isoformat()}
        write_candidate_pointer(candidate_lease, STATUS, status)
        raise
    persist_body_gate(candidate_lease, run, body_verdict)
    _load_training_stack()
    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    admitted_pointer = LEARNING / 'neural_admitted.json'
    if args.resume is None and admitted_pointer.is_file():
        args.resume = Path(json.loads(admitted_pointer.read_text())['run'])
    rng = random.Random(812)
    for source in sources:
        if source.suffix == '.py':
            candidate_lease.write_artifact(run / source.name, source.read_bytes())
    policy = LEARNING / 'verified_recovery_policy.json'
    state = json.loads((WORKSPACE / 'autonomy' / 'inn_hive_state.json').read_text())
    config = copy.deepcopy(state['config'])
    baseline = json.loads(policy.read_text())['engine']
    parent = StabilizedSourceEngine(copy.deepcopy(config), baseline)
    engine = LanguageEngine(copy.deepcopy(config), baseline, seed=812)
    retention_recommendation = None
    current_retention = config.get('neuralRetentionWeight', .1)
    if args.resume:
        manifest = json.loads((args.resume / 'manifest.json').read_text())
        prior_evaluation = json.loads((args.resume / 'evaluation.json').read_text())
        if not prior_evaluation['passed']:
            raise ValueError('A failed candidate cannot become the training parent')
        if digest(args.resume / 'engine.pt') != manifest['engine_sha256']:
            raise ValueError('Resume checkpoint hash mismatch')
        engine.load(args.resume / 'engine.pt')
        parent = copy.deepcopy(engine)
        previous = json.loads(STATUS.read_text()) if STATUS.is_file() else {}
        prior_config = json.loads((args.resume / 'parent.json').read_text())['config']
        current_retention = prior_config.get('neuralRetentionWeight', .1)
        retention_recommendation = retention_after_failure(
            previous, digest(args.resume / 'engine.pt'), current_retention)
    retention = args.retention_weight if args.retention_weight is not None else retention_recommendation
    if retention is None:
        retention = current_retention
    config['neuralRetentionWeight'] = retention
    engine.config['neuralRetentionWeight'] = retention
    parent_sha = digest(policy)
    write_run_json(candidate_lease, run / 'parent.json', {'config': config, 'engine': baseline, 'sha256': parent_sha})
    print('[INN TRAINING] parent artifact persisted', flush=True)
    protocol = {'scope': 'short Rust-grounded legality descriptions; no general language claim',
                'device': 'cpu', 'threads': args.threads, 'seed': 812,
                'language_gate': 'at least 20 previously-unseen prompts, exact generation >= 0.95',
                'action_contract': 'Hive one-action commitment and deterministic score/tool/plot tie rule',
                'counterfactual_target': 'Pairwise ranking from the Rust-cloned 12-tick score delta (harvests minus decays) under the deterministic parent continuation, centered against the parent-selected action in the same state; legal gate labels and parent-score retention remain separate',
                'counterfactual_rollout': {'seeds': list(COUNTERFACTUAL_ROLLOUT_SEEDS),
                                           'epsilon': COUNTERFACTUAL_EPSILON,
                                           'policy': 'parent_deterministic',
                                           'live_policy_changed': False},
                'farm_gate': 'no lower score, no more decays/invalids; strictly higher score on at least one final probe',
                'validation': {'steps': 3000, 'seed': 991},
                'final': [{'steps': 5000, 'seed': 1801},
                          {'steps': 5000, 'seed': 1802, 'farm_config': {'tillDecay': 4, 'seedDecay': 3, 'waterDecay': 3}}],
                'parent_sha256': parent_sha, 'resume': str(args.resume) if args.resume else None,
                'source_hashes': source_hashes}
    protocol.update(collect_steps=args.collect_steps, update_budget=args.updates,
                    retention_weight=engine.config.get('neuralRetentionWeight', .1))
    if args.resume and retention_recommendation != current_retention:
        adaptation = {'previous_run': previous['run'],
            'variable': 'neuralRetentionWeight',
            'before': previous.get('receipt', {}).get('protocol', {}).get('retention_weight', current_retention),
            'after': retention_recommendation,
            'reason': 'farm regression while training against the same admitted parent'}
        adaptation['applied'] = args.retention_weight is None
        adaptation['active_weight'] = retention
        protocol['failure_adaptation'] = adaptation
    if args.retention_weight is not None:
        protocol['retention_override'] = {
            'automatic_recommendation': retention_recommendation,
            'active_weight': retention,
            'reason': 'explicit CLI override for controlled candidate experiment'}
    protocol['neural_parameters'] = sum(p.numel() for p in engine.model.parameters())
    print('[INN TRAINING] protocol assembled', flush=True)
    if args.resume:
        protocol['parent_checkpoint_sha256'] = digest(args.resume / 'engine.pt')
        protocol['parent_kind'] = 'own_neural_inn'
    else:
        protocol['parent_kind'] = 'legacy_learned_farm_policy'
    status = {'run': str(candidate_lease.final_root), 'stage': 'collecting Rust examples', 'active_policy_changed': False,
              'protocol': protocol, 'at_utc': datetime.now(timezone.utc).isoformat()}
    print('[INN TRAINING] publishing initial status', flush=True)
    write_candidate_pointer(candidate_lease, STATUS, status)
    print('[INN TRAINING] initial status published', flush=True)
    voice = None
    try:
        runtime_guard.check(force=True)
        if args.voice_progress:
            try:
                voice = VoiceProgress()
                voice.speak('INN drone training has started. The deterministic body allowed this bounded CPU candidate run. The Queen policy remains in control.')
            except BodyRuntimeHold:
                raise
            except Exception as error:
                print(json.dumps({'voice_progress': 'UNAVAILABLE', 'reason': type(error).__name__}), flush=True)
                if voice is not None:
                    voice.close()
                    voice = None
        train, action_samples = collect(parent, args.collect_steps, 812, lookahead=True,
                                        runtime_guard=runtime_guard)
        # Vary actual active plot identities and prefix lengths, not just wording.
        for plot_offset in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
                            16, 17, 18, 19, 29, 30, 31, 49, 50, 51, 59, 60, 61):
            extra_text, extra_actions = collect(parent, 60, 812, plot_offset=plot_offset,
                                                lookahead=True, runtime_guard=runtime_guard)
            train.extend(extra_text)
            action_samples.extend(extra_actions)
        live_corpus = LEARNING / 'neural_live_examples.json'
        live_count = 0
        if live_corpus.is_file():
            for example in json.loads(live_corpus.read_text()).values():
                if example.get('provenance') != 'live Rust counterfactual':
                    continue
                # Plot 21/41 are reserved for language evaluation.
                if example['prompt'].startswith(('plot=21 ', 'plot=41 ')):
                    continue
                train.append(example)
                live_count += 1
        status['live_examples'] = live_count
        # Disjoint plot identities, durations, and trajectories. Training cannot read these targets.
        validation, _ = collect(parent, 180, 991, plot_offset=20, runtime_guard=runtime_guard)
        write_run_json(candidate_lease, run / 'training_data.json', {'language': train, 'actions': action_samples})
        write_run_json(candidate_lease, run / 'validation_data.json', validation)
        corpus = publish_corpus(train, action_samples, run / 'farm_corpus',
                                {str(run / 'training_data.json'): digest(run / 'training_data.json')},
                                writer=lambda path, payload: candidate_lease.write_artifact(path, payload))
        corpus_manifest = verify_corpus(corpus)
        # INN and LoRA use two views of this exact immutable corpus.
        corpus_data = json.loads((corpus / 'inn_train.json').read_text())
        train, action_samples = corpus_data['language'], corpus_data['actions']
        action_weights = action_sampling_weights(action_samples)
        action_groups = Counter(action_identity_group(sample) for sample in action_samples)
        protocol['action_sampling'] = {
            'strategy': 'inverse_frequency_by_active_plot_identity_set_v1',
            'groups': [{'active_plot_ids': list(group), 'samples': count,
                        'per_sample_weight': 1.0 / count}
                       for group, count in sorted(action_groups.items())],
            'total_samples': len(action_samples),
        }
        protocol['counterfactual_coverage'] = counterfactual_coverage(action_samples)
        protocol['corpus_id'] = corpus_manifest['corpus_id']
        protocol['corpus_manifest_sha256'] = digest(corpus / 'manifest.json')
        write_run_json(candidate_lease, run / 'protocol.json', protocol)
        corpus_pointer = {
            'folder': str(candidate_lease.final_root / corpus.relative_to(candidate_lease.stage_root)),
            'manifest_sha256': digest(corpus / 'manifest.json'), **corpus_manifest}
        initial_language = language_probe(engine, validation, runtime_guard)
        best_quality = -1
        selected_update = None
        next_voice_update = max(1, (args.updates + 3) // 4)
        started = time.monotonic()
        for update in range(1, args.updates + 1):
            runtime_guard.check()
            batch = rng.choices(train, k=16)
            actions = rng.choices(action_samples, weights=action_weights, k=2)
            loss = engine.train_joint(batch, actions)
            if update % 25 == 0 or update == 1:
                status.update(stage='training', update=update, total_updates=args.updates,
                              optimizer_steps=engine.optimizer_steps, examples=len(train),
                              action_examples=len(action_samples), losses=loss,
                              elapsed_seconds=time.monotonic()-started,
                              at_utc=datetime.now(timezone.utc).isoformat())
                write_candidate_pointer(candidate_lease, STATUS, status)
            if update % 500 == 0 or update == args.updates:
                lang = language_probe(engine, validation, runtime_guard)
                farm = frozen_probe(engine, config, 3000, 991, runtime_guard=runtime_guard)
                parent_farm = frozen_probe(parent, config, 3000, 991, runtime_guard=runtime_guard)
                retained_validation = (farm['score'] >= parent_farm['score']
                    and farm['decays'] <= parent_farm['decays'] and farm['invalid'] <= parent_farm['invalid'])
                quality = (int(lang['accuracy'] >= .95 and retained_validation),
                           farm['score'], lang['accuracy'])
                report = {'update': update, 'language': lang, 'farm': farm, 'parent': parent_farm}
                write_run_json(candidate_lease, run / f'validation-{update:06d}.json', report)
                engine.freeze_target()
                checkpoint = io.BytesIO()
                engine.save(checkpoint)
                checkpoint_bytes = checkpoint.getvalue()
                candidate_lease.write_artifact(run / f'candidate-update-{update:06d}.pt', checkpoint_bytes)
                if best_quality == -1 or quality > best_quality:
                    best_quality = quality
                    selected_checkpoint = checkpoint_bytes
                    selected_update = update
                status.update(validation=report)
                write_candidate_pointer(candidate_lease, STATUS, status)
                print(json.dumps({'update': update, 'language_accuracy': lang['accuracy'],
                                  'farm': farm, 'parent': parent_farm}), flush=True)
            if voice is not None and update >= next_voice_update:
                try:
                    voice.speak(voice_progress_text(update, args.updates))
                except BodyRuntimeHold:
                    raise
                except Exception as error:
                    print(json.dumps({'voice_progress': 'UNAVAILABLE', 'reason': type(error).__name__}), flush=True)
                    voice.close()
                    voice = None
                next_voice_update += max(1, (args.updates + 3) // 4)
        if selected_update is None:
            raise RuntimeError('No validation checkpoint selected')
        candidate_lease.write_artifact(run / 'engine.pt', selected_checkpoint)
        engine.load(run / 'engine.pt')
        status.update(stage='final evaluation')
        write_candidate_pointer(candidate_lease, STATUS, status)
        final_text, _ = collect(parent, 300, 1802, plot_offset=40,
                               farm_config={'tillDecay': 4, 'seedDecay': 3, 'waterDecay': 3},
                               runtime_guard=runtime_guard)
        known_prompts = {e['prompt'] for e in train}
        known_global_examples = [e for e in final_text if e['prompt'] in known_prompts]
        final_text = [e for e in final_text if e['prompt'] not in known_prompts]
        # Exact duplicates must never cross a split.
        assert not {e['prompt'] for e in train} & {e['prompt'] for e in final_text}
        language = language_probe(engine, final_text, runtime_guard)
        comparisons = []
        for case in protocol['final']:
            runtime_guard.check()
            comparisons.append({'candidate': frozen_probe(engine, config, **case,
                                                           runtime_guard=runtime_guard),
                                'parent': frozen_probe(parent, config, **case,
                                                        runtime_guard=runtime_guard)})
        retained = all(c['candidate']['score'] >= c['parent']['score']
                       and c['candidate']['decays'] <= c['parent']['decays']
                       and c['candidate']['invalid'] <= c['parent']['invalid'] for c in comparisons)
        improved = retained and any(c['candidate']['score'] > c['parent']['score'] for c in comparisons)
        receipt = {'schema': 'inn_neural_language_evaluation_v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
                   'passed': language['total'] >= 20 and language['accuracy'] >= .95 and improved, 'farm_retained': retained,
                   'farm_improved': improved, 'language': language, 'farm': comparisons,
                   'initial_validation_language': initial_language, 'protocol': protocol,
                   'known_global_examples_excluded_from_unseen_scope': len(known_global_examples),
                   'selected_update': selected_update, 'selected_optimizer_steps': engine.optimizer_steps,
                   'engine_sha256': digest(run / 'engine.pt'), 'active_policy_changed': False}
        write_run_json(candidate_lease, run / 'evaluation.json', receipt)
        write_run_json(candidate_lease, run / 'manifest.json', {'engine_sha256': receipt['engine_sha256'],
                                           'parent_sha256': parent_sha,
                                           'selected_update': selected_update,
                                           'model': 'own-INN-shared-action-byte-transformer'})
        status.update(stage='evaluated', receipt=receipt, at_utc=receipt['at_utc'])
        run = candidate_lease.commit()
        status['run'] = str(run)
        write_candidate_pointer(candidate_lease, STATUS, status)
        corpus_pointer['folder'] = str(run / corpus.relative_to(candidate_lease.stage_root))
        write_candidate_pointer(candidate_lease, LEARNING / 'farm_corpus_latest.json', corpus_pointer)
        candidate_pointer = {'run': str(run), 'passed': receipt['passed'],
                     'engine_sha256': receipt['engine_sha256'], 'evaluation_sha256': digest(run / 'evaluation.json')}
        write_candidate_pointer(candidate_lease, LEARNING / 'neural_candidate.json', candidate_pointer)
        if receipt['passed']:
            runtime_guard.check(force=True)
            try:
                subprocess.run(verifier_command(admit=args.admit),
                               cwd=WORKSPACE, check=True, timeout=300)
            except subprocess.CalledProcessError as exc:
                recheck_path = run / 'recheck.json'
                if recheck_path.is_file():
                    recheck = json.loads(recheck_path.read_text())
                    if recheck.get('body_held'):
                        raise BodyRuntimeHold(recheck['body_gate']) from exc
                raise
        if voice is not None:
            admitted = False
            if admitted_pointer.is_file():
                try:
                    admitted = json.loads(admitted_pointer.read_text()).get('run') == str(run)
                except (OSError, json.JSONDecodeError):
                    admitted = False
            try:
                voice.speak(voice_completion_text(receipt, admitted))
            except BodyRuntimeHold:
                raise
            except Exception as error:
                print(json.dumps({'voice_progress': 'UNAVAILABLE', 'reason': type(error).__name__}), flush=True)
                voice.close()
                voice = None
        print(json.dumps({'run': str(run), 'passed': receipt['passed'], 'language_accuracy': language['accuracy'],
                          'farm_retained': retained, 'farm_improved': improved}), flush=True)
    except BodyRuntimeHold as exc:
        status.update(stage='body_held', body_gate=exc.verdict,
                      at_utc=datetime.now(timezone.utc).isoformat())
        write_candidate_pointer(candidate_lease, STATUS, status)
        raise
    except Exception as exc:
        status.update(stage='failed', error=f'{type(exc).__name__}: {exc}')
        if candidate_lease is None:
            _atomic_json(STATUS, status)
        else:
            write_candidate_pointer(candidate_lease, STATUS, status)
        raise
    finally:
        if voice is not None:
            voice.close()


if __name__ == '__main__':
    LEARNING.mkdir(parents=True, exist_ok=True)
    with file_lock(LEARNING / 'neural_training.lock'):
        main()
