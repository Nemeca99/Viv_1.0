"""Train a shared or residual specialist QLoRA with assistant-only loss."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

import torch
from peft import LoraConfig, PeftModel, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainerCallback,
)


class ChatDataset(Dataset):
    def __init__(self, path: Path, tokenizer: AutoTokenizer, max_length: int) -> None:
        self.rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.tokenizer = tokenizer
        self.max_length = max_length
        if not self.rows:
            raise ValueError("training dataset is empty")
        if not isinstance(max_length, int) or max_length < 2:
            raise ValueError("max_length must be an integer of at least 2 tokens")
        self.examples: list[dict[str, torch.Tensor]] = []
        self.supervised_token_counts: list[int] = []
        self.context_truncated_rows = 0
        for index, row in enumerate(self.rows):
            messages = row.get("messages")
            if not isinstance(messages, list) or len(messages) < 2:
                raise ValueError(f"training row {index} must contain prompt and assistant messages")
            if not isinstance(messages[-1], dict) or messages[-1].get("role") != "assistant":
                raise ValueError(f"training row {index} must end with an assistant message")
            assistant_content = messages[-1].get("content")
            if not isinstance(assistant_content, str) or not assistant_content.strip():
                raise ValueError(f"training row {index} has empty assistant target content")
            prompt = tokenizer.apply_chat_template(
                messages[:-1],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            full = tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=False, enable_thinking=False
            )
            prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
            full_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
            common_prefix = 0
            for prompt_token, full_token in zip(prompt_ids, full_ids):
                if prompt_token != full_token:
                    break
                common_prefix += 1
            if common_prefix != len(prompt_ids):
                raise ValueError(
                    f"training row {index} prompt is not a prefix of its full chat template"
                )
            target_tokens = len(full_ids) - common_prefix
            if target_tokens <= 0:
                raise ValueError(f"training row {index} has no assistant target tokens")
            if target_tokens >= max_length:
                raise ValueError(
                    f"training row {index} assistant target ({target_tokens} tokens) "
                    f"does not fit max_length={max_length}"
                )
            if len(full_ids) > max_length:
                # Keep the complete assistant target and the newest prompt context.
                prompt_budget = max_length - target_tokens
                prompt_start = common_prefix - prompt_budget
                input_ids = full_ids[max(0, prompt_start):]
                retained_prompt_tokens = len(input_ids) - target_tokens
                self.context_truncated_rows += 1
            else:
                input_ids = full_ids
                retained_prompt_tokens = common_prefix
            labels = list(input_ids)
            for position in range(retained_prompt_tokens):
                labels[position] = -100
            supervised_tokens = sum(token != -100 for token in labels)
            if supervised_tokens == 0:
                raise ValueError(f"training row {index} has no supervised assistant tokens")
            self.supervised_token_counts.append(supervised_tokens)
            self.examples.append({
                "input_ids": torch.tensor(input_ids),
                "attention_mask": torch.ones(len(input_ids), dtype=torch.long),
                "labels": torch.tensor(labels),
            })

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return self.examples[index]


class Pad:
    def __init__(self, pad_id: int) -> None:
        self.pad_id = pad_id

    def __call__(self, rows: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
        width = max(len(row["input_ids"]) for row in rows)

        def padded(key: str, fill: int) -> torch.Tensor:
            return torch.stack(
                [
                    torch.nn.functional.pad(
                        row[key], (0, width - len(row[key])), value=fill
                    )
                    for row in rows
                ]
            )

        return {
            "input_ids": padded("input_ids", self.pad_id),
            "attention_mask": padded("attention_mask", 0),
            "labels": padded("labels", -100),
        }


def _body_runtime_guard():
    from aios_rebuild.main_core.mind_runtime_gate import RuntimeBodyGuard

    return RuntimeBodyGuard(requested_threads=2)


class BodyRuntimeCallback(TrainerCallback):
    def __init__(self, body_guard) -> None:
        self.body_guard = body_guard

    def on_step_begin(self, args, state, control, **kwargs):
        self.body_guard.check()
        return control


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def adapter_dir(path: Path, name: str) -> Path:
    if (path / "adapter_config.json").is_file():
        return path
    nested = path / name
    if (nested / "adapter_config.json").is_file():
        return nested
    raise FileNotFoundError(f"adapter config not found below {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adapter-name", required=True)
    parser.add_argument("--shared-adapter", type=Path)
    parser.add_argument("--steps", type=int, default=40)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=42017)
    parser.add_argument("--low-vram", action="store_true")
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("output directory is not empty")
    body_guard = _body_runtime_guard()
    body_guard.check(force=True)
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.base, local_files_only=True)
    tokenizer.pad_token = tokenizer.eos_token
    # Validate that every training row has supervised assistant tokens before
    # loading model weights or allocating GPU memory.
    dataset = ChatDataset(args.dataset, tokenizer, args.max_length)
    body_guard.check(force=True)
    torch.cuda.manual_seed_all(args.seed)
    from transformers import Trainer, TrainingArguments
    args.output.mkdir(parents=True, exist_ok=True)
    def progress(stage, **values):
        path = args.output / 'training_progress.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'stage': stage, 'total_updates': args.steps,
                             'at_utc': datetime.now(timezone.utc).isoformat(), **values}), encoding='utf-8')
        temporary.replace(path)
    progress('loading_4bit_weights')

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    body_guard.check(force=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        local_files_only=True,
        quantization_config=quant,
        device_map={"": 0},
        torch_dtype=torch.float16,
        **({'attn_implementation': 'sdpa'} if args.low_vram else {}),
    )
    model.config.use_cache = False
    # PEFT upcasts embeddings and the output head to fp32. Moving these frozen
    # matrices to CPU first avoids a transient >8GB allocation on an 8B model.
    frozen_matrices = [model.get_input_embeddings(), model.get_output_embeddings()]
    if args.low_vram:
        for module in frozen_matrices:
            module.to('cpu')
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    if args.low_vram:
        for module in frozen_matrices:
            module.to(device='cuda', dtype=torch.float16)
    config = LoraConfig(
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    if args.shared_adapter:
        shared_path = adapter_dir(args.shared_adapter, "swarm-default")
        model = PeftModel.from_pretrained(
            model, shared_path, adapter_name="swarm-default", is_trainable=False
        )
        model.add_adapter(args.adapter_name, config)
        model.base_model.set_adapter(["swarm-default", args.adapter_name])
        for name, parameter in model.named_parameters():
            parameter.requires_grad = f".{args.adapter_name}." in name
    else:
        model = get_peft_model(model, config, adapter_name=args.adapter_name)
    trainable = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    if trainable == 0:
        raise SystemExit("no trainable adapter parameters")
    training = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        max_steps=args.steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=2e-4,
        warmup_ratio=0.05,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        fp16=True,
        optim="paged_adamw_8bit",
        seed=args.seed,
        data_seed=args.seed,
        remove_unused_columns=False,
    )
    class Progress(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            progress('training', update=state.global_step, logs=logs or {},
                     cuda_allocated_bytes=torch.cuda.memory_allocated(),
                     cuda_peak_bytes=torch.cuda.max_memory_allocated())
    trainer = Trainer(
        model=model,
        args=training,
        train_dataset=dataset,
        data_collator=Pad(tokenizer.pad_token_id),
        callbacks=[BodyRuntimeCallback(body_guard), Progress()],
    )
    result = trainer.train()
    progress('saving_adapter', update=args.steps)
    args.output.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(
        args.output, selected_adapters=[args.adapter_name], safe_serialization=True
    )
    tokenizer.save_pretrained(args.output)
    receipt = {
        "schema": "hive_lora_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "base": str(args.base.resolve()),
        "base_config_sha256": digest(args.base / "config.json"),
        "base_weight_sha256": {path.name: digest(path) for path in sorted(args.base.glob("*.safetensors"))},
        "dataset": str(args.dataset.resolve()),
        "dataset_sha256": digest(args.dataset),
        "adapter_name": args.adapter_name,
        "shared_adapter": (
            str(args.shared_adapter.resolve()) if args.shared_adapter else None
        ),
        "saved_adapter": str((args.output / args.adapter_name).resolve()),
        "steps": args.steps,
        "low_vram": args.low_vram,
        "gradient_accumulation_steps": args.gradient_accumulation_steps,
        "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(),
        "seed": args.seed,
        "trainable_parameters": trainable,
        "training_examples": len(dataset),
        "supervised_target_tokens": sum(dataset.supervised_token_counts),
        "supervised_target_tokens_min": min(dataset.supervised_token_counts),
        "supervised_target_tokens_max": max(dataset.supervised_token_counts),
        "context_truncated_rows": dataset.context_truncated_rows,
        "max_length": args.max_length,
        "train_loss": result.training_loss,
        "metrics": result.metrics,
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "gpu": torch.cuda.get_device_name(0),
    }
    (args.output / "training_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))
    progress('complete', update=args.steps, train_loss=result.training_loss)


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
