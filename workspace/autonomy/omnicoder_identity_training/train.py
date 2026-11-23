"""Bounded local Viv open-inquiry QLoRA rounds with immutable data and Rust-run probes.

Outputs are candidates. This program never activates a model or writes live memory/SQLite.
"""
import argparse
import gc
import hashlib
import json
import os
import random
import shutil
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
DEFAULT_WORK = Path('E:/Viv_Sandbox/omnicoder_identity_20261118')
ACTIVE = {}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def record(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False,
                  default=lambda item: sorted(item) if isinstance(item, set) else str(item) if isinstance(item, Path) else (_ for _ in ()).throw(TypeError(type(item).__name__)))
    return value

def event(work, kind, **fields):
    value = {'utc': datetime.now(timezone.utc).isoformat(), 'event': kind, **fields}
    with (work / 'events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
    print(json.dumps(value, ensure_ascii=False), flush=True)

def libraries(work):
    sys.path.insert(0, str(work / 'packages'))
    os.environ.update(HF_HOME=str(work / 'cache'), HF_HUB_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1',
                      TOKENIZERS_PARALLELISM='false', TEMP=str(work / 'tmp'), TMP=str(work / 'tmp'))
    import torch
    import transformers
    return torch, transformers

def convert(work):
    torch, transformers = libraries(work)
    source = work / 'model_source' / 'OmniCoder-2-9B.f16.gguf'
    if not source.is_file():
        raise FileNotFoundError('Matching full-precision OmniCoder export is not downloaded: ' + str(source))
    destination = work / 'base_hf_fp16'
    if (work / 'conversion-receipt.json').exists():
        old = json.loads((work / 'conversion-receipt.json').read_text(encoding='utf-8'))
        if old['source_sha256'] != 'f2253f1859072adb2c115ed4f4818df1870fd087821419f8b41c66e7f3567554':
            raise RuntimeError('Source export does not match the pinned upstream LFS hash')
        if old['source_sha256'] != digest(source):
            raise RuntimeError('Original GGUF changed after conversion')
        if not all(digest(destination / p) == h for p, h in old['files'].items()):
            raise RuntimeError('Converted base changed')
        return old
    if destination.exists() and any(destination.iterdir()):
        raise RuntimeError('Incomplete conversion retained; choose a fresh work directory')
    event(work, 'conversion_started', source=str(source))
    torch.set_num_threads(4)
    model, loading_info = transformers.AutoModelForCausalLM.from_pretrained(
        str(source.parent), gguf_file=source.name,
        quantization_config=transformers.GgufConfig(dequantize=True),
        dtype=torch.float16, device_map='cpu',
        local_files_only=True, attn_implementation='sdpa', output_loading_info=True)
    if loading_info.get('missing_keys') or loading_info.get('mismatched_keys') or loading_info.get('error_msgs'):
        raise RuntimeError('Incomplete model reconstruction: ' + str(loading_info))
    if any(not key.startswith('mtp.') for key in loading_info.get('unexpected_keys', [])):
        raise RuntimeError('Unmapped source tensors: ' + str(loading_info))
    tokenizer = transformers.AutoTokenizer.from_pretrained(str(source.parent), gguf_file=source.name,
                                                          local_files_only=True)
    if not tokenizer.chat_template:
        raise RuntimeError('Source tokenizer has no chat template; refusing an invented template')
    if model.config.model_type != 'qwen3_5_text' or model.config.num_hidden_layers != 32:
        raise RuntimeError('Unexpected matching-model architecture')
    destination.mkdir(exist_ok=True)
    model.save_pretrained(destination, safe_serialization=True, max_shard_size='1GB')
    tokenizer.save_pretrained(destination)
    info = record(work / 'conversion-receipt.json', {
        'source_repo': 'mradermacher/OmniCoder-2-9B-GGUF',
        'source_revision': 'bd26f7e9e5012cb18e3934e505d76a01028ebbdc',
        'source': str(source), 'source_sha256': digest(source),
        'transformers': transformers.__version__, 'model_type': model.config.model_type,
        'base_path': str(destination), 'loading_info': loading_info,
        'files': {p.name: digest(p) for p in destination.iterdir() if p.is_file()},
        'scope': 'Published FP16 text export reconstructed using upstream GGUF mappings; vision supplement untouched',
    })
    del model
    gc.collect()
    event(work, 'conversion_complete', receipt=str(work / 'conversion-receipt.json'))
    return info

def render(tokenizer, rows, limit=256):
    import torch
    result = []
    skipped = 0
    for row in rows:
        messages = row['messages']
        prefix = tokenizer.apply_chat_template(messages[:-1], tokenize=True,
                                              add_generation_prompt=True, enable_thinking=False)
        full = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False,
                                            enable_thinking=False)
        if isinstance(prefix, Mapping):
            prefix = prefix['input_ids']
        if isinstance(full, Mapping):
            full = full['input_ids']
        if len(full) > limit:
            # Recorded grounding episodes include evidence blocks far longer than this
            # budget. Dropping and counting is honest; truncating would break the gold
            # answer, which quotes a required term from further down the block.
            skipped += 1
            continue
        if full[:len(prefix)] != prefix:
            raise RuntimeError('Incompatible assistant prefix: ' + row['id'] + ':' + repr((prefix[-12:], full[len(prefix)-12:len(prefix)+4])))
        labels = [-100] * len(prefix) + full[len(prefix):]
        if not any(v != -100 for v in labels):
            raise RuntimeError('No assistant target tokens: ' + row['id'])
        result.append({'input_ids': torch.tensor(full), 'attention_mask': torch.ones(len(full), dtype=torch.long),
                       'labels': torch.tensor(labels)})
    return result, skipped

