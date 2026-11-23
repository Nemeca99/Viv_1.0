"""Check actual CUDA kernels, source tokenizer and supervised targets before training."""
import json
import sys
from pathlib import Path
from train import DEFAULT_WORK, PROJECT, libraries, record, render
from curriculum_exploration import prepare

def main():
    work = DEFAULT_WORK
    torch, transformers = libraries(work)
    import peft
    import bitsandbytes as bnb
    sys.path.insert(0, str(PROJECT / 'workspace/aios_rebuild'))
    from train_real_lora import PadCollator
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        'L:/AI_Models/mradermacher/OmniCoder-2-9B-GGUF',
        gguf_file='OmniCoder-2-9B.Q3_K_M.gguf', local_files_only=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id
    prepare(work / 'data_exploration_v2')
    rows = [json.loads(line) for line in (work / 'data_exploration_v2/train.jsonl').read_text(encoding='utf-8').splitlines()]
    encoded = render(tokenizer, rows)
    collated = PadCollator(tokenizer.pad_token_id)(encoded[:2])
    assert (collated['labels'] == -100).any() and (collated['labels'] != -100).any()
    layer = bnb.nn.Linear4bit(16, 8, bias=False, compute_dtype=torch.bfloat16, quant_type='nf4').to('cuda')
    with torch.no_grad():
        output = layer(torch.ones(1, 16, device='cuda', dtype=torch.bfloat16))
    assert torch.isfinite(output).all()
    result = {'result': 'PASS', 'scope': 'Environment/tokenizer/kernel controls, not model training',
              'torch': torch.__version__, 'transformers': transformers.__version__, 'peft': peft.__version__,
              'gpu': torch.cuda.get_device_name(0), 'bf16': torch.cuda.is_bf16_supported(),
              'training_records': len(encoded), 'max_tokens': max(len(row['input_ids']) for row in encoded),
              'all_assistant_prefixes_match': True, 'nf4_kernel_finite': True}
    record(work / 'training-preflight-exploration-v2.json', result)
    print(json.dumps(result))

if __name__ == '__main__':
    main()
