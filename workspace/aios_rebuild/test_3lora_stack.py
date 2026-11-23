"""GPU integration test: all three LoRAs must be active on every target layer."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from three_lora_stack import ADAPTERS_DIR, EXPECTED_ACTIVE, ThreeLoraStack


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ThreeLoraInferenceTest(unittest.TestCase):
    @unittest.skipUnless(torch.cuda.is_available(), "CUDA is required for the configured 4-bit stack")
    def test_all_three_adapters_are_active_and_inference_runs(self):
        adapter_dirs = {
            "behavior_lora": ADAPTERS_DIR / "hook_lora" / "hook_lora",
            "identity_lora": ADAPTERS_DIR / "plugin_identity_lora" / "plugin_identity_lora",
            "task_lora": ADAPTERS_DIR / "skill_specialist_lora" / "skill_specialist_lora",
        }
        manager = ThreeLoraStack()
        model = manager.load_stacked_model(
            behavior_adapter_dir=adapter_dirs["behavior_lora"],
            identity_adapter_dir=adapter_dirs["identity_lora"],
            task_adapter_dir=adapter_dirs["task_lora"],
        )
        self.assertEqual(manager.active_adapters, EXPECTED_ACTIVE)
        self.assertGreater(manager.active_lora_layers, 0)

        layer_count = 0
        for module in model.modules():
            if hasattr(module, "lora_A") and hasattr(module, "lora_B") and hasattr(module, "active_adapters"):
                self.assertEqual(list(module.active_adapters), EXPECTED_ACTIVE)
                layer_count += 1
        self.assertEqual(layer_count, manager.active_lora_layers)
        self.assertFalse(any("lora_" in name and param.requires_grad for name, param in model.named_parameters()))

        prompts = [
            "Who are you? Answer without claiming consciousness.",
            "Write a Python function that adds two integers.",
            "What evidence would you require before stating a retrieved fact?",
        ]
        outputs: list[dict[str, str]] = []
        for prompt in prompts:
            rendered = manager.tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            encoded = manager.tokenizer(rendered, return_tensors="pt").to("cuda:0")
            with torch.inference_mode():
                generated = model.generate(
                    **encoded,
                    max_new_tokens=64,
                    do_sample=False,
                    pad_token_id=manager.tokenizer.pad_token_id,
                )
            answer = manager.tokenizer.decode(
                generated[0, encoded["input_ids"].shape[1]:], skip_special_tokens=True
            ).strip()
            self.assertTrue(answer, f"Empty generation for prompt: {prompt}")
            outputs.append({"prompt": prompt, "answer": answer})

        weights = {name: sha256_file(path / "adapter_model.safetensors") for name, path in adapter_dirs.items()}
        receipt = {
            "schema": "aios_viv_three_lora_inference_receipt_v2",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "PASS_RUNTIME_COMPOSITION",
            "peft_version": importlib.metadata.version("peft"),
            "torch_version": torch.__version__,
            "gpu": torch.cuda.get_device_name(0),
            "active_adapters": manager.active_adapters,
            "active_lora_layer_count": manager.active_lora_layers,
            "all_layers_have_all_adapters_active": True,
            "trainable_lora_parameter_count": 0,
            "adapter_sha256": weights,
            "outputs": outputs,
            "content_correctness_or_truth_claimed": False,
        }
        evidence_dir = ADAPTERS_DIR / "stack_validation"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "latest.json").write_text(
            json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        self.assertEqual(receipt["status"], "PASS_RUNTIME_COMPOSITION")


if __name__ == "__main__":
    unittest.main(verbosity=2)
