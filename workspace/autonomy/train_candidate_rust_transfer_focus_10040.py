"""Train candidate10040 from six new Rust ALLOW transfers, candidate-only."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

import candidate_coding_runtime_v1 as runtime
import train_candidate_mixed_offsplit_10038 as previous
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

ADAPTERS = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ADAPTERS / "epoch_10038"
DEST = ADAPTERS / "epoch_10040"
NEURAL = HERE / "learning" / "neural_runs"
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v2_1.json"
FUNCTION_DB = NEURAL / "candidate_verified_functions.sqlite3"
TRANSFER = NEURAL / "candidate_rust_transfer_learning_10039.json"
DATA_OUT = NEURAL / "candidate_rust_transfer_training_10040.json"
RUN_OUT = NEURAL / "candidate_rust_transfer_training_run_10040.json"
LIVE = runtime.LIVE
SEED = 20261113
LEARNING_RATE = 5e-7
NEW_RUST_REPEATS = 4


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def write_new(path: Path, value: dict) -> dict:
    authorization = PrivacyCore().authorize_file_write(str(path))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied {path}: {authorization}")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return authorization


def load_new_rust_transfers(suite_hash: str, held_ids: set[str],
                            held_names: set[tuple[str, str]],
                            prior_samples: list[dict]) -> tuple[list[dict], dict]:
    envelope = json.loads(TRANSFER.read_text(encoding="utf-8"))
    claimed = envelope.pop("receipt_sha256", None)
    if canonical_hash(envelope) != claimed:
        raise ValueError("TRANSFER_RECEIPT_HASH_MISMATCH")
    envelope["receipt_sha256"] = claimed
    if (envelope.get("frozen_suite_sha256") != suite_hash
            or envelope.get("promoted") is not False
            or envelope.get("accepted_count") != 6
            or envelope.get("live_restored") is not True):
        raise ValueError("TRANSFER_RECEIPT_CONTRACT_INVALID")
    if envelope.get("topology_sha256_before") != envelope.get("topology_sha256_after"):
        raise ValueError("TRANSFER_TOPOLOGY_CHANGED")
    if envelope.get("persistent_memory_sha256_before") != envelope.get("persistent_memory_sha256_after"):
        raise ValueError("TRANSFER_MEMORY_CHANGED")
    candidate_hash = file_hash(PARENT / "adapter_model.safetensors")
    if envelope.get("candidate_sha256") != candidate_hash:
        raise ValueError("TRANSFER_CANDIDATE_HASH_MISMATCH")

    existing = {(x["language"], x["function_name"]) for x in prior_samples}
    store_hash_before = file_hash(FUNCTION_DB)
    uri = f"file:{FUNCTION_DB.as_posix()}?mode=ro"
    selected = []
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("FUNCTION_STORE_QUICK_CHECK_FAILED")
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT f.function_key,f.language,f.function_name,f.specification,
                   v.task_id,v.source_kind,v.source_sha256,v.code,v.code_sha256,
                   v.tests_sha256,v.gate_name,v.gate_status,v.gate_output,
                   v.gate_receipt_sha256,v.admitted_utc
            FROM active_versions a
            JOIN functions f USING(function_key)
            JOIN function_versions v USING(version_id)
            WHERE v.gate_status='ALLOW'
              AND v.source_kind='model_proposal_epoch_10038'
              AND v.task_id LIKE 'candidate_rust_transfer_10039_%'
            ORDER BY v.task_id
        """).fetchall()

    for row in rows:
        name, task_id = str(row["function_name"]), str(row["task_id"])
        pair = ("rust", name)
        if (task_id in held_ids or pair in held_names
                or pair in existing
                or not task_id.startswith("candidate_rust_transfer_10039_")):
            raise ValueError(f"HELDOUT_OR_DUPLICATE_TRANSFER:{task_id}:{name}")
        code = str(row["code"])
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if code_hash != row["code_sha256"]:
            raise ValueError(f"TRANSFER_CODE_HASH_MISMATCH:{task_id}")
        evidence = {
            "task_id": task_id, "language": "rust",
            "function_key": row["function_key"], "code_sha256": row["code_sha256"],
            "tests_sha256": row["tests_sha256"], "gate": row["gate_name"],
            "status": row["gate_status"], "output": row["gate_output"],
            "created_utc": row["admitted_utc"],
        }
        if canonical_hash(evidence) != row["gate_receipt_sha256"]:
            raise ValueError(f"TRANSFER_GATE_RECEIPT_HASH_MISMATCH:{task_id}")
        sample = previous._rust_prompt(
            name, str(row["specification"]), code, task_id,
            str(row["source_kind"]), str(row["source_sha256"]),
            str(row["tests_sha256"]), str(row["gate_receipt_sha256"]))
        selected.append(sample)
        existing.add(pair)

    if len(selected) != 6:
        raise ValueError(f"EXPECTED_SIX_NEW_RUST_ALLOW_EXAMPLES_GOT:{len(selected)}")
    if file_hash(FUNCTION_DB) != store_hash_before:
        raise RuntimeError("FUNCTION_STORE_CHANGED_DURING_READ")
    return selected, {"path": str(FUNCTION_DB), "sha256": store_hash_before,
                      "quick_check": "ok", "new_rust_allow_examples": len(selected),
                      "validated_transfer_receipt_sha256": claimed}


