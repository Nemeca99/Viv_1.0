"""Compare the trained farm adapter with its base on reserved Rust text facts.

This is a language gate only. It never admits an adapter to the live Queen.
"""
import json
import hashlib
import sys
import subprocess
from contextlib import nullcontext
from pathlib import Path
from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autonomy.farm_corpus import chat, check_fact, verify
from autonomy.farm_gpu_phase import gpu_training_phase, run_gpu_child
from autonomy.inn_hive import _atomic_json


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_model_stack():
    global AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, PeftModel, generate, torch
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from swarm_adapters.evaluate_behavior import generate


def _body_runtime_guard():
    from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard

    return RuntimeBodyGuard(requested_threads=2)


def main():
    body_guard = _body_runtime_guard()
    body_guard.check(force=True)
    _load_model_stack()
    torch.set_num_threads(2)
    learning = ROOT / 'autonomy/learning'
    status_path = learning / 'farm_adapter_status.json'
    status = json.loads(status_path.read_text())
    output = Path(status['output'])
    evaluation_path = output / 'language_evaluation.json'
    if evaluation_path.exists():
        raise ValueError('Preserve existing evaluation; do not overwrite it')
    train_receipt = json.loads((output / 'adapter/training_receipt.json').read_text())
    base = Path(train_receipt['base'])
    source = json.loads((base / 'model_source.json').read_text())
    if any(value != source['files'][name]['sha256'] for name, value in train_receipt['base_weight_sha256'].items()):
        raise ValueError('Training base hashes differ from verified source')
    corpus = Path(status['corpus'])
    verify(corpus)
    if digest(corpus / 'model_train.jsonl') != train_receipt['dataset_sha256']:
        raise ValueError('Training dataset hash mismatch')
    admitted = json.loads((learning / 'neural_admitted.json').read_text())
    validation_path = Path(admitted['run']) / 'validation_data.json'
    facts = [check_fact(row, training=False) for row in json.loads(validation_path.read_text())
             if row['prompt'].startswith('plot=21 ')]
    if len(facts) < 20:
        raise ValueError('Reserved evaluation has insufficient coverage')
    # Rebuild a fresh final plot-41 trajectory through the actual Rust farm.
    # Plot 21 is development validation; plot 41 is evaluated after the budget
    # change and does not supply optimizer targets.
    from autonomy.train_neural_inn import collect
    from inn.language import LanguageEngine
    parent_data = json.loads((Path(admitted['run']) / 'parent.json').read_text())
    parent = LanguageEngine(parent_data['config'], parent_data['engine'])
    checkpoint = Path(admitted['run']) / 'engine.pt'
    if digest(checkpoint) != admitted['engine_sha256']:
        raise ValueError('INN source parent integrity failure')
    parent.load(checkpoint)
    final_facts, _ = collect(parent, 300, 1802, plot_offset=40,
                            farm_config={'tillDecay': 4, 'seedDecay': 3, 'waterDecay': 3},
                            runtime_guard=body_guard)
    final_facts = [check_fact(row, training=False) for row in final_facts
                   if row['prompt'].startswith('plot=41 ')]
    if len(final_facts) < 20:
        raise ValueError('Fresh Rust final trajectory has insufficient coverage')
    train = json.loads((corpus / 'inn_train.json').read_text())['language']
    if {r['prompt'] for r in train} & {r['prompt'] for r in facts + final_facts}:
        raise ValueError('Reserved model evaluation leaked into training')
    progress_path = output / 'adapter/language_evaluation_progress.json'
    body_guard.check(force=True)
    status.update(stage='evaluating_language')
    _atomic_json(status_path, status)
    results = []
    summary = {}
    with nullcontext():
        tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
        tokenizer.pad_token = tokenizer.eos_token
        quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                  bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
        model = AutoModelForCausalLM.from_pretrained(base, local_files_only=True,
            quantization_config=quant, device_map={'': 0}, dtype=torch.float16, attn_implementation='sdpa')
        model = PeftModel.from_pretrained(model, output / 'adapter/farm-queen', adapter_name='farm-queen')
        model.eval()
        for arm in ('base', 'farm-queen', 'farm-queen-final'):
            arm_facts = final_facts if arm == 'farm-queen-final' else facts
            hits = 0
            for index, fact in enumerate(arm_facts):
                body_guard.check()
                messages = chat(fact)['messages'][:-1]
                if arm == 'base':
                    with model.disable_adapter():
                        generated = generate(model, tokenizer, messages, max_new_tokens=64)
                else:
                    generated = generate(model, tokenizer, messages, max_new_tokens=64)
                exact = generated == fact['target']
                hits += int(exact)
                results.append({'arm': arm, 'prompt': fact['prompt'], 'expected': fact['target'],
                                'generated': generated, 'exact': exact})
                _atomic_json(progress_path, {'arm': arm, 'completed': index + 1,
                    'total': len(arm_facts), 'exact': hits, 'latest': results[-1]})
            summary[arm] = {'exact': hits, 'total': len(arm_facts), 'accuracy': hits / len(arm_facts)}
        # Release the training model before the context restores Ollama.
        del model
        import gc
        gc.collect()
        torch.cuda.empty_cache()
    evaluation = {'schema': 'farm_queen_lora_language_evaluation_v1',
        'at_utc': datetime.now(timezone.utc).isoformat(), 'summary': summary, 'results': results,
        'corpus_id': status['corpus_id'], 'validation_source_sha256': digest(validation_path),
        'adapter_sha256': digest(output / 'adapter/farm-queen/adapter_model.safetensors'),
        'passed_language_gate': summary['farm-queen']['accuracy'] >= .95
                                and summary['farm-queen-final']['accuracy'] >= .95
                                and summary['farm-queen']['exact'] >= summary['base']['exact'],
        'improved_exact_generation': summary['farm-queen']['exact'] > summary['base']['exact'],
        'farm_behavior_gate': 'not_run', 'live_queen_weights_updated': False}
    _atomic_json(evaluation_path, evaluation)
    status.update(stage='evaluated_candidate', language_evaluation=evaluation,
                  live_queen_weights_updated=False)
    _atomic_json(status_path, status)
    print(json.dumps({'summary': summary, 'passed_language_gate': evaluation['passed_language_gate']}))


if __name__ == '__main__':
    if '--worker' in sys.argv:
        main()
    else:
        # A separate process releases every CUDA allocation, including partial
        # loads after an exception, before the parent restores the Queen.
        try:
            with gpu_training_phase():
                run_gpu_child([sys.executable, str(Path(__file__)), '--worker'], cwd=ROOT, timeout=900)
        except Exception as exc:
            path = ROOT / 'autonomy/learning/farm_adapter_status.json'
            status = json.loads(path.read_text())
            status.update(stage='evaluation_failed', error=f'{type(exc).__name__}: {exc}')
            _atomic_json(path, status)
            raise
