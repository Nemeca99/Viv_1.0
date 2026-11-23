"""Inspect the tokenizer candidate's neural generation, without activation."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'INN'))
import torch
from inn.language import LanguageEngine
from inn.tokenizer import INNCharacterTokenizer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prompt', required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    learning = ROOT / 'autonomy/learning'
    status = json.loads((learning / 'inn_tokenizer_status.json').read_text())
    run = Path(status['run'])
    receipt = json.loads((run / 'evaluation.json').read_text())
    admission = json.loads((learning / 'neural_admitted.json').read_text())
    if admission['engine_sha256'] != receipt['parent_sha256']:
        raise ValueError('Current parent differs from candidate; inspect its lineage before use')
    checkpoint = run / 'engine.pt'
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != receipt['checkpoint_sha256']:
        raise ValueError('Candidate checkpoint integrity failure')
    state = json.loads((Path(admission['run']) / 'parent.json').read_text())
    tokenizer = INNCharacterTokenizer.from_manifest(json.loads((run / 'tokenizer.json').read_text()))
    if tokenizer.manifest()['sha256'] != receipt['tokenizer_sha256']:
        raise ValueError('Candidate tokenizer identity failure')
    engine = LanguageEngine(copy.deepcopy(state['config']), state['engine'], tokenizer=tokenizer,
                            context_length=512)
    engine.load(checkpoint)
    print(json.dumps({'candidate': str(run), 'gate_passed': receipt['passed'],
                      'prompt': args.prompt, 'generated': engine.speak(args.prompt, 80)}, ensure_ascii=True))


if __name__ == '__main__':
    main()
