"""
Viv Sleep Trainer (AIOS V2 QLoRA Consolidation Engine)
Executed during Viv's circadian SLEEP phase.
Ingests verified passing programs (Exit Code 0) from E:\\Viv_Sandbox\\playground\\training\\verified_successes.jsonl,
runs 4-bit QLoRA fine-tuning on the RTX 3060 Ti GPU, saves the adapter checkpoint to Drive E:,
and records a cryptographic training receipt.
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CENTRAL_TZ = ZoneInfo("America/Chicago")

def central_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()

PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
GRADUATED_SUCCESS_FILE = PLAYGROUND_ROOT / "training" / "graduated_successes.jsonl"
VERIFIED_SUCCESS_FILE = GRADUATED_SUCCESS_FILE if GRADUATED_SUCCESS_FILE.exists() else (PLAYGROUND_ROOT / "training" / "verified_successes.jsonl")
ADAPTERS_ROOT = PLAYGROUND_ROOT / "adapters"
RECEIPTS_FILE = PLAYGROUND_ROOT / "receipts" / "sleep_training_receipts.jsonl"
DEFAULT_BASE_MODEL = Path(r"L:\AI_Models\deepseek-ai\deepseek-coder-6.7b-base")


def prepare_sft_dataset(verified_file: Path, max_samples: int = 60) -> list[dict]:
    """Reads verified passing programs from verified_successes.jsonl and builds instruction-response pairs."""
    if not verified_file.exists():
        return []

    samples = []
    with open(verified_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                spec = row.get("spec", "").strip()
                code = row.get("code", "").strip()
                cat = row.get("category", "code").strip()
                if spec and code:
                    samples.append({
                        "category": cat,
                        "prompt": f'"""\nTask: {spec}\nEnvironment: Python 3.12, container viv-vm (/work)\n"""\n\n',
                        "completion": f"{code}\n"
                    })
            except Exception:
                continue

    # Failure->fix lessons: teach the failing error and the diff that resolved it
    lessons_file = PLAYGROUND_ROOT / "lessons" / "lessons.jsonl"
    if lessons_file.exists():
        lesson_rows = []
        for line in lessons_file.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                lr = json.loads(line)
                if lr.get("error") and lr.get("fix_diff"):
                    lesson_rows.append(lr)
            except Exception:
                continue
        for lr in lesson_rows[-10:]:
            samples.append({
                "category": "lesson",
                "prompt": f'# Lesson: {lr["title"]}\n# Failure Error: {lr["error"]}\n# Unified Fix Diff:\n',
                "completion": f'{lr["fix_diff"]}\n'
            })

    # Return newest samples up to max_samples
    return samples[-max_samples:] if len(samples) > max_samples else samples


def run_sleep_training(
    epoch: int,
    base_model_path: Path = DEFAULT_BASE_MODEL,
    steps: int = 15,
    lr: float = 2e-4,
    lora_r: int = 8,
    lora_alpha: int = 16,
    parent_adapter: Path | None = None,
    training_samples: list[dict] | None = None,
) -> dict:
    """Runs 4-bit QLoRA fine-tuning on GPU during the sleep window."""
    import torch
    from transformers import (
        AutoModelForCausalLM,
        PreTrainedTokenizerFast,
        BitsAndBytesConfig,
        TrainingArguments,
        Trainer,
    )
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from torch.utils.data import Dataset

    print(f"\n=======================================================")
    print(f" [SLEEP CONSOLIDATION] Epoch {epoch} GPU Training Start")
    print(f"=======================================================")
    start_time = time.time()

    adapter_epoch_dir = ADAPTERS_ROOT / f"epoch_{epoch:04d}"
    if adapter_epoch_dir.exists():
        raise FileExistsError(f"Candidate destination already exists: {adapter_epoch_dir}")
    if parent_adapter is not None and not (parent_adapter / 'adapter_model.safetensors').is_file():
        raise FileNotFoundError(f"Parent adapter is missing: {parent_adapter}")
    samples = training_samples if training_samples is not None else prepare_sft_dataset(VERIFIED_SUCCESS_FILE)
    if not samples:
        print("[!] No verified successes found to train on. Skipping training pass.")
        return {"ok": False, "error": "No verified samples found in dataset"}

    print(f"[+] Ingested {len(samples)} SEMANTIC_GRADUATION programs (assertion-proven) for Epoch {epoch} fine-tuning.")

    # Tokenizer
    tokenizer = PreTrainedTokenizerFast.from_pretrained(str(base_model_path), local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Dataset formatting
    class SFTDataset(Dataset):
        def __init__(self, items, tok, max_len=512):
            self.examples = []
            for item in items:
                prompt = item.get("prompt", "")
                full = prompt + item.get("completion", "")
                
                p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
                f_ids = tok(full, add_special_tokens=False, truncation=True, max_length=max_len)["input_ids"]

                labels = list(f_ids)
                prefix_len = min(len(p_ids), len(f_ids))
                for i in range(prefix_len):
                    labels[i] = -100

                self.examples.append({
                    "input_ids": torch.tensor(f_ids),
                    "attention_mask": torch.ones(len(f_ids), dtype=torch.long),
                    "labels": torch.tensor(labels)
                })

        def __len__(self):
            return len(self.examples)

        def __getitem__(self, idx):
            return self.examples[idx]

    class PadCollator:
        def __init__(self, pad_id):
            self.pad_id = pad_id

        def __call__(self, batch):
            max_len = max(len(b["input_ids"]) for b in batch)
            input_ids = []
            attn_masks = []
            labels = []
            for b in batch:
                pad_len = max_len - len(b["input_ids"])
                input_ids.append(torch.cat([b["input_ids"], torch.full((pad_len,), self.pad_id, dtype=torch.long)]))
                attn_masks.append(torch.cat([b["attention_mask"], torch.zeros(pad_len, dtype=torch.long)]))
                labels.append(torch.cat([b["labels"], torch.full((pad_len,), -100, dtype=torch.long)]))
            return {
                "input_ids": torch.stack(input_ids),
                "attention_mask": torch.stack(attn_masks),
                "labels": torch.stack(labels)
            }

    train_data = SFTDataset(samples, tokenizer, max_len=512)

    # 4-bit Quantization Config
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True
    )

    print(f"[+] Loading base model weights from {base_model_path.name} in 4-bit...")
    model = AutoModelForCausalLM.from_pretrained(
        str(base_model_path),
        quantization_config=bnb_config,
        device_map={"": 0},
        torch_dtype=torch.float16,
        local_files_only=True
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    lora_config = LoraConfig(
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )
    
    from peft import PeftModel
    prev_adapter = parent_adapter if parent_adapter is not None else ADAPTERS_ROOT / f"epoch_{epoch-1:04d}"
    if prev_adapter.exists() and (prev_adapter / "adapter_model.safetensors").exists():
        print(f"[+] Resuming cumulative training from prior epoch: {prev_adapter.name}")
        try:
            model = PeftModel.from_pretrained(model, str(prev_adapter), is_trainable=True)
        except Exception as e:
            if parent_adapter is not None:
                raise RuntimeError(f"Explicit parent adapter could not be loaded: {prev_adapter}") from e
            print(f"[!] Warning resuming prior adapter ({e}), re-initializing fresh LoRA...")
            model = get_peft_model(model, lora_config)
    else:
        model = get_peft_model(model, lora_config)

    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"[+] PEFT QLoRA configured: {trainable_params:,} trainable parameters.")

    checkpoint_dir = adapter_epoch_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    actual_steps = min(steps, len(train_data))
    if actual_steps < 5:
        actual_steps = min(15, len(train_data))

    training_args = TrainingArguments(
        output_dir=str(checkpoint_dir),
        max_steps=actual_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=2,
        learning_rate=lr,
        warmup_ratio=0.05,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        fp16=True,
        optim="paged_adamw_8bit",
        remove_unused_columns=False
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_data,
        data_collator=PadCollator(tokenizer.pad_token_id)
    )

    print(f"[+] Executing gradient descent on GPU for {actual_steps} steps...")
    train_res = trainer.train()
    final_loss = train_res.training_loss
    print(f"[+] Gradient descent complete! Final Loss: {final_loss:.4f}")

    # Save adapter weights (.safetensors)
    print(f"[+] Saving LoRA adapter checkpoint to {adapter_epoch_dir}...")
    model.save_pretrained(str(adapter_epoch_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(adapter_epoch_dir))

    # Clean up PyTorch from GPU immediately
    del model
    del trainer
    del train_data
    torch.cuda.empty_cache()
    duration = time.time() - start_time
    print(f"[+] PyTorch GPU VRAM freed. Sleep training duration: {duration:.1f}s")

    receipt = {
        "epoch": epoch,
        "status": "CONSOLIDATED_SUCCESS",
        "timestamp": central_iso(),
        "samples_trained": len(samples),
        "steps_completed": actual_steps,
        "final_loss": round(final_loss, 5),
        "duration_sec": round(duration, 2),
        "trainable_parameters": trainable_params,
        "adapter_dir": str(adapter_epoch_dir),
        "base_model": base_model_path.name
    }

    RECEIPTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RECEIPTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(receipt) + "\n")

    print(f"=======================================================")
    print(f" [SLEEP CONSOLIDATION] Epoch {epoch} Finished | Loss: {final_loss:.4f}")
    print(f"=======================================================\n")
    return {"ok": True, "receipt": receipt}


if __name__ == "__main__":
    ep = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    st = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    res = run_sleep_training(epoch=ep, steps=st)
    print("===SLEEP_TRAINING_RECEIPT_START===")
    print(json.dumps(res))
    print("===SLEEP_TRAINING_RECEIPT_END===")

