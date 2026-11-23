"""Independent campaign head reload and continuation evidence check."""
import copy
import json
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1] / 'INN')]
import torch
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from autonomy.train_inn_wikipedia import HEAD, read
from autonomy.train_inn_sentences import digest, measure
from autonomy.inn_hive import _atomic_json


def main():
    torch.set_num_threads(2)
    head = read(HEAD)
    path = Path(head['checkpoint'])
    run = path.parent
    receipt = read(run / 'evaluation.json')
    protocol = read(run / 'protocol.json')
    checkpoint = torch.load(path, map_location='cpu', weights_only=False)
    parent = torch.load(receipt['parent'], map_location='cpu', weights_only=False)
    tokenizer = INNCharacterTokenizer.from_manifest(checkpoint['language_contract']['tokenizer'])
    engine = LanguageEngine(copy.deepcopy(head['state']['config']), head['state']['engine'],
                            tokenizer=tokenizer, context_length=512, seed=812)
    engine.load(path)
    corpus = read(protocol['corpus'])
    evaluation = []
    for row in corpus['rows']:
        if row['split'] != 'test':
            continue
        try:
            tokenizer.encode(row['reduced'])
        except ValueError:
            continue
        if len(evaluation) < 32:
            evaluation.append({'prompt': '', 'target': row['reduced']})
    score = measure(engine, evaluation) if evaluation else None
    retained = sum(engine.speak(e['prompt'], 80) == e['target'] for e in head['retention'])
    checks = {
        'head_checkpoint_hash': digest(path) == head['checkpoint_sha256'] == receipt['checkpoint_sha256'],
        'parent_hash': digest(Path(receipt['parent'])) == receipt['parent_sha256'],
        'corpus_hash': digest(Path(protocol['corpus'])) == protocol['corpus_sha256'],
        'continued_optimizer': parent['optimizer_steps'] == receipt['optimizer_start'] and
            engine.optimizer_steps == receipt['optimizer_end'] == receipt['optimizer_start'] + receipt['updates'],
        'continued_chunk_offset': receipt['offset_start'] == protocol['offset_start'] and
            receipt['offset_end'] - receipt['offset_start'] == receipt['chunks_presented'],
        'retention_matches': retained == receipt['retained'],
        'nll_matches': score is None or abs(score['nll'] - receipt['after']['test']['nll']) < 1e-6,
        'generations_match': all(engine.speak(g['prompt'], 80) == g['generated'] for g in receipt['generations']),
        'finite_weights': all(torch.isfinite(t).all().item() for t in engine.model.state_dict().values()),
        'committed_passed_candidate': receipt['passed'] is True,
    }
    result = {'passed': all(checks.values()), 'checks': checks, 'test': score,
              'retained': retained, 'optimizer_steps': engine.optimizer_steps,
              'articles_completed': head['articles_completed'], 'cursor': head['cursor'],
              'generation_quality_gate': 'unproven'}
    _atomic_json(run / 'independent_recheck.json', result)
    print(json.dumps(result))
    if not result['passed']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
