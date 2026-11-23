"""Bounded sentence learning from a verified custom-tokenizer parent."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'INN')]
import torch
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from autonomy.wiki_sentence_corpus import prepare
from autonomy.inn_hive import _atomic_json
from viv_autonomy import Store, worker_alive, file_lock

LEARNING = ROOT / 'autonomy/learning'
STATUS = LEARNING / 'inn_sentence_status.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def examples(rows, stage):
    return [{'prompt': '' if stage == 'content' else 'Restore: ' + r['reduced'] + '\n',
             'target': r['reduced'] if stage == 'content' else r['original']} for r in rows]


@torch.no_grad()
def measure(engine, data):
    total, count = 0., 0
    for example in data:
        tokens = len(engine.tokenizer.encode(example['target'])) + 1
        total += float(engine.language_batch([example])) * tokens
        count += tokens
    return {'nll': total / count, 'target_tokens': count, 'sentences': len(data)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--articles', type=int, default=80)
    parser.add_argument('--updates', type=int, default=600)
    parser.add_argument('--stage', choices=('content', 'structure'), default='content')
    parser.add_argument('--retention-every', type=int, choices=range(2, 11), default=5)
    args = parser.parse_args()
    if args.stage == 'structure':
        raise ValueError('Structure pass remains closed until reduced-sentence generation passes a separate quality evaluation')
    if not 20 <= args.articles <= 500 or not 1 <= args.updates <= 2000:
        raise ValueError('Pilot limits: 20..500 articles; 1..2000 updates')
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    with file_lock(ROOT / 'autonomy/inn_tokenizer_rebuild.lock'):
        store = Store()
        if store.get('enabled') or worker_alive() or store.get('gpu_training_active'):
            raise RuntimeError('Hive must remain paused for this CPU pilot')
        pointer = LEARNING / 'neural_admitted.json'
        farm_parent_hash = digest(pointer)
        admitted = json.loads(pointer.read_text())
        state = json.loads((Path(admitted['run']) / 'parent.json').read_text())
        parent_status = json.loads((LEARNING / 'inn_tokenizer_status.json').read_text())
        parent = Path(parent_status['run'])
        proof = json.loads((parent / 'evaluation.json').read_text())
        if not proof['passed'] or proof['checkpoint_sha256'] != digest(parent / 'engine.pt'):
            raise ValueError('Custom-tokenizer parent did not pass its integrity/learning gate')
        parent_hash = digest(parent / 'engine.pt')
        old_tokenizer = INNCharacterTokenizer.from_manifest(json.loads((parent / 'tokenizer.json').read_text()))
        corpus = prepare('F:/AI_Datasets/wikipedia_deduplicated', args.articles)
        by_split = {key: [r for r in corpus['rows'] if r['split'] == key] for key in ('train', 'validation', 'test')}
        replay = json.loads((parent / 'training_data.json').read_text())
        train = examples(by_split['train'], args.stage)
        tokenizer = INNCharacterTokenizer.from_texts(list(old_tokenizer.characters) +
                    [f[k] for f in train for k in ('prompt', 'target')])
        evaluation, excluded = {}, {}
        for split in ('validation', 'test'):
            evaluation[split], excluded[split] = [], 0
            for example in examples(by_split[split], args.stage):
                try:
                    tokenizer.encode(example['prompt'] + example['target'])
                except ValueError:
                    excluded[split] += 1
                    continue
                evaluation[split].append(example)
            if len(evaluation[split]) < 8:
                raise ValueError(f'Insufficient representable {split} sentences; exclusions={excluded[split]}')
        train = [e for e in train if len(e['prompt'] + e['target']) + 2 <= 512]
        for split in evaluation:
            evaluation[split] = [e for e in evaluation[split] if len(e['prompt'] + e['target']) + 2 <= 512]
            if len(evaluation[split]) < 8:
                raise ValueError('Insufficient evaluation after context checks')
        run = LEARNING / 'sentence_runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        run.mkdir(parents=True)
        _atomic_json(run / 'corpus.json', corpus)
        _atomic_json(run / 'tokenizer.json', tokenizer.manifest())
        for source in (Path(__file__), ROOT / 'autonomy/wiki_sentence_corpus.py',
                       ROOT / 'INN/inn/language.py', ROOT / 'INN/inn/tokenizer.py'):
            (run / source.name).write_bytes(source.read_bytes())
        engine = LanguageEngine(copy.deepcopy(state['config']), state['engine'], tokenizer=tokenizer, context_length=512, seed=812)
        engine.migrate_character_parent(parent / 'engine.pt')
        retention = json.loads((parent / 'heldout_data.json').read_text())
        before = {k: measure(engine, v) for k, v in evaluation.items()}
        started = time.monotonic()
        status = {'stage': 'training', 'run': str(run), 'pid': os.getpid(), 'updates': 0,
                  'total_updates': args.updates, 'curriculum': args.stage, 'train_sentences': len(train),
                  'articles': len(corpus['sources']), 'tokenizer_size': tokenizer.size, 'live_activated': False}
        protocol = dict(status, parent=str(parent), parent_sha256=parent_hash,
                        corpus_sha256=digest(run / 'corpus.json'), excluded_evaluation=excluded,
                        gate='test NLL at least 2% lower; retained exact descriptions at least 95%; parent untouched',
                        optimizer_lr=.0002, retention_update_every=args.retention_every, before=before,
                        evaluation_scope='Development holdouts; generated quality is separate from NLL/retention gate')
        _atomic_json(run / 'protocol.json', protocol)
        _atomic_json(STATUS, status)
        for group in engine.optimizer.param_groups:
            group['lr'] = .0002
        for step in range(args.updates):
            if time.monotonic() - started > 600:
                raise TimeoutError('Sentence pilot exceeded 600 seconds')
            source = replay if step % args.retention_every == args.retention_every - 1 else train
            # Contiguous sentence batches keep article order deterministic.
            offset = (step * 8) % len(source)
            batch = [source[(offset + i) % len(source)] for i in range(min(8, len(source)))]
            engine.train_joint(batch, [])
            if (step + 1) % 25 == 0:
                status.update(updates=step + 1, loss=engine.loss)
                _atomic_json(STATUS, status)
        engine.save(run / 'engine.pt')
        after = {k: measure(engine, v) for k, v in evaluation.items()}
        retained = sum(engine.speak(e['prompt'], 80) == e['target'] for e in retention)
        generations = []
        for e in evaluation['test'][:6]:
            prompt = e['target'][:24] if args.stage == 'content' else e['prompt']
            generations.append({'prompt': prompt, 'generated': engine.speak(prompt, 80), 'reference': e['target']})
        untouched = parent_hash == digest(parent / 'engine.pt') and farm_parent_hash == digest(pointer)
        passed = after['test']['nll'] <= before['test']['nll'] * .98 and retained / len(retention) >= .95 and untouched
        receipt = {'schema': 'inn_wiki_sentence_pilot_v1', 'passed': passed, 'before': before, 'after': after,
                   'retained': retained, 'retention_total': len(retention), 'parent_unchanged': untouched,
                   'generations': generations, 'checkpoint_sha256': digest(run / 'engine.pt'),
                   'tokenizer_sha256': tokenizer.manifest()['sha256'], 'duration_seconds': time.monotonic() - started,
                   'scope': 'Development next-character prediction on reduced Wikipedia lead sentences; fluent factual knowledge remains unproven.',
                   'generation_quality_gate': 'unproven', 'retention_update_every': args.retention_every,
                   'live_activated': False}
        _atomic_json(run / 'evaluation.json', receipt)
        status.update(stage='passed_candidate' if passed else 'failed_candidate', updates=args.updates, receipt=receipt)
        _atomic_json(STATUS, status)
        print(json.dumps({'run': str(run), 'passed': passed, 'before': before, 'after': after, 'retained': retained}))
        if not passed:
            raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if STATUS.exists():
            status = json.loads(STATUS.read_text())
            if status.get('pid') == os.getpid() and status.get('stage') == 'training':
                status.update(stage='error', error=f'{type(exc).__name__}: {exc}')
                _atomic_json(STATUS, status)
        raise
