"""Fine-tune a new candidate adapter from gate-accepted candidate DB versions."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import sqlite3
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_verified_function_store as store
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10024"
DEST = ROOT / "epoch_10025"
RUNS = HERE / "learning" / "neural_runs"
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v2_1.json"
DATA_OUT = RUNS / "candidate_store_training_10025.json"
RUN_OUT = RUNS / "candidate_store_training_run_10025.json"
SEED, LEARNING_RATE, STEPS = 20261128, 5e-7, 18
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)


def write_authorized(path: Path, value: dict) -> None:
    authorization = PrivacyCore().authorize_file_write(str(path))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied training receipt: {authorization}")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    if DATA_OUT.exists() or RUN_OUT.exists() or DEST.exists():
        raise FileExistsError("epoch 10025 output already exists; refusing overwrite")
    for path in (store.DB_PATH, PARENT / "adapter_model.safetensors"):
        if not path.is_file():
            raise FileNotFoundError(path)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if suite_hash != canonical_hash(suite):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {str(row["id"]) for row in suite["held_out"]}
    held_names = {str(row["spec"]).split("(", 1)[0].rsplit(" ", 1)[-1]
                  for row in suite["held_out"] if row["lang"] == "python"}
    db_hash_before = sha_file(store.DB_PATH)
    uri = store.DB_PATH.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")
        rows = db.execute("""
            SELECT f.function_key,f.domain,f.function_name,f.specification,
                   v.version_id,v.task_id,v.source_kind,v.source_sha256,
                   v.code,v.code_sha256,v.tests_sha256,v.gate_status,
                   v.gate_receipt_sha256
            FROM function_versions v
            JOIN functions f USING(function_key)
            WHERE v.gate_status='ALLOW'
            ORDER BY v.version_id
        """).fetchall()
        attempts = db.execute("SELECT gate_status,COUNT(*) FROM proposal_attempts GROUP BY gate_status").fetchall()
    if not rows:
        raise RuntimeError("CANDIDATE_STORE_HAS_NO_GATE_ACCEPTED_FUNCTIONS")
    samples = []
    seen = set()
    for row in rows:
        (function_key, domain, name, spec, version_id, task_id, source_kind,
         source_hash, code, code_hash, tests_hash, gate_status, gate_receipt_hash) = row
        if task_id in held_ids:
            raise ValueError(f"HELD_OUT_TASK_IN_CANDIDATE_STORE:{task_id}")
        if name in held_names:
            raise ValueError(f"HELD_OUT_FUNCTION_NAME_IN_CANDIDATE_STORE:{name}")
        if hashlib.sha256(code.encode("utf-8")).hexdigest() != code_hash:
            raise ValueError(f"CANDIDATE_CODE_HASH_MISMATCH:{version_id}")
        if not gate_receipt_hash or gate_status != "ALLOW":
            raise ValueError(f"CANDIDATE_GATE_RECEIPT_MISSING:{version_id}")
        if code_hash in seen:
            continue
        seen.add(code_hash)
        prompt = (
            "SYSTEM: Write one self-contained, correct, standard-library python function. "
            "Do not depend on other top-level helpers. Return only one fenced code block; "
            "no tests or explanation.\n\nUSER: Implement: " + spec + "\n\nASSISTANT:"
        )
        samples.append({
            "id": f"candidate_store_v{version_id}_{task_id}",
            "category": "candidate_verified_function_store_distillation_v1",
            "prompt": prompt,
            "completion": f"{FENCE}python\n{code}\n{FENCE}{EOS}",
            "source_kind": source_kind,
            "function_key": function_key,
            "version_id": version_id,
            "source_sha256": source_hash,
            "code_sha256": code_hash,
            "tests_sha256": tests_hash,
            "gate_receipt_sha256": gate_receipt_hash,
        })
    training_rows = samples * 2
    dataset = {
        "schema": "viv_candidate_function_store_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "store_path": str(store.DB_PATH),
        "store_sha256": db_hash_before,
        "accepted_version_count": len(rows),
        "unique_training_examples": len(samples),
        "training_rows": len(training_rows),
        "rejected_attempt_counts": dict(attempts),
        "parent_candidate": str(PARENT),
        "heldout_suite_sha256": suite_hash,
        "heldout_id_overlap": [],
        "heldout_function_name_overlap": [],
        "samples": samples,
        "training_sha256": canonical_hash(training_rows),
    }
    dataset["receipt_sha256"] = canonical_hash(dataset)
    write_authorized(DATA_OUT, dataset)

    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    run = {
        "schema": "viv_candidate_function_store_training_run_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_OUT),
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_sha256": canonical_hash(training_rows),
        "store_sha256_before": db_hash_before,
        "unique_examples": len(samples),
        "training_rows": len(training_rows),
        "seed": SEED,
        "learning_rate": LEARNING_RATE,
        "steps_requested": STEPS,
        "parent": str(PARENT),
        "parent_sha256": sha_file(PARENT / "adapter_model.safetensors"),
        "heldout_suite_sha256": suite_hash,
        "live_before": before,
        "promoted": False,
        "topology_write": False,
        "persistent_memory_write": False,
    }
    quiesced = False
    try:
        state = request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(state))
        quiesced = True
        import torch
        from transformers import set_seed
        random.seed(SEED)
        torch.manual_seed(SEED)
        set_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        result = trainer.run_sleep_training(
            epoch=10025, steps=STEPS, lr=LEARNING_RATE,
            parent_adapter=PARENT, training_samples=training_rows,
        )
        if not result.get("ok"):
            raise RuntimeError("TRAINING_FAILED:" + json.dumps(result))
        run["training"] = result
        run["candidate_sha256"] = sha_file(DEST / "adapter_model.safetensors")
        run["status"] = "TRAINED_CANDIDATE"
    except Exception as exc:
        run["status"] = "TRAINING_FAILED"
        run["training_error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if quiesced:
            try:
                request("/v1/resume", {"adapter_dir": str(LIVE)})
            except Exception as exc:
                run["restore_error"] = f"{type(exc).__name__}: {exc}"
    try:
        after = request("/v1/status")
        run["live_after"] = after
        run["live_restored"] = after.get("status") == "ACTIVE" and after.get("active_adapter") == LIVE.name
    except Exception as exc:
        run["live_restored"] = False
        run["restore_status_error"] = f"{type(exc).__name__}: {exc}"
    run["store_sha256_after"] = sha_file(store.DB_PATH)
    run["store_unchanged_during_training"] = run["store_sha256_after"] == db_hash_before
    run["receipt_sha256"] = canonical_hash(run)
    write_authorized(RUN_OUT, run)
    print(json.dumps({
        "dataset_receipt": str(DATA_OUT),
        "training_receipt": str(RUN_OUT),
        "database_versions": len(rows),
        "unique_examples": len(samples),
        "training_rows": len(training_rows),
        "status": run["status"],
        "candidate_sha256": run.get("candidate_sha256"),
        "live_restored": run.get("live_restored"),
        "store_unchanged_during_training": run["store_unchanged_during_training"],
        "promoted": False,
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if run["status"] == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
