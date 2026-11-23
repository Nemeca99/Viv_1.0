"""Independent reload check of the latest saved sentence candidate."""
import copy
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'INN')]
import torch
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer
from autonomy.train_inn_sentences import digest, measure, examples, LEARNING
from autonomy.inn_hive import _atomic_json


def main():
    torch.set_num_threads(2)
    status = json.loads((LEARNING / 'inn_sentence_status.json').read_text())
    run = Path(status['run'])
    receipt = json.loads((run / 'evaluation.json').read_text())
    protocol = json.loads((run / 'protocol.json').read_text())
    parent = Path(protocol['parent'])
    assert digest(parent / 'engine.pt') == protocol['parent_sha256']
    assert digest(run / 'engine.pt') == receipt['checkpoint_sha256']
    assert digest(run / 'corpus.json') == protocol['corpus_sha256']
    tokenizer = INNCharacterTokenizer.from_manifest(json.loads((run / 'tokenizer.json').read_text()))
    assert tokenizer.manifest()['sha256'] == receipt['tokenizer_sha256']
    admission = json.loads((LEARNING / 'neural_admitted.json').read_text())
    state = json.loads((Path(admission['run']) / 'parent.json').read_text())
    engine = LanguageEngine(copy.deepcopy(state['config']), state['engine'], tokenizer=tokenizer, context_length=512)
    engine.load(run / 'engine.pt')
    corpus = json.loads((run / 'corpus.json').read_text())
    data = []
    for example in examples([r for r in corpus['rows'] if r['split'] == 'test'], protocol['curriculum']):
        try:
            tokenizer.encode(example['prompt'] + example['target'])
        except ValueError:
            continue
        if len(example['prompt'] + example['target']) + 2 <= 512:
            data.append(example)
    measured = measure(engine, data)
    retention = json.loads((parent / 'heldout_data.json').read_text())
    retained = sum(engine.speak(e['prompt'], 80) == e['target'] for e in retention)
    outputs_equal = all(engine.speak(e['prompt'], 80) == e['generated'] for e in receipt['generations'])
    passed = abs(measured['nll'] - receipt['after']['test']['nll']) < 1e-6 and retained == receipt['retained'] and outputs_equal
    result = {'schema': 'inn_sentence_reload_recheck_v1', 'passed': passed,
              'measured_test': measured, 'retained': retained, 'generated_outputs_identical': outputs_equal,
              'checkpoint_integrity': True, 'tokenizer_integrity': True, 'corpus_integrity': True}
    _atomic_json(run / 'reload_recheck.json', result)
    print(json.dumps(result))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
