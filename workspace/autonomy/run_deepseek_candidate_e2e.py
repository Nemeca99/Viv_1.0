"""Train and behavior-test an isolated DeepSeek adapter; always restore live tutor."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
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
import viv_sleep_trainer as sleep_trainer

PARENT_ADAPTER = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
CANDIDATE_ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
RECEIPT_ROOT = HERE / "learning" / "deepseek_candidate_runs"
LIVE_ADAPTER_NAME = "epoch_10001"
EPOCH = 10002
SEED = 20261110
HELD_OUT_IDS = {"py_dedupe", "py_is_palindrome", "rs_fib", "rs_reverse"}
API = "http://127.0.0.1:1234"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sha_obj(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        API + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)


def accepted_training_samples() -> tuple[list[dict], list[dict]]:
    """Use latest hashed ACCEPTED code only; never train from rejected proposals."""
    specs = {item["id"]: item["spec"] for item in code_loop.CURRICULUM}
    specs.update({item["id"]: item["spec"] for item in python_curriculum.TASKS})
    receipt_file = HERE / "learning" / "code_learning_receipts.jsonl"
    latest: dict[str, dict] = {}
    for line_number, line in enumerate(receipt_file.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("stage") != "ACCEPTED" or not entry.get("passed") or not entry.get("code"):
            continue
        task_id = entry.get("task", "")
        if task_id not in specs or task_id in HELD_OUT_IDS:
            continue
        body = dict(entry)
        receipt_hash = body.pop("sha256", None)
        expected_receipt_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if not receipt_hash or expected_receipt_hash != receipt_hash:
            raise ValueError(f"Accepted source receipt hash failed at line {line_number}")
        latest[task_id] = entry

    samples, lineage = [], []
    for task_id, entry in sorted(latest.items()):
        lang = entry.get("lang") or ("rust" if task_id.startswith("rs_") else "python")
        samples.append({
            "category": task_id,
            "prompt": f"USER: {specs[task_id]}\n\nASSISTANT:\n",
            "completion": entry["code"].rstrip() + "\n",
        })
        lineage.append({
            "task": task_id, "lang": lang, "source_receipt_sha256": entry["sha256"],
            "code_sha256": hashlib.sha256(entry["code"].encode("utf-8")).hexdigest(),
        })
    if len(samples) < 8:
        raise RuntimeError(f"Only {len(samples)} distinct verified training tasks found")
    return samples, lineage


def held_out_tasks() -> list[dict]:
    tasks = {item["id"]: dict(item) for item in code_loop.CURRICULUM}
    tasks.update({item["id"]: dict(item) for item in python_curriculum.TASKS})
    missing = HELD_OUT_IDS - tasks.keys()
    if missing:
        raise RuntimeError(f"Held-out tasks missing from curriculum: {sorted(missing)}")
    return [tasks[task_id] for task_id in sorted(HELD_OUT_IDS)]


def evaluate(adapter_name: str) -> list[dict]:
    out = []
    for task in held_out_tasks():
        try:
            raw = code_loop.propose(task, prior=[], examples=[])
            candidate = code_loop.extract_code(raw, task["lang"])
            if not candidate:
                passed, error = False, "NO_CODE_BLOCK"
            else:
                gate = code_loop.gate_python if task["lang"] == "python" else code_loop.gate_rust
                passed, error = gate(candidate, task["tests"])
            result = {
                "task": task["id"], "lang": task["lang"],
                "adapter": adapter_name, "passed": passed,
                "error": error[:2000], "code": candidate, "raw_output": raw,
            }
        except Exception as exc:
            result = {"task": task["id"], "lang": task["lang"],
                      "adapter": adapter_name, "passed": False,
                      "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps({"evaluation": result}, ensure_ascii=False), flush=True)
        out.append(result)
    return out


def set_adapter(path: Path) -> dict:
    response = request("/v1/reload_adapter", {"adapter_dir": str(path)})
    status = request("/v1/status")
    if status.get("status") != "ACTIVE":
        raise RuntimeError(f"Tutor did not return ACTIVE: {status}")
    if status.get("active_adapter") != path.name:
        raise RuntimeError(f"Wrong adapter active: expected {path.name}, got {status}")
    return {"response": response, "status": status}


def main() -> int:
    parent_weights = PARENT_ADAPTER / "adapter_model.safetensors"
    base_model = sleep_trainer.DEFAULT_BASE_MODEL
    if not parent_weights.is_file() or not base_model.is_dir():
        raise FileNotFoundError("Pinned parent adapter or local DeepSeek base is missing")
    candidate_dir = CANDIDATE_ROOT / f"epoch_{EPOCH:05d}"
    if candidate_dir.exists():
        raise FileExistsError(f"Candidate path already exists: {candidate_dir}")
    CANDIDATE_ROOT.mkdir(parents=True, exist_ok=True)
    RECEIPT_ROOT.mkdir(parents=True, exist_ok=True)

    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE_ADAPTER_NAME:
        raise RuntimeError(f"Live tutor state differs from expected parent: {before}")

    samples, lineage = accepted_training_samples()
    tasks = held_out_tasks()
    training_ids = {sample["category"] for sample in samples}
    if training_ids.intersection(HELD_OUT_IDS):
        raise RuntimeError("Held-out task leakage into training examples")
    corpus_hash = sha_obj(samples)
    print(json.dumps({
        "phase": "preflight", "parent_adapter": LIVE_ADAPTER_NAME,
        "parent_sha256": sha_file(parent_weights), "training_tasks": len(samples),
        "training_languages": sorted({row["lang"] for row in lineage}),
        "held_out_tasks": [task["id"] for task in tasks],
        "training_corpus_sha256": corpus_hash,
        "gpu": "temporarily quiescing the tutor for QLoRA; parent will be restored",
    }, ensure_ascii=False), flush=True)

    baseline = evaluate(LIVE_ADAPTER_NAME)
    candidate_outcome = None
    candidate_eval = []
    restore = None
    try:
        quiesced = request("/v1/quiesce", {})
        if quiesced.get("status") != "QUIESCED":
            raise RuntimeError(f"Tutor did not quiesce: {quiesced}")
        print(json.dumps({"phase": "training", "status": "GPU released",
                          "candidate": str(candidate_dir)}, ensure_ascii=False), flush=True)

        import torch
        from transformers import set_seed
        random.seed(SEED)
        torch.manual_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        set_seed(SEED)

        sleep_trainer.ADAPTERS_ROOT = CANDIDATE_ROOT
        sleep_trainer.RECEIPTS_FILE = CANDIDATE_ROOT / "training_receipts.jsonl"
        # Three deterministic copies give the existing trainer three passes
        # over the verified examples while keeping its own bounded QLoRA path.
        candidate_outcome = sleep_trainer.run_sleep_training(
            epoch=EPOCH, steps=60, parent_adapter=PARENT_ADAPTER,
            training_samples=samples * 3,
        )
        if not candidate_outcome.get("ok"):
            raise RuntimeError(f"Candidate trainer did not complete: {candidate_outcome}")
        candidate_weights = candidate_dir / "adapter_model.safetensors"
        if not candidate_weights.is_file():
            raise RuntimeError("Trainer returned success without adapter weights")

        set_adapter(candidate_dir)
        candidate_eval = evaluate(candidate_dir.name)
    finally:
        # This model path is fixed: candidate weights never become live state.
        restore = set_adapter(PARENT_ADAPTER)

    receipt = {
        "schema": "viv_deepseek_candidate_e2e_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED, "live_adapter_before": before,
        "parent_adapter": str(PARENT_ADAPTER),
        "parent_adapter_sha256": sha_file(parent_weights),
        "base_model_path": str(base_model),
        "training_sample_count": len(samples) * 3,
        "distinct_training_task_count": len(samples),
        "training_tasks": lineage,
        "training_corpus_sha256": corpus_hash,
        "held_out_tasks": sorted(HELD_OUT_IDS),
        "baseline": baseline,
        "training": candidate_outcome,
        "candidate_adapter": str(candidate_dir),
        "candidate_adapter_sha256": sha_file(candidate_dir / "adapter_model.safetensors"),
        "candidate_evaluation": candidate_eval,
        "live_adapter_restored": restore,
        "promoted": False,
    }
    receipt["receipt_sha256"] = sha_obj(receipt)
    receipt_path = RECEIPT_ROOT / f"deepseek_candidate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {
        "receipt": str(receipt_path), "candidate": str(candidate_dir),
        "baseline_passed": sum(row.get("passed", False) for row in baseline),
        "baseline_total": len(baseline),
        "candidate_passed": sum(row.get("passed", False) for row in candidate_eval),
        "candidate_total": len(candidate_eval),
        "restored_live_adapter": restore["status"].get("active_adapter"),
        "promoted": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0 if restore["status"].get("active_adapter") == LIVE_ADAPTER_NAME else 2


if __name__ == "__main__":
    raise SystemExit(main())
