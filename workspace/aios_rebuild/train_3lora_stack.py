"""Train the baseline stack or explicitly admitted Dream candidates.

Dream-candidate training writes a versioned candidate adapter under an
isolated run directory. It never updates the active adapter paths.
"""

import argparse
import json
from pathlib import Path
from train_real_lora import train_lora_adapter, DEFAULT_BASE_MODEL
from dream_core.training_gate import stage_admitted_candidates

ROOT = Path(__file__).resolve().parent
DATASET_DIR = ROOT / "datasets"
OUTPUT_DIR = ROOT / "adapters"

def train_full_3lora_stack():
    adapters_config = [
        ("hook_lora", DATASET_DIR / "dataset_hook.jsonl", 15),
        ("plugin_identity_lora", DATASET_DIR / "dataset_plugin.jsonl", 15),
        ("skill_specialist_lora", DATASET_DIR / "dataset_skill.jsonl", 15),
    ]

    receipts = {}
    for name, dataset, steps in adapters_config:
        print(f"\n========================================================")
        print(f"  STARTING TRAINING: {name.upper()}")
        print(f"========================================================\n")
        receipt = train_lora_adapter(
            dataset_path=dataset,
            output_dir=OUTPUT_DIR,
            adapter_name=name,
            base_model_path=DEFAULT_BASE_MODEL,
            steps=steps
        )
        receipts[name] = receipt

    print("\n========================================================")
    print("  ALL 3 LORAS TRAINED SUCCESSFULLY!")
    print("========================================================\n")
    for k, v in receipts.items():
        print(f"Adapter: {k} -> Path: {v['adapter_path']} (Loss: {v['train_loss']:.4f})")


def train_admitted_dream_candidates(
    candidate_path: Path,
    steps: int = 15,
    confirm_fn=input,
) -> dict:
    """Train only explicitly admitted rows into a fresh candidate run folder."""
    manifest = stage_admitted_candidates(
        candidate_path,
        DATASET_DIR / "dream_staged",
    )
    confirmation = f"TRAIN {len(manifest['datasets'])} DREAM CANDIDATE ADAPTER(S)"
    print(f"Candidate run: {manifest['run_id']}")
    print(f"Staged datasets: {len(manifest['datasets'])}")
    print("This writes new candidate adapters and does not promote them.")
    if confirm_fn(f"Type exactly '{confirmation}' to continue: ").strip() != confirmation:
        manifest["training_status"] = "NOT_STARTED_OPERATOR_CONFIRMATION_MISSING"
        manifest_path = Path(next(iter(manifest["datasets"].values()))).parent / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print("Training not started; staged candidate data remains available for review.")
        return {"status": manifest["training_status"], "manifest": str(manifest_path)}
    stage_dir = Path(next(iter(manifest["datasets"].values()))).parent
    run_dir = OUTPUT_DIR / "dream_candidate_runs" / manifest["run_id"]
    run_dir.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "aios_viv_dream_training_run_v1",
        "run_id": manifest["run_id"],
        "manifest": str(stage_dir / "manifest.json"),
        "status": "IN_PROGRESS",
        "active_adapter_modified": False,
        "adapters": {},
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    try:
        for adapter_name, dataset_path in manifest["datasets"].items():
            receipt = train_lora_adapter(
                dataset_path=Path(dataset_path),
                output_dir=run_dir,
                adapter_name=adapter_name,
                base_model_path=DEFAULT_BASE_MODEL,
                steps=steps,
            )
            result["adapters"][adapter_name] = receipt
        result["status"] = "CANDIDATES_TRAINED_NOT_PROMOTED"
    except Exception as exc:
        result["status"] = "FAILED"
        result["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        (run_dir / "run_manifest.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--train-baseline-stack",
        action="store_true",
        help="train the three configured baseline adapters (requires exact interactive confirmation)",
    )
    parser.add_argument(
        "--train-dream-candidates",
        type=Path,
        help="train only rows with explicit quality/correctness/truth passes and Architect admission",
    )
    parser.add_argument("--steps", type=int, default=15)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("--steps must be positive")
    if args.train_dream_candidates is not None:
        train_admitted_dream_candidates(args.train_dream_candidates, steps=args.steps)
    else:
        phrase = "TRAIN BASELINE THREE-LORA STACK"
        if input(f"This trains and overwrites baseline adapters. Type exactly '{phrase}' to continue: ").strip() == phrase:
            train_full_3lora_stack()
        else:
            print("Training not started.")