def infer(model, tokenizer, probes, torch, work, name):
    model.eval()
    outputs = []
    for row in probes:
        encoded = tokenizer.apply_chat_template(row['messages'], tokenize=True, add_generation_prompt=True,
                                               enable_thinking=False, return_tensors='pt')
        if isinstance(encoded, Mapping):
            encoded = encoded['input_ids']
        encoded = encoded.to('cuda')
        with torch.inference_mode():
            answer = model.generate(encoded, attention_mask=torch.ones_like(encoded), do_sample=False,
                                    max_new_tokens=192 if row['category'] == 'coding' else 96,
                                    pad_token_id=tokenizer.pad_token_id, eos_token_id=tokenizer.eos_token_id,
                                    use_cache=True)
        text = tokenizer.decode(answer[0, encoded.shape[-1]:], skip_special_tokens=True)
        outputs.append({**row, 'output': text})
        event(work, 'probe_generated', run=name, probe=row['id'])
    return outputs

def verify(outputs, manifest, baseline_coding, name, work):
    fixtures = PROJECT / '.opencode/evals/viv-identity' / name
    if fixtures.exists():
        # Never overwrite a retained fixture: a retried run must not destroy the record
        # of the attempt it is retrying. Suffix instead of reusing.
        name = name + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        fixtures = PROJECT / '.opencode/evals/viv-identity' / name
    fixtures.mkdir(parents=True, exist_ok=False)
    suite = fixtures / 'suite.json'
    checker = fixtures / 'check_generated.py'
    record(suite, {'outputs': outputs, 'criteria': manifest['criteria'], 'baseline_coding': baseline_coding})
    shutil.copyfile(HERE / 'check_generated.py', checker)
    relative_suite = suite.relative_to(PROJECT).as_posix()
    relative_checker = checker.relative_to(PROJECT).as_posix()
    contract = {'version': 1, 'kind': 'artifacts', 'artifacts': [relative_suite, relative_checker],
                'checks': [{'id': 'unseen-identity-behavior-and-code',
                            'argv': ['/usr/local/bin/python', '-B', relative_checker, relative_suite],
                            'timeout_seconds': 25, 'inputs': [relative_checker, relative_suite]}],
                'frozen_inputs': {relative_checker: digest(checker), relative_suite: digest(suite)}}
    sys.path.insert(0, str(HERE.parent / 'aios_router_mcp_v3_postal_candidate'))
    from completion_authority import execute
    image = json.loads((PROJECT / 'opencode.json').read_text(encoding='utf-8-sig'))['mcp']['servers']['aios_router']['command'][-1]
    evidence = execute(contract, image)
    record(work / (name + '-rust-verification.json'), evidence)
    stdout = evidence['evidence']['checks'][0]['stdout']
    if stdout['truncated']:
        raise RuntimeError('Rust probe output was truncated; preserve the result and revise reporting')
    score = json.loads(stdout['excerpt'].strip())
    event(work, 'probes_verified', run=name, scores=score['scores'], passed=score['passed'])
    return score, evidence

