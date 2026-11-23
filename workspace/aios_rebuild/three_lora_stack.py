"""Load the Qwen substrate with the behavior, identity, and skill LoRAs active."""
from __future__ import annotations

import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


ROOT_DIR = Path(__file__).resolve().parent
ADAPTERS_DIR = ROOT_DIR / "adapters"
BASE_MODEL_PATH = Path(r"L:\LocalCoder\workspace\swarm_adapters\models\Qwen3-1.7B")
EXPECTED_ACTIVE = ["behavior_lora", "identity_lora", "task_lora"]


class ThreeLoraStack:
    def __init__(self, base_model_path: Path = BASE_MODEL_PATH):
        self.base_model_path = Path(base_model_path)
        self.tokenizer = None
        self.model: PeftModel | None = None
        self.active_adapters: list[str] = []
        self.active_lora_layers = 0

    def _validate_adapter(self, adapter_dir: Path, expected_base: Path) -> None:
        config_path = adapter_dir / "adapter_config.json"
        weight_path = adapter_dir / "adapter_model.safetensors"
        if not config_path.is_file() or not weight_path.is_file():
            raise FileNotFoundError(f"Adapter needs adapter_config.json and adapter_model.safetensors: {adapter_dir}")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        recorded = config.get("base_model_name_or_path")
        if recorded and Path(recorded).resolve() != expected_base.resolve():
            if str(Path(recorded)).casefold() != str(expected_base.resolve()).casefold():
                raise ValueError(f"Adapter {adapter_dir.name} was trained against a different base: {recorded}")
        if config.get("peft_type") != "LORA":
            raise ValueError(f"Unsupported adapter type in {config_path}")

    @staticmethod
    def activate_combined(peft_model: PeftModel, adapter_names: list[str]) -> int:
        """Activate the list through PEFT's BaseTuner multi-adapter inference API.

        PeftModel.set_adapter in the installed PEFT 0.18.1 accepts only one
        adapter; BaseTuner.set_adapter accepts an ordered list. Calling the
        former in a loop silently leaves only the last adapter active.
        """
        missing = set(adapter_names) - set(peft_model.peft_config)
        if missing:
            raise ValueError(f"Adapters not loaded: {sorted(missing)}")
        tuner = getattr(peft_model, "base_model", None)
        if tuner is None or not hasattr(tuner, "set_adapter"):
            raise RuntimeError("PEFT model has no BaseTuner multi-adapter activation API")
        try:
            tuner.set_adapter(adapter_names, inference_mode=True)
        except TypeError as exc:
            raise RuntimeError(
                "Installed PEFT must support BaseTuner.set_adapter(list[str], inference_mode=True)"
            ) from exc

        actual = list(peft_model.active_adapters)
        if actual != adapter_names:
            raise RuntimeError(f"Combined adapter activation mismatch: expected {adapter_names}, got {actual}")
        lora_layers = [
            module for module in peft_model.modules()
            if hasattr(module, "lora_A") and hasattr(module, "lora_B") and hasattr(module, "active_adapters")
        ]
        if not lora_layers:
            raise RuntimeError("No LoRA layers were found after adapter activation")
        for layer in lora_layers:
            active = layer.active_adapters
            if isinstance(active, str):
                active = [active]
            if list(active) != adapter_names:
                raise RuntimeError(f"A LoRA layer has active adapters {active}, expected {adapter_names}")
        trainable_lora = [
            name for name, parameter in peft_model.named_parameters()
            if "lora_" in name and parameter.requires_grad
        ]
        if trainable_lora:
            raise RuntimeError(f"Inference stack has trainable LoRA weights: {trainable_lora[:5]}")
        return len(lora_layers)

    def load_stacked_model(
        self,
        behavior_adapter_dir: Path,
        identity_adapter_dir: Path,
        task_adapter_dir: Path | None = None,
    ) -> PeftModel:
        """Load all three adapters and prove each LoRA layer has all active."""
        if task_adapter_dir is None:
            raise ValueError("The verified 3-LoRA stack requires a task adapter")
        if not self.base_model_path.is_dir():
            raise FileNotFoundError(f"Base model not found: {self.base_model_path}")
        paths = [Path(behavior_adapter_dir), Path(identity_adapter_dir), Path(task_adapter_dir)]
        for path in paths:
            self._validate_adapter(path, self.base_model_path)
        if not torch.cuda.is_available():
            raise RuntimeError("3-LoRA inference requires the configured CUDA device")

        self.tokenizer = AutoTokenizer.from_pretrained(str(self.base_model_path), local_files_only=True)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_use_double_quant=True,
        )
        base_model = AutoModelForCausalLM.from_pretrained(
            str(self.base_model_path),
            local_files_only=True,
            quantization_config=quant_config,
            device_map={"": 0},
            torch_dtype=torch.float16,
        )
        peft_model = PeftModel.from_pretrained(
            base_model, str(paths[0]), adapter_name=EXPECTED_ACTIVE[0], is_trainable=False
        )
        peft_model.load_adapter(str(paths[1]), adapter_name=EXPECTED_ACTIVE[1], is_trainable=False)
        peft_model.load_adapter(str(paths[2]), adapter_name=EXPECTED_ACTIVE[2], is_trainable=False)
        self.active_lora_layers = self.activate_combined(peft_model, EXPECTED_ACTIVE)
        peft_model.eval()
        self.active_adapters = list(peft_model.active_adapters)
        self.model = peft_model
        print(
            f"[3-LoRA Stack] Active={self.active_adapters}; "
            f"verified LoRA layers={self.active_lora_layers}; inference-only=True"
        )
        return peft_model


if __name__ == "__main__":
    print("Load adapters through ThreeLoraStack.load_stacked_model() to verify activation.")
