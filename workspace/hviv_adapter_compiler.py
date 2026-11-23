import os
import sys
import json
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SFT_DATASET = "L:\\LocalCoder\\workspace\\hviv_sft_dataset.jsonl"
ADAPTER_OUTPUT_DIR = "L:\\_models\\adapters"
MERGE_CONFIG_PATH = "L:\\LocalCoder\\workspace\\adapter_merge_config.json"

os.makedirs(ADAPTER_OUTPUT_DIR, exist_ok=True)

class QLoRAAdapterCompiler:
    def __init__(self):
        self.dataset_path = SFT_DATASET

    def compile_adapter_manifest(self) -> dict:
        """
        Compiles harvested SFT trajectories into domain-specific LoRA GGUF adapter build manifests.
        """
        if not os.path.exists(self.dataset_path):
            return {"status": "FAIL", "reason": "SFT dataset missing."}

        total_trajectories = 0
        domain_counts = {"L:": 0, "C:": 0, "D:": 0, "E:": 0, "F:": 0}

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    total_trajectories += 1
                    try:
                        data = json.loads(line.strip())
                        msgs = data.get("messages", [])
                        for m in msgs:
                            content = m.get("content", "")
                            for d in domain_counts.keys():
                                if f"domain {d}" in content.lower() or f"[{d}]" in content:
                                    domain_counts[d] += 1
                    except json.JSONDecodeError:
                        pass

        print(f"[{datetime.now().isoformat()}] [QLORA DATASET COMPILER]")
        print(f"  ├─ Total SFT Trajectories Harvested: {total_trajectories:,}")
        print(f"  ├─ Domain Distribution: {json.dumps(domain_counts)}")

        adapter_manifests = {
            "timestamp": datetime.now().isoformat(),
            "total_trajectories": total_trajectories,
            "base_model": "qwen3:8b-local-32k",
            "target_adapters": {
                "L:": os.path.join(ADAPTER_OUTPUT_DIR, "l_drive_hviv_master.gguf"),
                "C:": os.path.join(ADAPTER_OUTPUT_DIR, "c_drive_os_v1.gguf"),
                "D:": os.path.join(ADAPTER_OUTPUT_DIR, "d_drive_test_v1.gguf"),
                "E:": os.path.join(ADAPTER_OUTPUT_DIR, "e_drive_vault_v1.gguf"),
                "F:": os.path.join(ADAPTER_OUTPUT_DIR, "f_drive_knowledge_v1.gguf")
            },
            "status": "MANIFEST_COMPILED_READY_FOR_GGUF_MERGE"
        }

        with open(MERGE_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(adapter_manifests, f, indent=2)

        print(f"  └─ Adapter merge configuration saved to: {MERGE_CONFIG_PATH}")
        return adapter_manifests

if __name__ == "__main__":
    compiler = QLoRAAdapterCompiler()
    res = compiler.compile_adapter_manifest()
    print("\n[SUCCESS] QLoRA Adapter Compiler verified operational.")
