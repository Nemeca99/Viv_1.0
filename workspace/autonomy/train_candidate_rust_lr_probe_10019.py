"""Controlled higher-learning-rate replay of the gate-accepted Rust v5 data."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import re
import urllib.request
from pathlib import Path

import train_candidate_rust_increment_10018 as source

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10016"
DEST = ROOT / "epoch_10019"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
DATA = RUNS / "candidate_rust_training_10018.json"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
PREFLIGHT = RUNS / "candidate_rust_lr_preflight_10019.json"
RECEIPT = RUNS / "candidate_rust_training_run_10019.json"
API = "http://127.0.0.1:1234"
SEED, LR, STEPS = 20261142, 5e-6, 24


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def api(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)


def main() -> int:
    for path in (PREFLIGHT, RECEIPT):
        if path.exists():
            raise FileExistsError(path)
    if DEST.exists():
        raise FileExistsError(DEST)

    source_data = json.loads(DATA.read_text(encoding="utf-8"))
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if canonical_hash(suite) != suite_hash:
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held = [row for row in suite["held_out"] if row["lang"] == "rust"]
    held_ids = {row["id"] for row in held}
    held_names = {re.search(r"pub\s+fn\s+(\w+)", row["spec"]).group(1) for row in held}
    samples = source_data["samples"]
    ids = {row["id"] for row in samples}
    names = {row["id"].removeprefix("rust10018_") for row in samples}
    if ids & held_ids or names & held_names:
        raise ValueError("HELDOUT_OVERLAP")
    if source_data.get("heldout_suite_sha256") != suite_hash:
        raise ValueError("SOURCE_DATA_SUITE_HASH_MISMATCH")

    references = {row[0]: row for row in source.EXAMPLES}
    gate_rows = []
    for sample in samples:
        name = sample["id"].removeprefix("rust10018_")
        if name not in references:
            raise ValueError("SOURCE_REFERENCE_MISSING:" + name)
        _, spec, code, checks = references[name]
        tests = "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ " + checks + " } }"
        passed, error = source.gates.gate_rust(code, tests)
        gate_rows.append({"id": sample["id"], "function": name,
                          "passed": bool(passed), "error": error[:1200]})
    if not gate_rows or not all(row["passed"] for row in gate_rows):
        raise RuntimeError("SOURCE_GATE_RECHECK_FAILED")
    if source_data["training_sha256"] != canonical_hash(samples):
        raise ValueError("SOURCE_DATA_HASH_MISMATCH")

    before_topology = file_hash(HERE / "viv_code_topology.sqlite3")
    before = api("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("LIVE_ADAPTER_NOT_ACTIVE:" + json.dumps(before))
    preflight = {
        "schema": "viv_candidate_rust_lr_preflight_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_dataset": str(DATA), "source_dataset_sha256": file_hash(DATA),
        "source_training_sha256": source_data["training_sha256"], "suite_sha256": suite_hash,
        "parent": str(PARENT), "parent_sha256": file_hash(PARENT / "adapter_model.safetensors"),
        "unique_examples": len(samples), "heldout_id_overlap": sorted(ids & held_ids),
        "heldout_function_overlap": sorted(names & held_names), "gate_results": gate_rows,
        "learning_rate": LR, "steps": STEPS, "seed": SEED,
    }
    preflight["receipt_sha256"] = canonical_hash(preflight)
    PREFLIGHT.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    import viv_sleep_trainer as trainer
    import torch
    from transformers import set_seed

    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    run = {
        "schema": "viv_candidate_rust_lr_training_run_v1", "created_utc": datetime.now(timezone.utc).isoformat(),
        "preflight": str(PREFLIGHT), "preflight_sha256": preflight["receipt_sha256"],
        "source_dataset_sha256": file_hash(DATA), "source_training_sha256": source_data["training_sha256"],
        "parent": str(PARENT), "parent_sha256": preflight["parent_sha256"],
        "candidate": str(DEST), "candidate_only": True, "unique_examples": len(samples),
        "training_rows": len(samples) * 2, "steps_requested": STEPS, "learning_rate": LR,
        "seed": SEED, "suite_sha256": suite_hash, "live_before": before,
        "promoted": False, "topology_write": False, "persistent_memory_write": False,
    }
    quiesced = False
    try:
        status = api("/v1/quiesce", {})
        if status.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(status))
        quiesced = True
        random.seed(SEED)
        torch.manual_seed(SEED)
        set_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        result = trainer.run_sleep_training(epoch=10019, steps=STEPS, lr=LR,
                                            parent_adapter=PARENT,
                                            training_samples=samples * 2)
        if not result.get("ok"):
            raise RuntimeError("TRAINING_FAILED:" + json.dumps(result))
        run["training"] = result
        run["candidate_sha256"] = file_hash(DEST / "adapter_model.safetensors")
        run["status"] = "TRAINED_CANDIDATE"
    except Exception as exc:
        run["status"] = "TRAINING_FAILED"
        run["training_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if quiesced:
            try:
                api("/v1/resume", {"adapter_dir": str(LIVE)})
            except Exception as exc:
                run["restore_error"] = f"{type(exc).__name__}: {exc}"
    try:
        after = api("/v1/status")
        run["live_after"] = after
        run["live_restored"] = after.get("status") == "ACTIVE" and after.get("active_adapter") == LIVE.name
    except Exception as exc:
        run["live_restored"] = False
        run["restore_status_error"] = f"{type(exc).__name__}: {exc}"
    run["topology_sha256_before"] = before_topology
    run["topology_sha256_after"] = file_hash(HERE / "viv_code_topology.sqlite3")
    run["receipt_sha256"] = canonical_hash(run)
    RECEIPT.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"preflight": str(PREFLIGHT), "training_receipt": str(RECEIPT),
                      "status": run["status"], "learning_rate": LR,
                      "training": run.get("training", {}), "live_restored": run.get("live_restored"),
                      "topology_unchanged": run["topology_sha256_before"] == run["topology_sha256_after"],
                      "promoted": False}, indent=2), flush=True)
    return 0 if run.get("status") == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
