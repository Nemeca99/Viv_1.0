"""Verify the shared corpus against both existing learning interfaces.

One INN optimizer step runs on an isolated copy and is discarded. The 1.7B
tokenizer verifies Hive chat formatting only; no Queen adapter is trained here.
"""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'INN'))
import torch
from transformers import AutoTokenizer
from inn.language import LanguageEngine
from swarm_adapters.train_adapter import ChatDataset
from autonomy.farm_corpus import verify, sha
from autonomy.inn_hive import _atomic_json


def main():
    torch.set_num_threads(2)
    learning = ROOT / 'autonomy/learning'
    pointer = json.loads((learning / 'farm_corpus_latest.json').read_text())
    folder = Path(pointer['folder'])
    manifest = verify(folder)
    if sha(folder / 'manifest.json') != pointer['manifest_sha256']:
        raise ValueError('Corpus pointer hash mismatch')
    admitted = json.loads((learning / 'neural_admitted.json').read_text())
    run = Path(admitted['run'])
    checkpoint = run / 'engine.pt'
    before_hash = sha(checkpoint)
    if before_hash != admitted['engine_sha256']:
        raise ValueError('Admitted parent hash mismatch')
    parent = json.loads((run / 'parent.json').read_text())
    engine = LanguageEngine(copy.deepcopy(parent['config']), copy.deepcopy(parent['engine']))
    engine.load(checkpoint)
    data = json.loads((folder / 'inn_train.json').read_text())
    before = engine.model.blocks[0].qkv.weight.detach().clone()
    before_steps = engine.optimizer_steps
    losses = engine.train_joint(data['language'][:16], data['actions'][:2])
    changed = not torch.equal(before, engine.model.blocks[0].qkv.weight)
    if not changed or engine.optimizer_steps != before_steps + 1:
        raise ValueError('Shared corpus did not drive an internal INN optimizer update')
    base = ROOT / 'swarm_adapters/models/Qwen3-1.7B'
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    dataset = ChatDataset(folder / 'model_train.jsonl', tokenizer, 512)
    if dataset.context_truncated_rows or len(dataset) != manifest['model_rows']:
        raise ValueError('Model corpus row count or context mismatch')
    if sha(checkpoint) != before_hash:
        raise ValueError('Admitted checkpoint changed during isolated verification')
    receipt = {'schema': 'farm_shared_corpus_interface_verification_v1',
               'at_utc': datetime.now(timezone.utc).isoformat(), 'corpus_id': manifest['corpus_id'],
               'manifest_sha256': sha(folder / 'manifest.json'),
               'inn_shared_attention_updated_on_isolated_copy': changed,
               'isolated_optimizer_steps': 1, 'isolated_losses': losses,
               'admitted_checkpoint_unchanged': True,
               'hive_chat_rows_validated': len(dataset),
               'minimum_supervised_tokens': min(dataset.supervised_token_counts),
               'context_truncated_rows': dataset.context_truncated_rows,
               'format_check_tokenizer': str(base),
               'queen_adapter_trained': False, 'learning_improvement_proven_by_this_check': False}
    _atomic_json(learning / 'farm_corpus_verification.json', receipt)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
