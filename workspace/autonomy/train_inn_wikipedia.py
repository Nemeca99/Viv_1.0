"""Bounded, resumable INN Wikipedia campaign. Experimental weights only."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import shutil
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'INN')]
import torch
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from autonomy.inn_hive import _atomic_json
from autonomy.train_inn_sentences import measure, digest
from autonomy.wiki_stream import prepare_segment
from viv_autonomy import Store, worker_alive, file_lock

LEARNING = ROOT / 'autonomy/learning'
CAMPAIGN = LEARNING / 'wikipedia_campaign'
HEAD = CAMPAIGN / 'head.json'
STATUS = LEARNING / 'inn_wikipedia_status.json'
DATASET = Path('F:/AI_Datasets/wikipedia_deduplicated')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def initial_head():
    status = read(LEARNING / 'inn_sentence_status.json')
    parent = Path(status['run'])
    proof = read(parent / 'evaluation.json')
    if not proof['passed'] or digest(parent / 'engine.pt') != proof['checkpoint_sha256']:
        raise ValueError('Initial sentence candidate must pass its recorded prediction/retention gate')
    farm = read(LEARNING / 'neural_admitted.json')
    state = read(Path(farm['run']) / 'parent.json')
    tokenizer_parent = Path(read(LEARNING / 'inn_tokenizer_status.json')['run'])
    return {'schema': 'inn_wikipedia_head_v1', 'checkpoint': str(parent / 'engine.pt'),
            'checkpoint_sha256': proof['checkpoint_sha256'], 'state': state,
            'cursor': '', 'pending': None, 'offset': 0, 'articles_completed': 0,
            'files_completed': 0, 'chunks_presented': 0, 'segments_committed': 0,
            'replay': read(tokenizer_parent / 'training_data.json'),
            'retention': read(tokenizer_parent / 'heldout_data.json'),
            'reservoir': [], 'dataset': str(DATASET), 'exhausted': False,
            'generation_quality_gate': 'unproven', 'live_activated': False}


def reserve_rows(corpus):
    # Persistent exact-target ownership prevents later articles leaking a held-out target.
    # This registry has no model authority; rerunning a rejected segment is idempotent.
    with sqlite3.connect(CAMPAIGN / 'target_splits.sqlite3') as db:
        db.execute('CREATE TABLE IF NOT EXISTS owners (digest TEXT PRIMARY KEY, split TEXT NOT NULL)')
        accepted, excluded = [], 0
        for row in corpus['rows']:
            keys = [hashlib.sha256(row[k].encode()).hexdigest() for k in ('original', 'reduced')]
            owners = [db.execute('SELECT split FROM owners WHERE digest=?', (key,)).fetchone() for key in keys]
            if any(owner and owner[0] != row['split'] for owner in owners):
                excluded += 1
                continue
            for key in keys:
                db.execute('INSERT OR IGNORE INTO owners VALUES (?,?)', (key, row['split']))
            accepted.append(row)
        corpus['rows'] = accepted
        corpus['cross_split_duplicates_excluded'] = excluded
    return corpus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--updates', type=int, default=1000)
    parser.add_argument('--articles', type=int, default=64)
    args = parser.parse_args()
    if not 1 <= args.updates <= 2000 or not 1 <= args.articles <= 256:
        raise ValueError('Bounded command: 1..2000 updates, 1..256 articles per prepared segment')
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    CAMPAIGN.mkdir(parents=True, exist_ok=True)
    with file_lock(ROOT / 'autonomy/inn_tokenizer_rebuild.lock'):
        _atomic_json(STATUS, {'stage': 'preparing', 'pid': os.getpid(), 'live_activated': False})
        if shutil.disk_usage(ROOT).free < 2 * 1024 ** 3:
            raise RuntimeError('L: has less than 2 GiB free; preserve the checkpoint and free space before continuing')
        store = Store()
        if store.get('enabled') or worker_alive() or store.get('gpu_training_active'):
            raise RuntimeError('Pause the Hive before running the isolated CPU INN campaign')
        head = read(HEAD) if HEAD.exists() else initial_head()
        if head['dataset'] != str(DATASET):
            raise ValueError('Dataset identity changed')
        if head['exhausted'] and not head['pending']:
            _atomic_json(STATUS, {'stage': 'dataset_pass_complete', 'pid': os.getpid(),
                'articles_completed': head['articles_completed'], 'chunks_presented': head['chunks_presented'],
                'cursor': head['cursor'], 'live_activated': False})
            print(json.dumps({'stage': 'dataset_pass_complete', 'articles': head['articles_completed']}))
            return
        parent = Path(head['checkpoint'])
        if digest(parent) != head['checkpoint_sha256']:
            raise ValueError('Campaign parent checkpoint hash mismatch')
        pointer = LEARNING / 'neural_admitted.json'
        admission_hash = digest(pointer)
        run = CAMPAIGN / 'runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        run.mkdir(parents=True)
        for path in (Path(__file__), ROOT / 'autonomy/wiki_stream.py', ROOT / 'INN/inn/language.py'):
            (run / path.name).write_bytes(path.read_bytes())
        if head['pending']:
            corpus_path = Path(head['pending']['path'])
            if digest(corpus_path) != head['pending']['sha256']:
                raise ValueError('Pending corpus changed')
            corpus = read(corpus_path)
        else:
            corpus = reserve_rows(prepare_segment(DATASET, head['cursor'], args.articles))
            corpus_path = run / 'corpus.json'
            _atomic_json(corpus_path, corpus)
        train = [{'prompt': '', 'target': r['reduced']} for r in corpus['rows'] if r['split'] == 'train']
        saved = torch.load(parent, map_location='cpu', weights_only=False)
        old_tokenizer = INNCharacterTokenizer.from_manifest(saved['language_contract']['tokenizer'])
        tokenizer = INNCharacterTokenizer.from_texts(list(old_tokenizer.characters) + [e['target'] for e in train])
        engine = LanguageEngine(copy.deepcopy(head['state']['config']), head['state']['engine'],
                                tokenizer=tokenizer, context_length=512, seed=812)
        engine.resume_character_parent(parent)
        optimizer_start = engine.optimizer_steps
        optimizer_before = copy.deepcopy(engine.optimizer.state_dict())
        # Continue the pilot learning rate, even across vocabulary growth.
        for group in engine.optimizer.param_groups:
            group['lr'] = .0002
        evaluation, excluded = {}, {}
        for split in ('validation', 'test'):
            evaluation[split], excluded[split] = [], 0
            for row in corpus['rows']:
                if row['split'] != split:
                    continue
                try:
                    tokenizer.encode(row['reduced'])
                except ValueError:
                    excluded[split] += 1
                    continue
                if len(evaluation[split]) < 32:
                    evaluation[split].append({'prompt': '', 'target': row['reduced']})
        before = {s: measure(engine, data) for s, data in evaluation.items() if data}
        status = {'stage': 'training', 'run': str(run), 'pid': os.getpid(), 'updates': 0,
                  'total_updates': args.updates, 'articles_completed': head['articles_completed'],
                  'segment_articles': len(corpus['sources']), 'segment_chunks': len(train),
                  'offset': head['offset'], 'cursor': head['cursor'], 'tokenizer_size': tokenizer.size,
                  'optimizer_start': optimizer_start, 'live_activated': False,
                  'chunks_presented': head['chunks_presented']}
        _atomic_json(STATUS, status)
        _atomic_json(run / 'protocol.json', {'parent': str(parent), 'parent_sha256': digest(parent),
            'corpus': str(corpus_path), 'corpus_sha256': digest(corpus_path), 'offset_start': head['offset'],
            'optimizer_start': optimizer_start, 'optimizer_state_entries': len(optimizer_before['state']),
            'tokenizer_old_size': old_tokenizer.size, 'tokenizer_new_size': tokenizer.size,
            'excluded_evaluation': excluded, 'before': before,
            'gate': 'finite updates, checkpoint reload identity, >=95% prior exact descriptions, immutable parent/admission',
            'scope': 'Experimental continuation; development prediction scores do not establish factual generation.'})
        started = time.monotonic()
        offset, steps = head['offset'], 0
        prior = head['replay']
        while steps < args.updates and offset < len(train):
            if time.monotonic() - started > 600:
                break
            if engine.optimizer_steps % 2:
                # Count replay updates rather than all updates; avoid skipping alternating blocks.
                start = ((engine.optimizer_steps // 2) * 8) % len(prior)
                batch = [prior[(start + i) % len(prior)] for i in range(min(8, len(prior)))]
            else:
                batch = train[offset:offset + 8]
                offset += len(batch)
                if head['reservoir']:
                    start = (engine.optimizer_steps // 2) % len(head['reservoir'])
                    batch += [head['reservoir'][(start + i) % len(head['reservoir'])] for i in range(2)]
            engine.train_joint(batch, [])
            steps += 1
            if steps % 25 == 0:
                status.update(updates=steps, offset=offset, loss=engine.loss,
                              optimizer_steps=engine.optimizer_steps)
                _atomic_json(STATUS, status)
        engine.save(run / 'engine.pt')
        after = {s: measure(engine, data) for s, data in evaluation.items() if data}
        retention = head['retention']
        retained = sum(engine.speak(e['prompt'], 80) == e['target'] for e in retention)
        generations = []
        for example in evaluation['test'][:4]:
            prompt = example['target'][:24]
            generations.append({'prompt': prompt, 'generated': engine.speak(prompt, 80), 'reference': example['target']})
        # Independently reload every candidate before committing weights and cursor together.
        reloaded = LanguageEngine(copy.deepcopy(head['state']['config']), head['state']['engine'],
                                  tokenizer=tokenizer, context_length=512, seed=812)
        reloaded.load(run / 'engine.pt')
        reload_identical = (reloaded.optimizer_steps == engine.optimizer_steps and
            all(torch.equal(v.cpu(), reloaded.model.state_dict()[k].cpu()) for k, v in engine.model.state_dict().items()) and
            all(reloaded.speak(g['prompt'], 80) == g['generated'] for g in generations))
        original_optimizer, loaded_optimizer = engine.optimizer.state_dict(), reloaded.optimizer.state_dict()
        optimizer_identical = original_optimizer['param_groups'] == loaded_optimizer['param_groups'] and all(
            torch.equal(value.cpu(), loaded_optimizer['state'][ident][key].cpu()) if torch.is_tensor(value)
            else value == loaded_optimizer['state'][ident][key]
            for ident, item in original_optimizer['state'].items() for key, value in item.items())
        reload_identical = reload_identical and optimizer_identical
        untouched = digest(parent) == head['checkpoint_sha256'] and digest(pointer) == admission_hash
        passed = retained / len(retention) >= .95 and reload_identical and untouched
        receipt = {'passed': passed, 'before': before, 'after': after, 'retained': retained,
            'retention_total': len(retention), 'reload_identical': reload_identical, 'parent_unchanged': untouched,
            'optimizer_reload_identical': optimizer_identical,
            'parent': str(parent), 'parent_sha256': head['checkpoint_sha256'],
            'checkpoint_sha256': digest(run / 'engine.pt'), 'optimizer_start': optimizer_start,
            'optimizer_end': engine.optimizer_steps, 'updates': steps, 'offset_start': head['offset'],
            'offset_end': offset, 'chunks_presented': offset - head['offset'], 'segment_complete': offset == len(train),
            'generations': generations, 'duration_seconds': time.monotonic() - started,
            'generation_quality_gate': 'unproven', 'live_activated': False}
        _atomic_json(run / 'evaluation.json', receipt)
        _atomic_json(run / 'tokenizer.json', tokenizer.manifest())
        if passed:
            next_head = copy.deepcopy(head)
            next_head.update(checkpoint=str(run / 'engine.pt'), checkpoint_sha256=receipt['checkpoint_sha256'],
                offset=offset, pending={'path': str(corpus_path), 'sha256': digest(corpus_path)},
                chunks_presented=head['chunks_presented'] + offset - head['offset'],
                segments_committed=head['segments_committed'] + 1, receipt=str(run / 'evaluation.json'))
            # Bounded deterministic replay reservoir of previously presented Wikipedia chunks.
            unique = {e['target']: e for e in head['reservoir'] + train[head['offset']:offset]}
            next_head['reservoir'] = [unique[t] for t in sorted(unique, key=lambda t: hashlib.sha256(t.encode()).hexdigest())[:256]]
            if offset == len(train):
                next_head.update(cursor=corpus['next_cursor'], pending=None, offset=0,
                    articles_completed=head['articles_completed'] + len(corpus['sources']),
                    files_completed=head['files_completed'] + corpus['scanned'], exhausted=corpus['exhausted'])
            # One atomic pointer is the commit; a crash before it leaves the old parent/cursor intact.
            _atomic_json(run / 'continuation.json', next_head)
            _atomic_json(HEAD, next_head)
            status.update(articles_completed=next_head['articles_completed'], cursor=next_head['cursor'],
                          chunks_presented=next_head['chunks_presented'], pending_offset=next_head['offset'])
        status.update(stage='paused_checkpoint' if passed else 'rejected_candidate', updates=steps, offset=offset,
                      optimizer_steps=engine.optimizer_steps, receipt=receipt)
        _atomic_json(STATUS, status)
        print(json.dumps({'run': str(run), 'stage': status['stage'], 'updates': steps,
                          'optimizer_start': optimizer_start, 'optimizer_end': engine.optimizer_steps,
                          'offset_start': head['offset'], 'offset_end': offset, 'retained': retained,
                          'after': after, 'articles_completed': status['articles_completed']}))
        if not passed:
            raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        if STATUS.exists():
            status = read(STATUS)
            if status.get('pid') == os.getpid() and status.get('stage') in ('training', 'preparing'):
                status.update(stage='error', error=f'{type(exc).__name__}: {exc}')
                _atomic_json(STATUS, status)
        raise
