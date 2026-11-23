"""Train a new candidate from revalidated graduated Python and Rust examples."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = LIVE
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
DEST = ROOT / "epoch_10007"
DATASET = HERE / "learning" / "deepseek_candidate_runs" / "verified_multidomain_training_v1.json"
OUT = HERE / "learning" / "deepseek_candidate_runs" / "multidomain_training_10007.json"
SEED = 20261115
LR = 2e-6
MAX_STEPS = 60


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=240) as response:
        return json.load(response)


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    if DEST.exists() or OUT.exists():
        raise FileExistsError("candidate or receipt path already exists")
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    receipt_hash = dataset.pop("receipt_sha256")
    if sha_obj(dataset) != receipt_hash:
        raise ValueError("training dataset receipt hash mismatch")
    samples = dataset["samples"]
    if sha_obj(samples) != dataset.get("training_sha256"):
        raise ValueError("training data hash mismatch")
    py = [row for row in samples if not row["category"].startswith("rs_")]
    rs = [row for row in samples if row["category"].startswith("rs_")]
    if len(py) != dataset["python_sample_count"] or len(rs) != dataset["rust_sample_count"]:
        raise ValueError("language row counts differ from dataset receipt")
    # Balance languages so the training updates don't drown out Rust exposure.
    rust_balanced = (rs * ((len(py) + len(rs) - 1) // len(rs)))[:len(py)]
    training_samples = py + rust_balanced
    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"unexpected live adapter: {before}")
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    print(json.dumps({"phase": "preflight", "dataset_sha256": receipt_hash,
                      "python_samples": len(py), "rust_samples": len(rs),
                      "balanced_samples": len(training_samples), "parent": str(PARENT),
                      "candidate": str(DEST), "learning_rate": LR}, indent=2), flush=True)

    quiesced = False
    outcome = None
    try:
        state = request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError(f"tutor did not quiesce: {state}")
        quiesced = True
        import torch
        from transformers import set_seed
        random.seed(SEED)
        torch.manual_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        set_seed(SEED)
        outcome = trainer.run_sleep_training(epoch=10007, steps=MAX_STEPS, lr=LR,
                                             parent_adapter=PARENT,
                                             training_samples=training_samples)
        if not outcome.get("ok"):
            raise RuntimeError(f"trainer failed: {outcome}")
        payload = {
            "schema": "viv_verified_multidomain_candidate_training_v1",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_path": str(DATASET), "dataset_sha256": receipt_hash,
            "training_sha256": sha_obj(training_samples),
            "python_samples": len(py), "rust_unique_samples": len(rs),
            "balanced_sample_count": len(training_samples), "seed": SEED,
            "learning_rate": LR, "max_steps": MAX_STEPS,
            "parent": str(PARENT), "parent_sha256": sha_file(PARENT / "adapter_model.safetensors"),
            "candidate": str(DEST), "candidate_sha256": sha_file(DEST / "adapter_model.safetensors"),
            "training": outcome, "live_adapter_before": before,
            "live_restore": "PENDING", "promoted": False,
        }
        payload["receipt_sha256"] = sha_obj(payload)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"phase": "candidate_saved", "receipt": str(OUT),
                          "candidate_sha256": payload["candidate_sha256"],
                          "steps": outcome["receipt"]["steps_completed"],
                          "loss": outcome["receipt"]["final_loss"]}, indent=2), flush=True)
    finally:
        if quiesced:
            request("/v1/resume", {"adapter_dir": str(LIVE)})
    restored = request("/v1/status")
    if restored.get("status") != "ACTIVE" or restored.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"live adapter restore failed: {restored}")
    restore_path = OUT.with_name("multidomain_training_10007_restore.json")
    restore = {"schema": "viv_candidate_restore_receipt_v1", "training_receipt": str(OUT),
               "restored_status": restored, "created_utc": datetime.now(timezone.utc).isoformat()}
    restore["receipt_sha256"] = sha_obj(restore)
    restore_path.write_text(json.dumps(restore, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "complete", "receipt": str(OUT),
                      "restore_receipt": str(restore_path), "active_adapter": restored.get("active_adapter"),
                      "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
