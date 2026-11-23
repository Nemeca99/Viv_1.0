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
    Trainer,
    TrainingArguments,
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

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        messages = self.rows[index]["messages"]
        prompt = self.tokenizer.apply_chat_template(
            messages[:-1],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        full = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False, enable_thinking=False
        )
        prompt_ids = self.tokenizer(prompt, add_special_tokens=False)["input_ids"]
        encoded = self.tokenizer(
            full, add_special_tokens=False, truncation=True, max_length=self.max_length
        )
        ids = encoded["input_ids"]
        labels = ids.copy()
        for position in range(min(len(prompt_ids), len(labels))):
            labels[position] = -100
        return {
            "input_ids": torch.tensor(ids),
            "attention_mask": torch.ones(len(ids), dtype=torch.long),
            "labels": torch.tensor(labels),
        }


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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--seed", type=int, default=42017)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit("output directory is not empty")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    tokenizer = AutoTokenizer.from_pretrained(args.base, local_files_only=True)
    tokenizer.pad_token = tokenizer.eos_token
    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        local_files_only=True,
        quantization_config=quant,
        device_map={"": 0},
        torch_dtype=torch.float16,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
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
    dataset = ChatDataset(args.dataset, tokenizer, args.max_length)
    training = TrainingArguments(
        output_dir=str(args.output / "checkpoints"),
        max_steps=args.steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
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
    trainer = Trainer(
        model=model,
        args=training,
        train_dataset=dataset,
        data_collator=Pad(tokenizer.pad_token_id),
    )
    result = trainer.train()
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
        "seed": args.seed,
        "trainable_parameters": trainable,
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


if __name__ == "__main__":
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    main()