def train(args):
    work = args.work
    from curriculum_runtime import prepare_v4, prepare_v5
    from curriculum_grounding import prepare as prepare_grounding
    from curriculum_persona import prepare as prepare_persona
    builders = {'v4': prepare_v4, 'v5': prepare_v5, 'v6': prepare_grounding,
                'v7': lambda dest: prepare_grounding(dest, schema='viv_grounding_episodes_v7', mismatch_train=200),
                'v8': lambda dest: prepare_grounding(dest, schema='viv_grounding_episodes_v8', mismatch_train=750),
                'v9': lambda dest: prepare_grounding(dest, schema='viv_grounding_episodes_v9', mismatch_train=350),
                'v10': lambda dest: prepare_grounding(dest, schema='viv_grounding_episodes_v10', mismatch_train=350, prose_mismatch=True),
                'persona': prepare_persona}
    data_root = work / f'data_runtime_{args.curriculum}'
    manifest = builders[args.curriculum](data_root)
    low, high = (int(part) for part in args.lora_layers.split('-'))
    if not 0 <= low <= high <= 35:
        raise RuntimeError('Adapter layer range must be an ascending layer pair within 0-35: ' + args.lora_layers)
    layer_range = range(low, high + 1)
    if args.base_hf:
        base_path = Path(args.base_hf)
        if not (base_path / 'config.json').is_file():
            raise RuntimeError('Base model directory missing config.json: ' + str(base_path))
    else:
        base_info = convert(work)
        base_path = Path(base_info['base_path'])
    torch, transformers = libraries(work)
    import bitsandbytes as bnb
    from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required; CPU training is not a substitute')
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    torch.manual_seed(20261118)
    random.seed(20261118)
    torch.set_num_threads(4)
    tokenizer = transformers.AutoTokenizer.from_pretrained(base_path, local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    quant = transformers.BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                           bnb_4bit_compute_dtype=dtype, bnb_4bit_use_double_quant=True,
                                           llm_int8_skip_modules=[], llm_int8_enable_fp32_cpu_offload=True)
    event(work, 'gpu_load_started', gpu=torch.cuda.get_device_name(0), free_bytes=torch.cuda.mem_get_info()[0])
    model = transformers.AutoModelForCausalLM.from_pretrained(base_path, local_files_only=True,
                                                            quantization_config=quant, dtype=dtype,
                                                            device_map={'model.embed_tokens': 'cpu', 'model.layers': 0,
                                                                        'model.norm': 0, 'lm_head': 0},
                                                            attn_implementation='sdpa')
    # Stage the two-GiB embedding on CPU while the large output head is quantized.
    # Afterwards all execution is on the GPU; no persistent CPU-offload hooks remain.
    from accelerate.hooks import remove_hook_from_module
    remove_hook_from_module(model, recurse=True)
    model.get_input_embeddings().to(device='cuda', dtype=dtype)
    model.hf_device_map = {'': 0}
    event(work, 'gpu_load_complete', allocated_bytes=torch.cuda.memory_allocated(),
          head_type=type(model.lm_head).__name__)
    # A 248k-token FP32 head/embedding would consume most of this eight-GiB GPU.
    if not isinstance(model.lm_head, bnb.nn.Linear4bit):
        raise RuntimeError('Output projection was not quantized; refusing an unbounded memory configuration')
    train_rows = [json.loads(line) for line in (data_root / 'train.jsonl').read_text(encoding='utf-8').splitlines()]
    probes = [json.loads(line) for line in (data_root / 'heldout.jsonl').read_text(encoding='utf-8').splitlines()]
    def prompt_length(row):
        out = tokenizer.apply_chat_template(row['messages'], tokenize=True, add_generation_prompt=True, enable_thinking=False)
        if isinstance(out, Mapping):
            out = out['input_ids']
        if isinstance(out, list) and out and isinstance(out[0], list):
            out = out[0]
        return len(list(out))
    kept_probes = [row for row in probes if prompt_length(row) <= args.max_prompt_tokens]
    if not kept_probes:
        raise RuntimeError('No probe fits the prompt budget of ' + str(args.max_prompt_tokens))
    event(work, 'probes_selected', kept=len(kept_probes), skipped=len(probes) - len(kept_probes),
          limit=args.max_prompt_tokens)
    probes = kept_probes
    rows, skipped = render(tokenizer, train_rows, args.max_tokens)
    if not rows:
        raise RuntimeError('No training row fits the token budget of ' + str(args.max_tokens))
    event(work, 'training_rows_selected', kept=len(rows), skipped=skipped, limit=args.max_tokens)
    baseline_path = work / f'baseline-score-{args.curriculum}.json'
    if args.resume_adapter:
        baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        model = PeftModel.from_pretrained(model, args.resume_adapter, is_trainable=True, local_files_only=True)
    else:
        if baseline_path.exists():
            if not args.reuse_baseline:
                raise RuntimeError('Existing campaign retained. Resume its adapter or choose a fresh work directory')
            # The base model and probes are unchanged, so the recorded baseline is still
            # the correct reference for a new adapter configuration.
            baseline = json.loads(baseline_path.read_text(encoding='utf-8'))
        else:
            score, evidence = verify(infer(model, tokenizer, probes, torch, work, f'baseline-{args.curriculum}'), manifest, 0, f'baseline-{args.curriculum}', work)
            baseline = record(baseline_path, score)
        embeddings = [module for module in model.modules() if isinstance(module, torch.nn.Embedding)]
        for module in embeddings:
            module.to('cpu')
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=False)
        for module in embeddings:
            module.to(device='cuda', dtype=dtype)
        targets = [name for name, module in model.named_modules()
                   if any(f'.layers.{index}.' in name for index in layer_range)
                   and name.endswith(('.q_proj', '.v_proj', '.in_proj_qkv', '.in_proj_z'))]
        if not targets:
            raise RuntimeError('No matching late-layer adapter targets')
        model = get_peft_model(model, LoraConfig(r=args.lora_r, lora_alpha=args.lora_r * 2, lora_dropout=0.05,
                                               bias='none', task_type='CAUSAL_LM', target_modules=targets))
    trainable = [p for p in model.parameters() if p.requires_grad]
    if not trainable:
        raise RuntimeError('No trainable adapter parameters')
    if any(p.requires_grad for n, p in model.named_parameters() if 'lora_' not in n):
        raise RuntimeError('The original base must remain frozen')
    optimizer = torch.optim.AdamW(trainable, lr=args.learning_rate, weight_decay=0.01)
    # Reuse the installed project trainer's padding/masking contract without its unrelated base/outputs.
    sys.path.insert(0, str(PROJECT / 'workspace/aios_rebuild'))
    from train_real_lora import PadCollator
    collate = PadCollator(tokenizer.pad_token_id)
    campaign = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    previous = None
    for round_index in range(args.rounds):
        name = campaign + f'-round-{round_index + 1}'
        output_dir = work / 'runs' / name
        output_dir.mkdir(parents=True, exist_ok=False)
        ACTIVE.update(model=model, output_dir=output_dir, completed_steps=0)
        before = {n: digest_bytes(p.detach().float().cpu().numpy().tobytes())
                  for n, p in model.named_parameters() if p.requires_grad}
        event(work, 'training_started', run=name, steps=args.steps, trainable=sum(p.numel() for p in trainable),
              curriculum_sha256=manifest['sha256'], targets=model.peft_config['default'].target_modules.__str__())
        started = time.monotonic()
        model.train()
        model.config.use_cache = False
        losses = []
        optimizer.zero_grad(set_to_none=True)
        for step in range(args.steps):
            if (work / 'STOP').exists() or time.monotonic() - started > args.max_minutes * 60:
                model.save_pretrained(output_dir / 'interrupted-adapter', safe_serialization=True)
                record(output_dir / 'interrupted.json', {'completed_steps': step, 'reason': 'stop file or time bound'})
                return 2
            step_loss = 0.0
            for _ in range(4):
                batch = {k: v.to('cuda') for k, v in collate([random.choice(rows)]).items()}
                base = model.get_base_model()
                hidden = base.model(input_ids=batch['input_ids'], attention_mask=batch['attention_mask'],
                                    use_cache=False).last_hidden_state
                # Compute logits only for supervised assistant tokens, retaining exact causal alignment.
                labels = batch['labels'][:, 1:]
                keep = labels != -100
                logits = base.lm_head(hidden[:, :-1][keep].to(dtype))
                loss = torch.nn.functional.cross_entropy(logits.float(), labels[keep]) / 4
                if not torch.isfinite(loss):
                    raise RuntimeError('Nonfinite training loss')
                loss.backward()
                step_loss += loss.item()
                del hidden, logits, loss, batch
            norm = torch.nn.utils.clip_grad_norm_(trainable, 1.0)
            if not torch.isfinite(norm):
                raise RuntimeError('Nonfinite adapter gradient')
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
            ACTIVE['completed_steps'] = step + 1
            losses.append(step_loss)
            event(work, 'optimizer_step', run=name, step=step + 1, loss=step_loss,
                  elapsed_seconds=round(time.monotonic() - started, 2), peak_bytes=torch.cuda.max_memory_allocated())
        adapter = output_dir / 'adapter'
        model.save_pretrained(adapter, safe_serialization=True)
        tokenizer.save_pretrained(adapter)
        torch.save({'optimizer': optimizer.state_dict(), 'torch_rng': torch.get_rng_state(),
                    'python_rng': random.getstate(), 'completed_steps': args.steps}, output_dir / 'optimizer-state.pt')
        after = {n: digest_bytes(p.detach().float().cpu().numpy().tobytes())
                 for n, p in model.named_parameters() if p.requires_grad}
        assert before != after, 'No adapter weight changed'
        score, evidence = verify(infer(model, tokenizer, probes, torch, work, name), manifest,
                                 baseline['scores']['coding']['passed'], name, work)
        receipt = record(output_dir / 'training-receipt.json', {
            'run': name, 'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
            'transformers': transformers.__version__, 'steps': args.steps, 'losses': losses,
            'elapsed_seconds': time.monotonic() - started, 'peak_gpu_bytes': torch.cuda.max_memory_allocated(),
            'adapter': str(adapter), 'adapter_files': {p.name: digest(p) for p in adapter.iterdir() if p.is_file()},
            'trainable_before': before, 'trainable_after': after, 'data_sha256': manifest['sha256'],
            'program_sha256': {p.name: digest(p) for p in HERE.glob('*.py')},
            'score': score, 'rust_verified': evidence['evidence']['verified'],
            # rust_verified above is the checker's pass state. A candidate that fails on
            # its merits and a checker that never ran are both "verified: false", which
            # hides the difference in the receipt. Record execution separately so a
            # failing candidate is not misread as an unverified run.
            'rust_executed': all(check.get('exit_code') is not None and not check.get('timed_out')
                                 for check in evidence['evidence']['checks']),
            'rust_verdict': 'checker_passed' if score['passed'] else 'candidate_failed',
            'admitted': False, 'scope': 'Candidate-only held-out response/code probes; no live activation or complete identity-erasure claim',
        })
        if score['passed'] and evidence['evidence']['verified']:
            record(output_dir / 'candidate-passed.json', {'adapter': str(adapter), 'receipt_sha256': digest(output_dir / 'training-receipt.json')})
            event(work, 'candidate_passed', adapter=str(adapter), admitted=False)
            return 0
        regressions = validation_regressions(baseline, score)
        if regressions:
            event(work, 'candidate_rejected', reason='validation regression', categories=regressions, adapter=str(adapter))
            return 3
        current = tuple(score['scores'][k]['passed'] for k in ('identity', 'behavior', 'coding'))
        if previous == current:
            event(work, 'campaign_stopped', reason='same failed scores twice; revise the curriculum before further rounds')
            return 4
        previous = current
    event(work, 'bounded_rounds_complete', passed=False, last_adapter=str(adapter))
    return 5

