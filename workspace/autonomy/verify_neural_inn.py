"""Repeat the candidate's measured gate and optionally admit its proposal path."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autonomy.train_neural_inn import (
    LEARNING, WORKSPACE, frozen_probe, collect, language_probe, digest, _atomic_json,
)
from autonomy.inn_candidate_lease import write_verification_receipt
from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard, BodyRuntimeHold
from viv_autonomy import Store


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--admit', action='store_true')
    args = parser.parse_args()
    runtime_guard = RuntimeBodyGuard(requested_threads=2)
    runtime_guard.check(force=True)
    from autonomy.train_neural_inn import _load_training_stack
    from inn.engine import StabilizedSourceEngine
    from inn.language import LanguageEngine

    _load_training_stack()
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    pointer = json.loads((LEARNING / 'neural_candidate.json').read_text())
    run = Path(pointer['run'])
    if digest(run / 'engine.pt') != pointer['engine_sha256']:
        raise ValueError('Candidate checkpoint hash mismatch')
    if digest(run / 'evaluation.json') != pointer['evaluation_sha256']:
        raise ValueError('Candidate evaluation hash mismatch')
    original = json.loads((run / 'evaluation.json').read_text())
    if not original['passed'] or not pointer['passed']:
        raise ValueError('Only a passed candidate can be admitted')
    if original['protocol'].get('action_contract') != 'Hive one-action commitment and deterministic score/tool/plot tie rule':
        raise ValueError('Candidate did not evaluate the current Hive execution contract')
    parent_data = json.loads((run / 'parent.json').read_text())
    config = parent_data['config']
    parent = StabilizedSourceEngine(copy.deepcopy(config), parent_data['engine'])
    if original['protocol'].get('resume'):
        if digest(Path(original['protocol']['resume']) / 'engine.pt') != original['protocol']['parent_checkpoint_sha256']:
            raise ValueError('Neural parent checkpoint hash mismatch')
        parent = LanguageEngine(copy.deepcopy(config), parent_data['engine'])
        parent.load(Path(original['protocol']['resume']) / 'engine.pt')
    neural = LanguageEngine(copy.deepcopy(config), parent_data['engine'])
    neural.load(run / 'engine.pt')
    comparisons = []
    for case in original['protocol']['final']:
        runtime_guard.check()
        comparisons.append({'candidate': frozen_probe(neural, config, **case,
                                                       runtime_guard=runtime_guard),
                            'parent': frozen_probe(parent, config, **case,
                                                    runtime_guard=runtime_guard)})
    if comparisons != original['farm']:
        raise ValueError('Repeated farm results differ from the recorded gate')
    # Rebuild reserved examples from Rust; never accept stored prose as the oracle.
    text, _ = collect(parent, 300, 1802, plot_offset=40,
                     farm_config={'tillDecay': 4, 'seedDecay': 3, 'waterDecay': 3},
                     runtime_guard=runtime_guard)
    train = json.loads((run / 'training_data.json').read_text())['language']
    known = {e['prompt'] for e in train}
    text = [e for e in text if e['prompt'] not in known]
    language = language_probe(neural, text)
    if language != original['language']:
        raise ValueError('Repeated Rust-grounded language results differ from the recorded gate')
    passed = language['total'] >= 20 and language['accuracy'] >= .95
    retained = all(c['candidate']['score'] >= c['parent']['score']
                   and c['candidate']['decays'] <= c['parent']['decays']
                   and c['candidate']['invalid'] <= c['parent']['invalid'] for c in comparisons)
    improved = retained and any(c['candidate']['score'] > c['parent']['score'] for c in comparisons)
    passed = passed and improved
    runtime_guard.check(force=True)
    admit = bool(args.admit and passed and Store().get('neural_proposals_enabled', True))
    receipt = {'at_utc': datetime.now(timezone.utc).isoformat(), 'passed': passed,
               'original_gate_reproduced': True, 'language': language, 'farm': comparisons,
               'selected_optimizer_steps': neural.optimizer_steps,
               'checkpoint_unchanged': digest(run / 'engine.pt') == pointer['engine_sha256'],
               'admitted_proposals': admit, 'body_gate': runtime_guard.last_verdict,
               'scope': '20 grounded descriptions and two 5000-step Hive-contract probes; not general language or economy mastery'}
    write_verification_receipt(run, pointer, receipt, runtime_guard.last_verdict.get('stability_sn'))
    if admit:
        _atomic_json(LEARNING / 'neural_admitted.json', pointer)
        Store().event('inn_neural_proposal_admission', {'run': str(run),
                      'checkpoint_sha256': pointer['engine_sha256'], 'receipt': str(run / 'recheck.json')})
    print(json.dumps({k: receipt[k] for k in ('passed', 'original_gate_reproduced',
                     'selected_optimizer_steps', 'checkpoint_unchanged', 'admitted_proposals')}), flush=True)


def main():
    try:
        _main()
    except BodyRuntimeHold as hold:
        record = {'at_utc': datetime.now(timezone.utc).isoformat(), 'passed': False,
                  'body_held': True, 'body_gate': hold.verdict, 'admitted_proposals': False}
        pointer_path = LEARNING / 'neural_candidate.json'
        if pointer_path.is_file():
            pointer = json.loads(pointer_path.read_text())
            run = Path(pointer['run'])
            write_verification_receipt(run, pointer, record,
                                       (record.get('body_gate') or {}).get('stability_sn'))
        else:
            _atomic_json(LEARNING / 'neural_status.json', {'stage': 'body_held', **record})
        raise


if __name__ == '__main__':
    main()
