"""Train a bounded, isolated coding candidate from newly gate-verified data."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import random
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path.insert(0, str(WORKSPACE))
import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
DEST = ROOT / "epoch_10010"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
DATA = RUNS / "candidate_coding_training_v3.json"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
OUT = RUNS / "candidate_coding_training_10010.json"
SEED, LR, STEPS = 20261118, 5e-6, 64

def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)

def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def main() -> int:
    if DEST.exists() or OUT.exists():
        raise FileExistsError("candidate or receipt already exists")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    training_hash = data.pop("receipt_sha256")
    if sha_obj(data) != training_hash or sha_obj(data["samples"]) != data["training_sha256"]:
        raise ValueError("training receipt/hash validation failed")
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256")
    if sha_obj(suite) != suite_hash or suite_hash != data["heldout_suite_sha256"]:
        raise ValueError("held-out suite/hash mismatch")
    if data["heldout_id_overlap"] or data["heldout_function_name_overlap"]:
        raise ValueError("training data reports held-out leakage")
    rows = data["samples"]
    if len(rows) != 32 or sum(x["category"].startswith("python_") for x in rows) != 16 or sum(x["category"].startswith("rust_") for x in rows) != 16:
        raise ValueError("unexpected 16/16 verified sample balance")
    if any(not result["passed"] for result in data["gate_results"]):
        raise ValueError("unaccepted examples present in training source")
    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("unexpected active tutor: " + json.dumps(before))
    parent_hash = sha_file(PARENT / "adapter_model.safetensors")
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    examples = rows * 2
    payload = {"schema": "viv_candidate_coding_training_run_v1",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "dataset": str(DATA), "dataset_sha256": training_hash,
               "heldout_suite": str(SUITE), "heldout_suite_sha256": suite_hash,
               "unique_samples": len(rows), "python_unique": 16, "rust_unique": 16,
               "training_rows": len(examples), "training_sha256": sha_obj(examples),
               "seed": SEED, "learning_rate": LR, "steps_requested": STEPS,
               "parent": str(PARENT), "parent_sha256": parent_hash,
               "candidate": str(DEST), "live_before": before,
               "live_restore": "PENDING", "promoted": False}
    quiesced = False
    outcome = None
    error = None
    try:
        status = request("/v1/quiesce", {})
        if status.get("status") != "QUIESCED":
            raise RuntimeError("tutor failed to quiesce: " + json.dumps(status))
        quiesced = True
        import torch
        from transformers import set_seed
        random.seed(SEED)
        torch.manual_seed(SEED)
        set_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        outcome = trainer.run_sleep_training(epoch=10010, steps=STEPS, lr=LR,
                                             parent_adapter=PARENT,
                                             training_samples=examples)
        if not outcome.get("ok"):
            raise RuntimeError("candidate trainer returned failure: " + json.dumps(outcome))
        payload["candidate_sha256"] = sha_file(DEST / "adapter_model.safetensors")
        payload["training"] = outcome
        payload["status"] = "TRAINED_CANDIDATE"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        payload["training_error"] = error
        payload["status"] = "TRAINING_FAILED"
    finally:
        if quiesced:
            try:
                request("/v1/resume", {"adapter_dir": str(LIVE)})
            except Exception as exc:
                payload["restore_error"] = f"{type(exc).__name__}: {exc}"
    try:
        restored = request("/v1/status")
        payload["live_restore"] = restored
        payload["live_restored"] = restored.get("status") == "ACTIVE" and restored.get("active_adapter") == LIVE.name
    except Exception as exc:
        restored = None
        payload["live_restore_error"] = f"{type(exc).__name__}: {exc}"
        payload["live_restored"] = False
    payload["receipt_sha256"] = sha_obj(payload)
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(OUT), "status": payload["status"],
                      "candidate": str(DEST), "candidate_sha256": payload.get("candidate_sha256"),
                      "live_restored": payload["live_restored"],
                      "active_adapter": (restored or {}).get("active_adapter"),
                      "training_error": error, "promoted": False}, indent=2), flush=True)
    return 0 if payload["status"] == "TRAINED_CANDIDATE" and payload["live_restored"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
