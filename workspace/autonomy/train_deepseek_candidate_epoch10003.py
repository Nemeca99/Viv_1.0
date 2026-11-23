"""Increment the isolated coding candidate with a tested repair and new fact."""
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
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import viv_code_learning_loop as code_loop
import viv_python_curriculum as python_curriculum
import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
PARENT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
EPOCH = 10003
SEED = 20261111


def _sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=240) as response:
        return json.load(response)


def samples() -> tuple[list[dict], list[dict]]:
    # Keep the prior run's 22 accepted examples, add the independently
    # gate-passed ordered-dedupe fix that the candidate regressed on.
    rows, lineage = code_loop_receipts()
    all_samples = rows

    # New, synthetic conversational fact tests whether the same candidate can
    # retain a fact and answer a differently worded question after reload.
    fact = {
        "category": "conversation_fact_probe",
        "prompt": "USER: Record this fact for the fictional Atlas engine: its call sign is opal-fox.\n\nASSISTANT:\n",
        "completion": "The fictional Atlas engine's call sign is opal-fox.\n",
    }
    all_samples.extend([fact] * 10)
    lineage.extend([{"task": "conversation_fact_probe", "repetitions": 10}])
    return all_samples, lineage


def code_loop_receipts() -> tuple[list[dict], list[dict]]:
    curriculum = {item["id"]: item for item in code_loop.CURRICULUM}
    curriculum.update({item["id"]: item for item in python_curriculum.TASKS})
    path = HERE / "learning" / "code_learning_receipts.jsonl"
    latest: dict[str, dict] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("task") not in curriculum or row.get("stage") != "ACCEPTED"
                or not row.get("passed") or not row.get("code")):
            continue
        if row["task"] in {"py_dedupe", "py_is_palindrome"}:
            continue
        body = dict(row)
        recorded = body.pop("sha256", None)
        if not recorded or hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest() != recorded:
            raise ValueError(f"Accepted receipt hash mismatch at line {line_no}")
        latest[row["task"]] = row
    out, lineage = [], []
    for task_id, row in sorted(latest.items()):
        task = curriculum[task_id]
        out.append({"category": task_id,
                    "prompt": f"USER: {task['spec']}\n\nASSISTANT:\n",
                    "completion": row["code"].rstrip() + "\n"})
        lineage.append({"task": task_id, "source_receipt_sha256": row["sha256"]})
    # Add the approved dedupe example after validating the immutable receipt.
    accepted_dedupe = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("task") == "py_dedupe" and row.get("stage") == "ACCEPTED"
                and row.get("passed") and row.get("code")):
            accepted_dedupe = row
    if accepted_dedupe is None:
        raise RuntimeError("No gate-passed py_dedupe receipt available")
    body = dict(accepted_dedupe)
    recorded = body.pop("sha256", None)
    if not recorded or hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest() != recorded:
        raise ValueError("py_dedupe accepted receipt hash mismatch")
    task = curriculum["py_dedupe"]
    out.append({"category": "py_dedupe", "prompt": f"USER: {task['spec']}\n\nASSISTANT:\n",
                "completion": accepted_dedupe["code"].rstrip() + "\n"})
    lineage.append({"task": "py_dedupe", "source_receipt_sha256": recorded})
    return out, lineage


def main() -> int:
    if not (PARENT / "adapter_model.safetensors").is_file():
        raise FileNotFoundError(PARENT)
    destination = ROOT / f"epoch_{EPOCH:05d}"
    if destination.exists():
        raise FileExistsError(destination)
    status = _request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != "epoch_10001":
        raise RuntimeError(f"Unexpected live adapter state: {status}")
    training, lineage = samples()
    corpus_hash = _sha_obj(training)
    print(json.dumps({"phase": "preflight", "parent": str(PARENT),
                      "parent_sha256": hashlib.file_digest((PARENT / "adapter_model.safetensors").open("rb"), "sha256").hexdigest(),
                      "examples": len(training), "distinct_verified_code_tasks": sum(x["category"] != "conversation_fact_probe" for x in training),
                      "new_fact": "fictional Atlas engine -> opal-fox", "corpus_sha256": corpus_hash}, ensure_ascii=False), flush=True)

    quiesced = _request("/v1/quiesce", {})
    if quiesced.get("status") != "QUIESCED":
        raise RuntimeError(f"Tutor did not quiesce: {quiesced}")
    import torch
    from transformers import set_seed
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    set_seed(SEED)
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    outcome = trainer.run_sleep_training(
        epoch=EPOCH, steps=60, lr=5e-5, parent_adapter=PARENT,
        training_samples=training * 2,
    )
    if not outcome.get("ok"):
        raise RuntimeError(f"Training failed: {outcome}")
    candidate = destination / "adapter_model.safetensors"
    receipt = {
        "schema": "viv_deepseek_incremental_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED, "live_adapter_before": status,
        "parent": str(PARENT), "parent_sha256": hashlib.file_digest((PARENT / "adapter_model.safetensors").open("rb"), "sha256").hexdigest(),
        "candidate": str(destination), "candidate_sha256": hashlib.file_digest(candidate.open("rb"), "sha256").hexdigest(),
        "training_corpus_sha256": corpus_hash, "training_lineage": lineage,
        "fact_probe_included": True, "training": outcome,
        "promoted": False,
    }
    receipt["receipt_sha256"] = _sha_obj(receipt)
    receipt_path = HERE / "learning" / "deepseek_candidate_runs" / "incremental_10003.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "complete", "candidate": str(destination),
                      "steps": outcome["receipt"]["steps_completed"],
                      "loss": outcome["receipt"]["final_loss"],
                      "receipt": str(receipt_path), "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
