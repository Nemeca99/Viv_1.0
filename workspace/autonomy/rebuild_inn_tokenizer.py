"""Bounded custom-tokenizer integration proof; no live model activation."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'INN'))
sys.path.insert(0, str(ROOT))
import torch
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from inn import uml_character_tokenizer as uml
from autonomy.inn_hive import _atomic_json
from viv_autonomy import Store, worker_alive, file_lock


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(engine, facts):
    rows = [{'prompt': f['prompt'], 'expected': f['target'],
             'generated': engine.speak(f['prompt'], max_new=80)} for f in facts]
    return {'exact': sum(r['expected'] == r['generated'] for r in rows),
            'total': len(rows), 'examples': rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--updates', type=int, default=500)
    parser.add_argument('--final-plot', type=int, choices=range(41, 65), default=41)
    args = parser.parse_args()
    if not 1 <= args.updates <= 1000:
        raise ValueError('Bounded update budget must be 1..1000')
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    learning = ROOT / 'autonomy/learning'
    with file_lock(ROOT / 'autonomy/inn_tokenizer_rebuild.lock'):
        store = Store()
        if store.get('enabled') or worker_alive() or store.get('gpu_training_active'):
            raise RuntimeError('This proof requires the Hive paused and GPU training inactive')
        pointer = learning / 'neural_admitted.json'
        original_pointer = digest(pointer)
        admission = json.loads(pointer.read_text())
        parent = Path(admission['run'])
        checkpoint = parent / 'engine.pt'
        before_hash = digest(checkpoint)
        if before_hash != admission['engine_sha256']:
            raise ValueError('Admitted parent integrity mismatch')
        parent_state = json.loads((parent / 'parent.json').read_text())
        train = json.loads((parent / 'training_data.json').read_text())['language']
        final = [{'prompt': f['prompt'], 'target': f['expected']} for f in
                 json.loads((parent / 'evaluation.json').read_text())['language']['examples']]
        for fact in final:
            fact['prompt'] = fact['prompt'].replace('plot=41 ', f'plot={args.final_plot} ')
        names = ['José', 'Zoë', '水🌱']
        unicode_train = [{'prompt': name + ': ' + f['prompt'], 'target': name + ' → ' + f['target']}
                         for name in names for f in train]
        unicode_final = [{'prompt': name + ': ' + f['prompt'], 'target': name + ' → ' + f['target']}
                         for name in names for f in final]
        training = train + unicode_train
        tokenizer = INNCharacterTokenizer.from_texts(
            [chr(i) for i in range(128)] + [f[k] for f in training for k in ('prompt', 'target')])
        # Vocabulary derives from training only; held-out prompts must fit it.
        for f in unicode_final:
            tokenizer.encode(f['prompt'])
            tokenizer.encode(f['target'])
        assert not set(f['prompt'] for f in training) & set(f['prompt'] for f in final + unicode_final)
        run = learning / 'tokenizer_runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        run.mkdir(parents=True)
        _atomic_json(run / 'tokenizer.json', tokenizer.manifest())
        _atomic_json(run / 'training_data.json', training)
        _atomic_json(run / 'heldout_data.json', final + unicode_final)
        engine = LanguageEngine(copy.deepcopy(parent_state['config']), parent_state['engine'],
                                tokenizer=tokenizer, context_length=512, seed=812)
        engine.migrate_byte_parent(checkpoint)
        baseline = {'legacy': evaluate(engine, final), 'unicode': evaluate(engine, unicode_final)}
        status_path = learning / 'inn_tokenizer_status.json'
        started = time.monotonic()
        status = {'stage': 'training', 'run': str(run), 'updates': 0, 'total_updates': args.updates,
                  'pid': os.getpid(),
                  'tokenizer_size': tokenizer.size, 'context_length': 512, 'live_activated': False}
        _atomic_json(status_path, status)
        rng = random.Random(812)
        for step in range(args.updates):
            engine.train_joint(rng.sample(training, min(16, len(training))), [])
            if (step + 1) % 25 == 0:
                status.update(updates=step + 1, loss=engine.loss)
                _atomic_json(status_path, status)
        engine.save(run / 'engine.pt')
        restored = LanguageEngine(copy.deepcopy(parent_state['config']), parent_state['engine'],
            tokenizer=INNCharacterTokenizer.from_manifest(json.loads((run / 'tokenizer.json').read_text())),
            context_length=512, seed=99)
        restored.load(run / 'engine.pt')
        result = {'legacy': evaluate(restored, final), 'unicode': evaluate(restored, unicode_final)}
        probes = ['water → harvest', 'José café', '水 🌱', 'e\u0301', '\x00\U0010ffff']
        roundtrips = all(uml.decode(uml.encode(t)) == t for t in probes)
        same_reload = restored.speak(unicode_final[0]['prompt'], 80) == engine.speak(unicode_final[0]['prompt'], 80)
        untouched = digest(checkpoint) == before_hash and digest(pointer) == original_pointer
        passed = (roundtrips and same_reload and untouched
                  and result['legacy']['exact'] == result['legacy']['total']
                  and result['unicode']['exact'] / result['unicode']['total'] >= .95
                  and result['unicode']['exact'] > baseline['unicode']['exact'])
        receipt = {'schema': 'inn_custom_tokenizer_proof_v1', 'passed': passed,
            'baseline': baseline, 'after': result, 'roundtrips': roundtrips,
            'reload_preserved_generation': same_reload, 'live_parent_unchanged': untouched,
            'parent_sha256': before_hash, 'checkpoint_sha256': digest(run / 'engine.pt'),
            'tokenizer_sha256': tokenizer.manifest()['sha256'], 'updates': args.updates,
            'final_plot': args.final_plot,
            'duration_seconds': time.monotonic() - started,
            'universal_source_sha256': digest(ROOT / 'INN/inn/uml_character_tokenizer.py'),
            'scope': 'Reserved farm-description prompts with Unicode labels; no Wikipedia or general-language mastery claim.',
            'live_activated': False}
        _atomic_json(run / 'evaluation.json', receipt)
        status.update(stage='passed_candidate' if passed else 'failed_candidate', updates=args.updates,
                      receipt=receipt)
        _atomic_json(status_path, status)
        print(json.dumps({'passed': passed, 'run': str(run), 'before': {k:v['exact'] for k,v in baseline.items()},
                          'after': {k:v['exact'] for k,v in result.items()}, 'parent_unchanged': untouched}))
        if not passed:
            raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        status_path = ROOT / 'autonomy/learning/inn_tokenizer_status.json'
        if status_path.exists():
            status = json.loads(status_path.read_text())
            if status.get('pid') == os.getpid() and status.get('stage') == 'training':
                status.update(stage='error', error=f'{type(exc).__name__}: {exc}')
                _atomic_json(status_path, status)
        raise
