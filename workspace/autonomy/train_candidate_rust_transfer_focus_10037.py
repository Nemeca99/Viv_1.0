"""Candidate-only continuation from disjoint, gate-accepted Rust examples.

Combines retained base examples with fifteen newly admitted off-split Rust
transfer examples, at four Rust repetitions from the read-only candidate store.
The frozen suite is used only to enforce disjointness and is never training
input. Viv's live adapter, memory, topology, and function store are untouched.
"""
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
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import candidate_coding_runtime_v1 as runtime
import train_candidate_mixed_coding_10026 as source
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10027"
DEST = ROOT / "epoch_10037"
NEURAL = HERE / "learning" / "neural_runs"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
BASE_DATA = NEURAL / "candidate_rust_weighted_training_10027.json"
FUNCTION_DB = NEURAL / "candidate_verified_functions.sqlite3"
DATA_OUT = NEURAL / "candidate_rust_combined_offsplit_training_10037.json"
RUN_OUT = NEURAL / "candidate_rust_combined_offsplit_training_run_10037.json"
LIVE = runtime.LIVE
SEED = 20261113
LEARNING_RATE = 5e-7
RUST_REPEATS = 4
EOS = "<｜end▁of▁sentence｜>"


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new(path: Path, value: dict) -> dict:
    authorization = PrivacyCore().authorize_file_write(str(path))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied {path}: {authorization}")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    return authorization


def load_old_samples(suite_hash: str, held_ids: set[str],
                     held_names: set[tuple[str, str]]) -> tuple[list[dict], list[dict], dict]:
    envelope = json.loads(BASE_DATA.read_text(encoding="utf-8"))
    claimed = envelope.pop("receipt_sha256", None)
    if canonical_hash(envelope) != claimed:
        raise ValueError("BASE_DATASET_RECEIPT_HASH_MISMATCH")
    envelope["receipt_sha256"] = claimed
    if envelope.get("frozen_suite_sha256") != suite_hash:
        raise ValueError("BASE_DATASET_SUITE_MISMATCH")
    if envelope.get("promoted") is not False:
        raise ValueError("BASE_DATASET_PROMOTION_STATE_INVALID")

    verified_sources = []
    for source_record in envelope.get("source_receipts", []):
        source_path = Path(source_record["path"])
        validated, digest = source.validate_source(source_path, suite_hash)
        if (digest != source_record["file_sha256"]
                or validated.get("receipt_sha256") != source_record["receipt_sha256"]):
            raise ValueError("BASE_SOURCE_RECEIPT_MISMATCH:" + source_path.name)
        verified_sources.append({
            "path": str(source_path), "file_sha256": digest,
            "receipt_sha256": validated["receipt_sha256"],
            "sample_count": len(validated["samples"]),
        })

    all_samples = envelope.get("samples", [])
    if len(all_samples) != 41:
        raise ValueError(f"BASE_SAMPLE_COUNT_INVALID:{len(all_samples)}")
    rust_samples = [row for row in all_samples if row.get("language") == "rust"]
    python_samples = [row for row in all_samples if row.get("language") == "python"]
    if len(rust_samples) != 28:
        raise ValueError(f"BASE_RUST_SAMPLE_COUNT_INVALID:{len(rust_samples)}")
    if len(python_samples) != 13:
        raise ValueError(f"BASE_PYTHON_SAMPLE_COUNT_INVALID:{len(python_samples)}")
    ids: set[str] = set()
    names: set[tuple[str, str]] = set()
    for sample in all_samples:
        language = str(sample.get("language"))
        if language not in {"python", "rust"}:
            raise ValueError("BASE_SAMPLE_LANGUAGE_INVALID:" + language)
        code = source.code_from_sample(sample, language)
        if hashlib.sha256(code.encode("utf-8")).hexdigest() != sample.get("code_sha256"):
            raise ValueError("BASE_CODE_HASH_MISMATCH:" + str(sample.get("id")))
        name = (language, str(sample["function_name"]))
        sample_id = str(sample["id"])
        if sample_id in held_ids or name in held_names:
            raise ValueError("HELDOUT_OVERLAP_IN_BASE_RUST:" + sample_id)
        if sample_id in ids or name in names:
            raise ValueError("DUPLICATE_BASE_RUST_SAMPLE:" + sample_id)
        ids.add(sample_id)
        names.add(name)
    return rust_samples, python_samples, {
        "path": str(BASE_DATA), "file_sha256": file_hash(BASE_DATA),
        "receipt_sha256": claimed, "validated_source_receipts": verified_sources,
        "rust_sample_count": len(rust_samples),
    }


