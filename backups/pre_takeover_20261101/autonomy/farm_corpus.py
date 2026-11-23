"""Immutable Rust-derived corpus with INN and Hive LoRA views of the same facts.

No Queen prose is admitted as a target. Reserved plot identities never enter
training. Language here describes tool legality; it does not prove game mastery.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEARNING = ROOT / 'autonomy' / 'learning'
RESERVED = {21, 41}
FACT = re.compile(r'^plot=(\d+) stage=(\w+) tool=(\w+)\nDescribe:\n$')
PROVENANCE = {'live Rust counterfactual', 'Rust execution on isolated queue-cleared clone',
              'Rust execution at actual FIFO boundary'}


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_fact(row, training=True):
    match = FACT.fullmatch(row['prompt'])
    if not match or (training and int(match[1]) in RESERVED):
        raise ValueError('Invalid prompt or reserved plot in training corpus')
    allowed = {f'{match[3]} is {legal} on {match[2]}.' for legal in ('legal', 'illegal')}
    if row['target'] not in allowed:
        raise ValueError('Target does not match Rust fact format')
    if row.get('provenance') not in PROVENANCE or not row.get('state_sha256'):
        raise ValueError('Missing Rust source provenance')
    return row


def chat(row):
    return {'messages': [
        {'role': 'system', 'content': 'Describe the supplied farm tool legality. Reply with one factual sentence.'},
        {'role': 'user', 'content': row['prompt']},
        {'role': 'assistant', 'content': row['target']}],
        'source_id': hashlib.sha256(encoded([row['prompt'], row['target']])).hexdigest()}


def publish(language, actions, output, sources=None, writer=None):
    # Conflicting targets for the same state description need a richer prompt,
    # not silent majority voting or last-write-wins supervision.
    facts = {}
    for row in language:
        check_fact(row)
        if row['prompt'] in facts and facts[row['prompt']]['target'] != row['target']:
            raise ValueError('Conflicting Rust targets: enrich the state prompt before training')
        facts.setdefault(row['prompt'], row)
    language = [facts[key] for key in sorted(facts)]
    for sample in actions:
        if any(int(item['a']) in RESERVED or int(item.get('b', 0)) in RESERVED for item in sample['items']):
            raise ValueError('Reserved plot in action training')
        if len(sample['items']) != len(sample['legal']):
            raise ValueError('Mismatched action legality labels')
        if any(value not in (0, 1) for value in sample['legal']):
            raise ValueError('Invalid action legality label')
        if sample.get('oracle_improved'):
            best = sample.get('best')
            if not isinstance(best, int) or not 0 <= best < len(sample['items']) or not sample['legal'][best]:
                raise ValueError('Improved strategy target must reference a legal action')
    internal = {'language': language, 'actions': actions}
    model_rows = [chat(row) for row in language]
    # Counterfactual contexts teach legal choices. Strategic targets are admitted
    # only when the recorded Rust lookahead measured a strict improvement.
    for sample in actions:
        choices = [{k: item[k] for k in ('t', 'a', 'b', 'stage')} for item in sample['items']]
        target = {'legal': [bool(value) for value in sample['legal']]}
        if sample.get('oracle_improved') and sample.get('oracle_horizon') == 12:
            target['best_index_over_12_ticks'] = sample['best']
        payload = {'candidates': choices, 'horizon_ticks': 12 if 'best_index_over_12_ticks' in target else 0}
        row = {'messages': [
            {'role': 'system', 'content': 'Return JSON listing candidate legality. When requested, identify the measured best candidate over the stated horizon.'},
            {'role': 'user', 'content': json.dumps(payload, sort_keys=True)},
            {'role': 'assistant', 'content': json.dumps(target, sort_keys=True)}]}
        row['source_id'] = hashlib.sha256(encoded(sample)).hexdigest()
        model_rows.append(row)
    unique = {hashlib.sha256(encoded(row)).hexdigest(): row for row in model_rows}
    files = {'inn_train.json': encoded(internal),
             'model_train.jsonl': b''.join(encoded(unique[key]) for key in sorted(unique))}
    identity = hashlib.sha256(b''.join(name.encode() + content for name, content in sorted(files.items()))).hexdigest()
    folder = output / identity
    manifest = {'schema': 'rust_farm_shared_corpus_v1', 'corpus_id': identity,
                'language_facts': len(language), 'action_contexts': len(actions),
                'model_rows': len(unique), 'reserved_training_plots': sorted(RESERVED),
                'scope': 'tool legality and recorded 12-tick improvements; no general language claim',
                'queen_prose_is_supervision': False, 'sources': sources or {},
                'files': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}}
    if writer is None:
        folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = folder / name
        if path.exists() and path.read_bytes() != content:
            raise ValueError('Immutable corpus collision')
        if not path.exists() and writer is None:
            path.write_bytes(content)
        elif not path.exists():
            writer(path, content)
    path = folder / 'manifest.json'
    if not path.exists() and writer is None:
        path.write_bytes(encoded(manifest))
    elif not path.exists():
        writer(path, encoded(manifest))
    verify(folder)
    return folder


def verify(folder):
    manifest = json.loads((folder / 'manifest.json').read_text())
    for name, expected in manifest['files'].items():
        if Path(name).name != name or sha(folder / name) != expected:
            raise ValueError('Corpus file integrity failure')
    data = json.loads((folder / 'inn_train.json').read_text())
    for row in data['language']:
        check_fact(row)
    identity = hashlib.sha256(b''.join(name.encode() + (folder / name).read_bytes()
                                     for name in sorted(manifest['files']))).hexdigest()
    if identity != manifest['corpus_id'] or folder.name != identity:
        raise ValueError('Corpus identity mismatch')
    return manifest


def from_run(run, output):
    data = json.loads((run / 'training_data.json').read_text())
    live = LEARNING / 'neural_live_examples.json'
    language = list(data['language'])
    sources = {str(run / 'training_data.json'): sha(run / 'training_data.json')}
    if live.exists():
        content = live.read_bytes()
        sources[str(live)] = hashlib.sha256(content).hexdigest()
        language.extend(row for row in json.loads(content).values()
                        if int(FACT.fullmatch(row['prompt'])[1]) not in RESERVED)
    return publish(language, data['actions'], output, sources)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify(args.verify), indent=2))
        return
    run = args.run or Path(json.loads((LEARNING / 'neural_admitted.json').read_text())['run'])
    folder = from_run(run, LEARNING / 'farm_corpus')
    pointer = {'folder': str(folder), 'manifest_sha256': sha(folder / 'manifest.json'), **verify(folder)}
    from autonomy.inn_hive import _atomic_json
    _atomic_json(LEARNING / 'farm_corpus_latest.json', pointer)
    print(json.dumps(pointer, indent=2))


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(ROOT))
    main()
