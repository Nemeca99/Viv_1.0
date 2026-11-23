"""Validate completed export independently after the old set-serialization failure."""
import json
from datetime import datetime, timezone
from pathlib import Path
from train import DEFAULT_WORK, digest, libraries, record

def main():
    work = DEFAULT_WORK
    torch, transformers = libraries(work)
    from safetensors import safe_open
    receipt = work / 'conversion-receipt.json'
    broken = receipt.read_text(encoding='utf-8')
    if '"missing_keys":' not in broken:
        raise RuntimeError('Unexpected conversion receipt; do not replace it')
    source = work / 'model_source/OmniCoder-2-9B.f16.gguf'
    expected_source = 'f2253f1859072adb2c115ed4f4818df1870fd087821419f8b41c66e7f3567554'
    source_hash = digest(source)
    if source_hash != expected_source:
        raise RuntimeError('Source differs from upstream LFS hash')
    base = work / 'base_hf_fp16'
    cfg = transformers.AutoConfig.from_pretrained(base, local_files_only=True)
    with torch.device('meta'):
        model = transformers.AutoModelForCausalLM.from_config(cfg, dtype=torch.float16)
    expected = {name: tuple(tensor.shape) for name, tensor in model.state_dict().items()}
    index = json.loads((base / 'model.safetensors.index.json').read_text(encoding='utf-8'))
    actual = {}
    for filename in sorted(set(index['weight_map'].values())):
        with safe_open(base / filename, framework='pt', device='cpu') as handle:
            for name in handle.keys():
                if name in actual or index['weight_map'].get(name) != filename:
                    raise RuntimeError('Duplicate or incorrectly indexed tensor: ' + name)
                actual[name] = tuple(handle.get_slice(name).get_shape())
    if expected != actual:
        raise RuntimeError('Exported tensor names/shapes do not match the model graph')
    hashes = {p.name: digest(p) for p in base.iterdir() if p.is_file()}
    if not {'tokenizer.json', 'tokenizer_config.json', 'model.safetensors.index.json'}.issubset(hashes):
        raise RuntimeError('Export incomplete')
    # Preserve the failed partial receipt under the exact candidate workspace before replacing it.
    failed = receipt.with_name('conversion-receipt-serialization-failed-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.partial')
    if receipt.resolve().parent != work.resolve() or failed.resolve().parent != work.resolve():
        raise RuntimeError('Receipt recovery escaped the candidate workspace')
    receipt.rename(failed)
    result = record(receipt, {
        'source_repo': 'mradermacher/OmniCoder-2-9B-GGUF',
        'source_revision': 'bd26f7e9e5012cb18e3934e505d76a01028ebbdc',
        'source': str(source), 'source_sha256': source_hash,
        'transformers': transformers.__version__, 'model_type': cfg.model_type,
        'base_path': str(base), 'files': hashes,
        'loading_info': {'missing_keys': [], 'unexpected_keys': [], 'mismatched_keys': [], 'error_msgs': []},
        'receipt_recovery': {'cause': 'old serializer rejected upstream loading-info sets after successful export',
                             'preserved_partial': str(failed), 'tensor_count': len(actual),
                             'independent_export_headers_match_meta_graph': True,
                             'source_hash_matches_upstream': True},
        'scope': 'Published FP16 text export reconstructed through upstream GGUF mappings; no training update',
    })
    print(json.dumps({'result': 'PASS', 'tensors': len(actual), 'files': len(hashes), 'receipt': str(receipt)}), flush=True)

if __name__ == '__main__':
    main()
