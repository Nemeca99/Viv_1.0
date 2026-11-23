"""Real PyTorch / PEFT LoRA training manager for AIOS.
Trains real .safetensors binary adapter weights on GPU and creates Ollama Modelfile adapters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from torch.utils.data import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    Trainer,
    TrainingArguments,
)

ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_BASE_MODEL = Path("L:/LocalCoder/workspace/swarm_adapters/models/Qwen3-1.7B")
OUTPUT_ADAPTERS_DIR = ROOT_DIR / "adapters"

class ChatDataset(Dataset):
    def __init__(self, path: Path, tokenizer: AutoTokenizer, max_length: int = 512) -> None:
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

class PadCollator:
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


def resolve_saved_adapter_path(adapter_save_path: Path, adapter_name: str) -> Path:
    """PEFT may store a named adapter in a same-name subdirectory."""
    candidates = [adapter_save_path / adapter_name, adapter_save_path]
    for candidate in candidates:
        if ((candidate / "adapter_model.safetensors").is_file()
                or (candidate / "adapter_model.bin").is_file()):
            return candidate
    return candidates[0]

def train_lora_adapter(
    dataset_path: Path,
    output_dir: Path,
    adapter_name: str = "viv_identity",
    base_model_path: Path = DEFAULT_BASE_MODEL,
    steps: int = 20,
    r: int = 8,
    alpha: int = 16
) -> dict:
    """Train real LoRA binary weights (.safetensors) using PyTorch CUDA and PEFT."""
    print(f"[Real LoRA Trainer] Initializing PyTorch PEFT training for {adapter_name}...")
    if not base_model_path.exists():
        raise FileNotFoundError(f"Base model path not found: {base_model_path}")
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset path not found: {dataset_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained(str(base_model_path), local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    model = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        local_files_only=True,
        quantization_config=quant_config,
        device_map={"": 0},
        torch_dtype=torch.float16,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora_config = LoraConfig(
        r=r,
        lora_alpha=alpha,
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

    model = get_peft_model(model, lora_config, adapter_name=adapter_name)
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[Real LoRA Trainer] Trainable parameters: {trainable_params:,}")

    dataset = ChatDataset(dataset_path, tokenizer, max_length=512)
    training_args = TrainingArguments(
        output_dir=str(output_dir / "checkpoints"),
        max_steps=steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=2,
        learning_rate=2e-4,
        warmup_ratio=0.05,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        fp16=True,
        optim="paged_adamw_8bit",
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=PadCollator(tokenizer.pad_token_id),
    )

    print(f"[Real LoRA Trainer] Running GPU training for {steps} steps...")
    result = trainer.train()

    # Save real adapter weights (.safetensors)
    adapter_save_path = output_dir / adapter_name
    model.save_pretrained(str(adapter_save_path), safe_serialization=True)
    tokenizer.save_pretrained(str(adapter_save_path))
    actual_adapter_path = resolve_saved_adapter_path(adapter_save_path, adapter_name)
    safetensors_exists = (actual_adapter_path / "adapter_model.safetensors").is_file()
    binary_exists = (actual_adapter_path / "adapter_model.bin").is_file()

    # Free VRAM immediately after training
    del model
    del trainer
    torch.cuda.empty_cache()

    receipt = {
        "status": "SUCCESS" if safetensors_exists or binary_exists else "FAILED_ARTIFACT_MISSING",
        "adapter_name": adapter_name,
        "adapter_root": str(adapter_save_path.resolve()),
        "adapter_path": str(actual_adapter_path.resolve()),
        "safetensors_exists": safetensors_exists,
        "binary_exists": binary_exists,
        "train_loss": result.training_loss,
        "trainable_parameters": trainable_params,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    per_adapter_receipt = adapter_save_path / "training_receipt.json"
    per_adapter_receipt.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    receipts_path = output_dir / "training_receipts.json"
    try:
        receipt_map = json.loads(receipts_path.read_text(encoding="utf-8")) if receipts_path.is_file() else {}
        if not isinstance(receipt_map, dict):
            receipt_map = {}
    except json.JSONDecodeError:
        receipt_map = {}
    receipt_map[adapter_name] = receipt
    temporary = receipts_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt_map, indent=2), encoding="utf-8")
    temporary.replace(receipts_path)
    if receipt["status"] != "SUCCESS":
        raise RuntimeError(f"PEFT save completed without an adapter weight file: {actual_adapter_path}")
    print(f"[Real LoRA Trainer] Success! Adapter saved to {adapter_save_path}")
    return receipt

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train real PyTorch PEFT LoRA adapter")
    parser.add_argument("--dataset", type=Path, default=ROOT_DIR / "viv_identity_dataset.jsonl")
    parser.add_argument("--output", type=Path, default=OUTPUT_ADAPTERS_DIR)
    parser.add_argument("--name", type=str, default="viv_identity")
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()

    train_lora_adapter(args.dataset, args.output, adapter_name=args.name, steps=args.steps)
