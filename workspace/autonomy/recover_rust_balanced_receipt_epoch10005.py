"""Rebuild the post-training receipt from the trainer ledger and verified lineage."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
for item in (WORKSPACE, HERE):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import viv_code_learning_loop as gates
import viv_sleep_trainer as trainer

ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = Path(os.environ.get("VIV_CANDIDATE_PARENT", str(ROOT / "epoch_10002")))
EPOCH = int(os.environ.get("VIV_CANDIDATE_EPOCH", "10005"))
DEST = ROOT / f"epoch_{EPOCH:05d}"
LEDGER = ROOT / "training_receipts.jsonl"
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
OUT = HERE / "learning" / "deepseek_candidate_runs" / f"rust_balanced_training_{EPOCH}.json"


def sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def main() -> int:
    if OUT.exists():
        raise FileExistsError(OUT)
    if not (DEST / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(DEST)
    status = json.loads(urllib.request.urlopen("http://127.0.0.1:1234/v1/status", timeout=5).read())
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"live adapter not restored: {status}")
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected_steps = int(os.environ.get("VIV_CANDIDATE_STEPS", "60"))
    training = next((row for row in reversed(rows) if row.get("epoch") == EPOCH), None)
    if not training or training.get("status") != "CONSOLIDATED_SUCCESS" or training.get("steps_completed") != expected_steps:
        raise ValueError(f"trainer ledger does not prove epoch {EPOCH} completed: {training}")

    spec = importlib.util.spec_from_file_location("epoch10005_training", HERE / "train_rust_balanced_candidate_epoch10005.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    source_spec = importlib.util.spec_from_file_location("verified_training_source", HERE / "run_deepseek_candidate_e2e.py")
    source_module = importlib.util.module_from_spec(source_spec)
    assert source_spec and source_spec.loader
    source_spec.loader.exec_module(source_module)
    accepted, accepted_lineage = source_module.accepted_training_samples()
    extra_rust, rust_proofs = module.additional_rust_examples()
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    held_ids = {row["id"] for row in suite["held_out"]}
    py_rows = [row for row in accepted if not row["category"].startswith("rs_")]
    rs_rows = [row for row in accepted if row["category"].startswith("rs_")] + extra_rust
    rust_balanced = (rs_rows * ((len(py_rows) + len(rs_rows) - 1) // len(rs_rows)))[:len(py_rows)]
    samples = (py_rows + rust_balanced) * 2
    if len(samples) != training.get("samples_trained") or held_ids.intersection(row["category"] for row in samples):
        raise ValueError("training sample count or held-out separation mismatch")
    payload = {
        "schema": "viv_rust_balanced_candidate_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "live_adapter_before": status, "live_adapter_restored": status,
        "parent": str(PARENT), "parent_sha256": sha_file(PARENT / "adapter_model.safetensors"),
        "candidate_path": str(DEST), "candidate_sha256": sha_file(DEST / "adapter_model.safetensors"),
        "suite_sha256": sha_file(SUITE), "accepted_training_lineage": accepted_lineage,
        "additional_rust_gate_proofs": rust_proofs,
        "python_unique_sources": len(py_rows), "rust_unique_sources": len(rs_rows),
        "balanced_replayed_sample_count": len(samples), "training_sha256": sha_obj(samples),
        "held_out_overlap": [], "seed": module.SEED, "learning_rate": module.LEARNING_RATE,
        "training": training, "trained": True, "promoted": False,
    }
    payload["receipt_sha256"] = sha_obj(payload)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "candidate_sha256": payload["candidate_sha256"],
                      "steps": training["steps_completed"], "loss": training["final_loss"],
                      "python_sources": len(py_rows), "rust_sources": len(rs_rows),
                      "live_adapter": status.get("active_adapter")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