def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()

def validation_regressions(baseline, current):
    return [key for key in ('identity', 'behavior', 'coding')
            if current['scores'][key]['passed'] < baseline['scores'][key]['passed']]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'convert', 'train'])
    parser.add_argument('--work', type=Path, default=DEFAULT_WORK)
    parser.add_argument('--steps', type=int, default=16)
    parser.add_argument('--rounds', type=int, default=3)
    parser.add_argument('--max-minutes', type=float, default=20)
    parser.add_argument('--learning-rate', type=float, default=1e-5)
    parser.add_argument('--resume-adapter', type=Path)
    parser.add_argument('--curriculum', choices=['v4', 'v5', 'v6', 'v7', 'v8', 'v9', 'v10', 'persona'], default='v5')
    parser.add_argument('--lora-r', type=int, default=8)
    parser.add_argument('--lora-layers', type=str, default='24-31')
    parser.add_argument('--reuse-baseline', action='store_true')
    parser.add_argument('--max-tokens', type=int, default=256)
    parser.add_argument('--max-prompt-tokens', type=int, default=1024)
    parser.add_argument('--base-hf', type=Path)
    args = parser.parse_args()
    if not 1 <= args.steps <= 256 or not 1 <= args.rounds <= 6 or not 1 <= args.max_minutes <= 120:
        parser.error('Round, step and time bounds exceeded')
    args.work.mkdir(parents=True, exist_ok=True)
    if args.action == 'train' and (args.work / 'STOP').exists():
        print(json.dumps({'status': 'stopped', 'reason': 'STOP file is present; no model loaded or training started'}))
        return 2
    try:
        if args.action == 'prepare':
            from curriculum_runtime import prepare
            print(json.dumps(prepare(args.work / 'data_runtime_v3'), indent=2))
            return 0
        if args.action == 'convert':
            convert(args.work)
            return 0
        return train(args)
    except Exception as error:
        event(args.work, 'failed', error=type(error).__name__, message=str(error))
        if ACTIVE:
            try:
                ACTIVE['model'].save_pretrained(ACTIVE['output_dir'] / 'failed-adapter', safe_serialization=True)
                record(ACTIVE['output_dir'] / 'failure.json', {
                    'completed_steps': ACTIVE['completed_steps'], 'error': type(error).__name__,
                    'message': str(error), 'admitted': False})
            except Exception as save_error:
                event(args.work, 'failed_adapter_save_error', message=str(save_error))
        raise

if __name__ == '__main__':
    raise SystemExit(main())