def main() -> int:
    for path in (PARENT / "adapter_model.safetensors", FUNCTION_DB,
                 TRANSFER, SUITE):
        if not path.is_file():
            raise FileNotFoundError(path)
    for path in (DEST, DATA_OUT, RUN_OUT):
        if path.exists():
            raise FileExistsError(f"Refusing overwrite: {path}")

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if runtime.canonical_hash(suite) != suite_hash:
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {str(row["id"]) for row in suite["held_out"]}
    held_names: set[tuple[str, str]] = set()
    for row in suite["held_out"]:
        match = re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(",
                          row.get("spec", ""))
        if match:
            held_names.add((str(row["lang"]), match.group(1)))

    old_rust, retained_python, base_manifest = previous.prior.load_old_samples(
        suite_hash, held_ids, held_names)
    base_python_names = {("python", str(x["function_name"]))
                         for x in retained_python}
    prior_store_samples, prior_store_manifest = previous.verified_store_samples(
        suite_hash, held_ids, held_names, base_python_names)
    new_rust, new_store_manifest = load_new_rust_transfers(
        suite_hash, held_ids, held_names, prior_store_samples)
    prior_python = [x for x in prior_store_samples if x["language"] == "python"]
    prior_rust = [x for x in prior_store_samples if x["language"] == "rust"]
    samples = retained_python + prior_store_samples + new_rust
    if any(x.get("task_id") in held_ids
           or (x["language"], x["function_name"]) in held_names for x in samples):
        raise ValueError("HELDOUT_SAMPLE_REJECTED")

    training_rows = retained_python + prior_python + prior_rust + new_rust * NEW_RUST_REPEATS
    random.Random(SEED).shuffle(training_rows)
    counts = {lang: sum(x["language"] == lang for x in samples)
              for lang in ("python", "rust")}
    expected_rows = len(retained_python) + len(prior_python) + len(prior_rust) + len(new_rust) * NEW_RUST_REPEATS
    if counts != {"python": 21, "rust": 26} or len(training_rows) != expected_rows or expected_rows != 65:
        raise ValueError(f"TRAINING_COUNTS_INVALID:{counts}:{len(training_rows)}")

    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    parent_hash = file_hash(PARENT / "adapter_model.safetensors")
    store_hash = file_hash(FUNCTION_DB)
    dataset = {
        "schema": "viv_candidate_rust_transfer_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_candidate": str(PARENT), "parent_sha256": parent_hash,
        "base_dataset": base_manifest,
        "prior_verified_function_store": prior_store_manifest,
        "new_verified_function_store": new_store_manifest,
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": suite_hash,
        "accepted_source_counts": {
            "retained_python": len(retained_python),
            "prior_gate_accepted_python": len(prior_python),
            "prior_gate_accepted_rust": len(prior_rust),
            "new_gate_accepted_rust": len(new_rust),
            "validated_prior_rust_not_replayed": len(old_rust),
        },
        "language_counts": counts,
        "repeat_policy": {"retained_python": 1, "prior_python": 1,
                          "prior_rust": 1, "new_rust": NEW_RUST_REPEATS},
        "training_rows": len(training_rows),
        "training_sha256": canonical_hash(training_rows),
        "heldout_id_overlap": [], "heldout_function_name_overlap": [],
        "samples": samples, "live_adapter_at_build": before.get("active_adapter"),
        "candidate_function_store_sha256_after_build": store_hash,
        "promoted": False, "topology_write": False,
        "persistent_memory_write": False,
    }
    dataset["receipt_sha256"] = canonical_hash(dataset)
    data_auth = write_new(DATA_OUT, dataset)

    import torch
    from transformers import set_seed
    random.seed(SEED)
    torch.manual_seed(SEED)
    set_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)
    trainer.ADAPTERS_ROOT = ADAPTERS
    trainer.RECEIPTS_FILE = ADAPTERS / "training_receipts.jsonl"

    run = {
        "schema": "viv_candidate_rust_transfer_training_run_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_OUT), "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_sha256": dataset["training_sha256"],
        "source_samples": len(samples), "language_counts": counts,
        "training_rows": len(training_rows), "seed": SEED,
        "learning_rate": LEARNING_RATE, "steps_requested": len(training_rows),
        "parent": str(PARENT), "parent_sha256": parent_hash,
        "destination": str(DEST), "frozen_suite_sha256": suite_hash,
        "live_before": before, "privacy_authorization": data_auth,
        "promoted": False, "topology_write": False,
        "persistent_memory_write": False,
    }
    quiesced = False
    try:
        state = runtime.evaluator.request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(state))
        quiesced = True
        result = trainer.run_sleep_training(
            epoch=10040, steps=len(training_rows), lr=LEARNING_RATE,
            parent_adapter=PARENT, training_samples=training_rows)
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
                runtime.evaluator.request("/v1/resume", {"adapter_dir": str(LIVE)})
            except Exception as exc:
                run["restore_error"] = f"{type(exc).__name__}: {exc}"
    try:
        after = runtime.evaluator.request("/v1/status")
        run["live_after"] = after
        run["live_restored"] = (after.get("status") == "ACTIVE"
                                 and after.get("active_adapter") == LIVE.name)
    except Exception as exc:
        run["live_restored"] = False
        run["restore_status_error"] = f"{type(exc).__name__}: {exc}"
    run["candidate_function_store_sha256_after"] = file_hash(FUNCTION_DB)
    if run["candidate_function_store_sha256_after"] != store_hash:
        run["function_store_changed"] = True
    run["receipt_sha256"] = canonical_hash(run)
    write_new(RUN_OUT, run)
    print(json.dumps({
        "dataset_receipt": str(DATA_OUT), "training_receipt": str(RUN_OUT),
        "status": run["status"], "candidate_sha256": run.get("candidate_sha256"),
        "new_gate_accepted_rust": len(new_rust), "training_rows": len(training_rows),
        "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "promoted": False,
    }, indent=2), flush=True)
    return 0 if run.get("status") == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
