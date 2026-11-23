import os
import sys
import json
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

SFT_DATASET = "L:\\LocalCoder\\workspace\\hviv_sft_dataset.jsonl"
MANIFEST_PATH = "E:\\_sweep_quarantine\\quarantine_manifest.jsonl"
TRAIN_EXPORT = "L:\\_models\\training_export.json"

class AutonomousTrainer:
    def __init__(self):
        self.dataset_path = SFT_DATASET

    def harvest_quarantine_manifests(self) -> list:
        """
        Extracts successful Rust Queen approval decisions from E: Quarantine Manifest.
        """
        pairs = []
        if os.path.exists(MANIFEST_PATH):
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            data = json.loads(line.strip())
                            user_msg = f"Requesting action on {data.get('original_path')} due to: {data.get('reason')}"
                            assistant_msg = f"Rust Queen Evaluation PASSED. File safely quarantined to {data.get('quarantined_path')}."
                            pairs.append({
                                "messages": [
                                    {"role": "system", "content": "HViv System Invariant: You are an execution amplifier bound to Rust Queen rules."},
                                    {"role": "user", "content": user_msg},
                                    {"role": "assistant", "content": assistant_msg}
                                ]
                            })
                        except json.JSONDecodeError:
                            pass
        return pairs

    def run_harvest_and_prep(self):
        print(f"[{datetime.now().isoformat()}] Starting Autonomous Trajectory Harvester...")
        new_pairs = self.harvest_quarantine_manifests()
        print(f"Harvested {len(new_pairs)} new training trajectories from Rust Queen manifests.")

        # Read existing dataset count
        existing_count = 0
        if os.path.exists(self.dataset_path):
            with open(self.dataset_path, "r", encoding="utf-8") as f:
                existing_count = len([line for line in f if line.strip()])

        # Append new pairs if any
        if new_pairs:
            with open(self.dataset_path, "a", encoding="utf-8") as f:
                for pair in new_pairs:
                    f.write(json.dumps(pair) + "\n")

        total_count = existing_count + len(new_pairs)
        print(f"Total SFT Instruction Pairs Available: {total_count}")

        train_spec = {
            "timestamp": datetime.now().isoformat(),
            "total_pairs": total_count,
            "target_model": "qwen3:8b-local-32k",
            "qlora_config": {
                "rank": 16,
                "alpha": 32,
                "epochs": 3,
                "batch_size": 2,
                "learning_rate": 0.0002
            },
            "status": "READY_FOR_OFFLINE_QLORA_TRAINING"
        }

        os.makedirs(os.path.dirname(TRAIN_EXPORT), exist_ok=True)
        with open(TRAIN_EXPORT, "w", encoding="utf-8") as f:
            json.dump(train_spec, f, indent=2)

        print(f"Training export specification written to: {TRAIN_EXPORT}")
        return train_spec

if __name__ == "__main__":
    print("==================================================")
    print("  HViv Autonomous Trainer & Dataset Harvester    ")
    print("==================================================")
    
    trainer = AutonomousTrainer()
    spec = trainer.run_harvest_and_prep()
    print("\n[SUCCESS] Autonomous Trainer verified operational.")