def store_samples(suite_hash: str, held_ids: set[str],
                  held_names: set[tuple[str, str]],
                  existing_names: set[tuple[str, str]]) -> tuple[list[dict], dict]:
    db_hash_before = file_hash(FUNCTION_DB)
    with sqlite3.connect(FUNCTION_DB.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_FUNCTION_STORE_QUICK_CHECK_FAILED")
        db.row_factory = sqlite3.Row
        rows = db.execute("""
            SELECT f.function_key,f.language,f.domain,f.function_name,
                   f.specification,v.version_id,v.task_id,v.source_kind,
                   v.source_sha256,v.code,v.code_sha256,v.tests_sha256,
                   v.gate_name,v.gate_status,v.gate_output,
                   v.gate_receipt_sha256,v.admitted_utc
            FROM active_versions a
            JOIN functions f USING(function_key)
            JOIN function_versions v USING(version_id)
            WHERE f.language='rust'
            ORDER BY f.function_name
        """).fetchall()

    selected: list[dict] = []
    seen_names = set(existing_names)
    excluded = []
    for row in rows:
        name = str(row["function_name"])
        task_id = str(row["task_id"])
        pair = ("rust", name)
        if task_id in held_ids or pair in held_names:
            raise ValueError(f"HELDOUT_OVERLAP_IN_STORE:{task_id}:{name}")
        if row["gate_status"] != "ALLOW":
            raise ValueError(f"STORE_GATE_NOT_ALLOW:{task_id}")
        if hashlib.sha256(row["code"].encode("utf-8")).hexdigest() != row["code_sha256"]:
            raise ValueError(f"STORE_CODE_HASH_MISMATCH:{task_id}")
        evidence = {
            "task_id": task_id, "language": "rust",
            "function_key": row["function_key"],
            "code_sha256": row["code_sha256"],
            "tests_sha256": row["tests_sha256"], "gate": row["gate_name"],
            "status": row["gate_status"], "output": row["gate_output"],
            "created_utc": row["admitted_utc"],
        }
        if canonical_hash(evidence) != row["gate_receipt_sha256"]:
            raise ValueError(f"STORE_GATE_RECEIPT_HASH_MISMATCH:{task_id}")
        if row["source_kind"].startswith("first_party_source:"):
            excluded.append({"task_id": task_id, "name": name,
                             "reason": "first-party version duplicates a stronger tested contract"})
            continue
        if pair in seen_names:
            raise ValueError(f"DUPLICATE_STORE_FUNCTION:{name}")

        parsed = runtime.rust_signature(row["specification"])
        if not parsed:
            raise ValueError(f"STORE_RUST_SIGNATURE_INVALID:{name}")
        header, description = parsed
        opening = row["code"].find("{", row["code"].find("fn "))
        closing = row["code"].rfind("}")
        if opening < 0 or closing <= opening:
            raise ValueError(f"STORE_RUST_BODY_INVALID:{name}")
        body = row["code"][opening + 1:closing].strip()
        grounding = runtime.uml_context_for_task({"spec": row["specification"]})
        context = grounding.get("prompt_context", "")
        uml_note = "" if not context else "# Deterministic UML reference:\n" + "\n".join(
            "# " + line for line in context.splitlines()) + "\n"
        prompt = (
            "# Implement one self-contained, correct standard-library Rust function. "
            "Do not depend on other top-level helpers. Handle empty and boundary inputs.\n"
            + uml_note + f"# Task: {description}\n{header}\n"
        )
        selected.append({
            "id": f"candidate_store_rust_v{row['version_id']}_{task_id}",
            "language": "rust", "domain": row["domain"], "function_name": name,
            "prompt": prompt, "completion": body + "\n}\n" + EOS,
            "source_kind": row["source_kind"], "source_dataset": str(FUNCTION_DB),
            "spec_sha256": hashlib.sha256(row["specification"].encode("utf-8")).hexdigest(),
            "code_sha256": row["code_sha256"], "tests_sha256": row["tests_sha256"],
            "function_code": row["code"], "function_key": row["function_key"],
            "version_id": row["version_id"], "gate_name": row["gate_name"],
            "gate_status": row["gate_status"],
            "gate_receipt_sha256": row["gate_receipt_sha256"],
            "task_id": task_id, "source_sha256": row["source_sha256"],
        })
        seen_names.add(pair)

    selected = [row for row in selected if str(row["task_id"]).startswith((
        "candidate_rust_transfer_10031_", "candidate_rust_transfer_10034_", "candidate_rust_transfer_10036_"))]
    if len(selected) != 15:
        raise ValueError(f"EXPECTED_FIFTEEN_NEW_TRANSFER_RUST_EXAMPLES_GOT:{len(selected)}")
    if file_hash(FUNCTION_DB) != db_hash_before:
        raise RuntimeError("CANDIDATE_FUNCTION_STORE_CHANGED_DURING_READ")
    return selected, {
        "path": str(FUNCTION_DB), "sha256": db_hash_before,
        "quick_check": "ok", "selected_examples": len(selected),
        "excluded_rows": excluded,
    }


def main() -> int:
    for path in (BASE_DATA, FUNCTION_DB, SUITE,
                 PARENT / "adapter_model.safetensors"):
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
    for task in suite["held_out"]:
        match = re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(",
                          task.get("spec", ""))
        if match:
            held_names.add((task["lang"], match.group(1)))

    old_rust, python_samples, base_manifest = load_old_samples(
        suite_hash, held_ids, held_names)
    old_names = {("rust", str(row["function_name"])) for row in old_rust}
    new_rust, store_manifest = store_samples(suite_hash, held_ids, held_names, old_names)
    samples = python_samples + new_rust
    training_rows = python_samples + new_rust * RUST_REPEATS
    random.Random(SEED).shuffle(training_rows)
    counts = {lang: sum(row["language"] == lang for row in samples)
              for lang in ("python", "rust")}
    if counts != {"python": 13, "rust": 15}:
        raise ValueError("TRAINING_LANGUAGE_COUNTS_INVALID:" + json.dumps(counts))
    for sample in samples:
        if (sample["id"] in held_ids
                or (sample["language"], sample["function_name"]) in held_names):
            raise ValueError("HELDOUT_SAMPLE_REJECTED:" + sample["id"])

    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    parent_hash = file_hash(PARENT / "adapter_model.safetensors")
    store_hash = file_hash(FUNCTION_DB)
    dataset = {
        "schema": "viv_candidate_rust_combined_offsplit_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_candidate": str(PARENT), "parent_sha256": parent_hash,
        "base_dataset": base_manifest, "verified_function_store": store_manifest,
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": suite_hash,
        "accepted_source_counts": {"prior_rust_replay": 0,
                                    "new_store_rust": len(new_rust),
                                     "base_rust_validated_not_replayed": len(old_rust),
                                    "prior_python_retention": len(python_samples)},
        "language_counts": counts,
        "repeat_policy": {"python": 1, "rust": RUST_REPEATS},
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
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"

    run = {
        "schema": "viv_candidate_rust_combined_offsplit_training_run_v1",
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
            epoch=10037, steps=len(training_rows), lr=LEARNING_RATE,
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
        "samples": len(samples), "python_samples": len(python_samples),
        "rust_samples": len(new_rust),
        "validated_old_rust_not_replayed": len(old_rust),
        "training_rows": len(training_rows), "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "promoted": False,
    }, indent=2), flush=True)
    return 0 if run.get("status") == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())

