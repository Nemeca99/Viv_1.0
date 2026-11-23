"""Reuse the Hive QLoRA trainer with the immutable Rust farm corpus.

Preflight is the default. Training never changes the live Ollama model or admits
an adapter. The local 1.7B worker base cannot supply an adapter for the 8B Queen.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import hashlib
import json
import subprocess
import sys
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autonomy.farm_corpus import verify, sha
from autonomy.inn_hive import _atomic_json


def base_preflight(base):
    if base is None or not (base / 'config.json').is_file():
        return {'queen_compatible': False, 'reason': 'Local trainable Qwen3-8B base has not been supplied; the live Queen is GGUF.'}
    config = json.loads((base / 'config.json').read_text())
    index = base / 'model.safetensors.index.json'
    weights = set(json.loads(index.read_text())['weight_map'].values()) if index.is_file() else {'model.safetensors'}
    complete = all(Path(name).name == name and (base / name).is_file() for name in weights)
    architecture = (config.get('model_type') == 'qwen3' and config.get('hidden_size') == 4096
                    and config.get('num_hidden_layers') == 36)
    identity = config.get('_name_or_path', '')
    readme = base / 'README.md'
    if readme.is_file():
        identity += '\n' + readme.read_text(encoding='utf-8')[:12000]
    origin = 'Qwen/Qwen3-8B' in identity and 'DeepSeek' not in identity
    source_verified = False
    source_path = base / 'model_source.json'
    if complete and architecture and origin and source_path.is_file():
        source = json.loads(source_path.read_text())
        source_verified = (source.get('repo') == 'Qwen/Qwen3-8B' and source.get('source_hashes_verified') is True
                           and source['files']['config.json']['sha256'] == sha(base / 'config.json'))
        for name in sorted(weights) if source_verified else []:
            checksum = hashlib.sha256()
            with (base / name).open('rb') as stream:
                for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    checksum.update(chunk)
            source_verified = source_verified and checksum.hexdigest() == source['files'][name]['sha256']
    ready = complete and architecture and origin and source_verified
    return {'queen_compatible': bool(ready),
            'base': str(base.resolve()), 'config_sha256': sha(base / 'config.json'),
            'weights_complete': complete, 'architecture_matches_8b': architecture,
            'origin_identifies_qwen3_8b': origin,
            'upstream_source_hashes_rechecked': source_verified,
            'reason': 'Ready for an isolated training candidate; conversion compatibility still requires evaluation.'
                      if ready else 'Base weights or verified source hashes do not match the live Qwen3-8B Queen source.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', type=Path, default=ROOT / 'swarm_adapters/models/Qwen3-8B')
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--train', action='store_true')
    parser.add_argument('--gpu-phase', action='store_true')
    parser.add_argument('--steps', type=int, default=40)
    args = parser.parse_args()
    if not 1 <= args.steps <= 1000:
        raise ValueError('Use a bounded 1..1000 optimizer update budget')
    pointer = json.loads((ROOT / 'autonomy/learning/farm_corpus_latest.json').read_text())
    corpus = args.corpus or Path(pointer['folder'])
    manifest = verify(corpus)
    if not args.corpus and sha(corpus / 'manifest.json') != pointer['manifest_sha256']:
        raise ValueError('Corpus pointer manifest integrity failure')
    dependencies = {}
    for name in ('torch', 'transformers', 'peft', 'bitsandbytes', 'accelerate'):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = None
    import torch
    torch_distribution_version = dependencies['torch']
    dependencies['torch'] = torch.__version__
    base = base_preflight(args.base)
    gate_error = None
    try:
        from autonomy.farm_gpu_phase import ollama

        residents = ollama('ps', timeout=3).get('models', [])
        gpu_residents = [r['name'] for r in residents if r.get('size_vram', 0) > 0]
    except OSError as error:
        gate_error = f'{type(error).__name__}: {error}'
        gpu_residents = ['placement unavailable']
    except Exception as error:
        from aios_rebuild.main_core.mind_runtime_gate import BodyRuntimeHold, PrivacyEgressHold

        if not isinstance(error, (BodyRuntimeHold, PrivacyEgressHold)):
            raise
        gate_error = f'{type(error).__name__}: {error}'
        gpu_residents = ['placement unavailable']
    blockers = []
    if not base['queen_compatible']:
        blockers.append(base['reason'])
    if not all(dependencies.values()):
        blockers.append('Required Hive training dependencies are missing')
    if gate_error:
        blockers.append('AIOS Body or PrivacyCore held model-service access: ' + gate_error)
    if gpu_residents and not args.gpu_phase:
        blockers.append('GPU occupied by Ollama: ' + ', '.join(gpu_residents))
    command = [sys.executable, str(ROOT / 'swarm_adapters/train_adapter.py'),
               '--base', str(args.base), '--dataset', str(corpus / 'model_train.jsonl'),
               '--adapter-name', 'farm-queen', '--steps', str(args.steps), '--max-length', '512']
    command.extend(['--low-vram', '--gradient-accumulation-steps', '2'])
    receipt = {'schema': 'farm_queen_lora_preflight_v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
               'corpus_id': manifest['corpus_id'], 'corpus': str(corpus),
               'model_training_rows': manifest['model_rows'], 'base': base,
               'dependencies': dependencies, 'blockers': blockers, 'training_started': False,
               'torch_distribution_metadata': torch_distribution_version,
               'live_queen_weights_updated': False, 'admission': 'requires held-out legality and Rust farm comparisons'}
    path = ROOT / 'autonomy/learning/farm_adapter_status.json'
    _atomic_json(ROOT / 'autonomy/learning/farm_adapter_preflight.json', receipt)
    if args.train or not path.exists():
        _atomic_json(path, receipt)
    if args.train:
        if blockers:
            print(json.dumps(receipt, indent=2))
            raise SystemExit('Training blocked by recorded preflight; live Queen unchanged')
        output = ROOT / 'autonomy/learning/farm_adapter_runs' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        output.mkdir(parents=True)
        receipt.update(training_started=True, output=str(output), stage='training')
        _atomic_json(path, receipt)
        _atomic_json(output / 'corpus_receipt.json', receipt)
        from autonomy.farm_gpu_phase import gpu_training_phase, run_gpu_child
        try:
            with gpu_training_phase() if args.gpu_phase else nullcontext():
                code = run_gpu_child(command + ['--output', str(output / 'adapter')], cwd=ROOT, timeout=3600)
        except Exception as exc:
            receipt.update(stage='failed', error=f'{type(exc).__name__}: {exc}')
            _atomic_json(path, receipt)
            raise
        receipt.update(exit_code=code, stage='trained_candidate' if code == 0 else 'failed')
        _atomic_json(path, receipt)
        if code:
            raise SystemExit(code)
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
