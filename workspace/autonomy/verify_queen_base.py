"""Pin and verify the official local Qwen3-8B training source."""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'b968826d9c46dd6066d109eabc6255188de91218'
BASE = ROOT / 'swarm_adapters/models/Qwen3-8B'


def main():
    info = HfApi().model_info('Qwen/Qwen3-8B', revision=REVISION, files_metadata=True)
    required = {'config.json', 'generation_config.json', 'tokenizer.json', 'tokenizer_config.json',
                'model.safetensors.index.json', 'merges.txt', 'vocab.json', 'README.md', 'LICENSE'}
    required.update(json.loads((BASE / 'model.safetensors.index.json').read_text())['weight_map'].values())
    hashes = {}
    for item in info.siblings:
        if item.rfilename not in required:
            continue
        path = BASE / item.rfilename
        result = hashlib.sha256()
        git = hashlib.sha1(f'blob {item.size}\0'.encode())
        if path.stat().st_size != item.size:
            raise ValueError(f'Size mismatch: {path.name}')
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                result.update(chunk)
                git.update(chunk)
        expected = item.lfs.sha256 if item.lfs else item.blob_id
        actual = result.hexdigest() if item.lfs else git.hexdigest()
        if actual != expected:
            raise ValueError(f'Upstream hash mismatch: {path.name}')
        hashes[item.rfilename] = {'size': item.size, 'sha256': result.hexdigest(), 'upstream_hash': expected}
        print(f'Verified {path.name}', flush=True)
    if set(hashes) != required:
        raise ValueError('Required training files missing from official source')
    request = Request('http://127.0.0.1:11434/api/show', data=b'{"model":"qwen3:8b-local"}',
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=10) as response:
        queen = json.load(response)
    config = json.loads((BASE / 'config.json').read_text())
    model_info = queen['model_info']
    if (config['num_hidden_layers'] != model_info.get('qwen3.block_count')
            or config['hidden_size'] != model_info.get('qwen3.embedding_length')
            or queen['details']['parent_model'] != 'qwen3:8b'):
        raise ValueError('Training source architecture differs from the live Queen')
    receipt = {'schema': 'queen_training_source_v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
               'repo': 'Qwen/Qwen3-8B', 'revision': info.sha, 'files': hashes,
               'queen_details': queen['details'], 'queen_block_count': model_info['qwen3.block_count'],
               'queen_embedding_length': model_info['qwen3.embedding_length'],
               'source_hashes_verified': True, 'architecture_matches_live_queen': True,
               'scope': 'official source and matching architecture; quantized GGUF tensor equality not claimed'}
    (BASE / 'model_source.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'revision': info.sha, 'files_verified': len(hashes),
                      'total_bytes': sum(r['size'] for r in hashes.values()), 'architecture_matches': True}))


if __name__ == '__main__':
    main()
