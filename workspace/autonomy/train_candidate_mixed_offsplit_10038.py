"""Candidate-only mixed-language update from disjoint ALLOW examples.

Retains epoch10027 Python samples, adds eight verified Python functions and
twenty verified Rust functions from the isolated function store, then trains
an unpromoted candidate from epoch10037. The frozen evaluation split is used
only to enforce task/name disjointness.
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
import train_candidate_rust_transfer_focus_10037 as prior
import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10037"
DEST = ROOT / "epoch_10038"
NEURAL = HERE / "learning" / "neural_runs"
SUITE = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v2_1.json"
FUNCTION_DB = NEURAL / "candidate_verified_functions.sqlite3"
BASE_DATA = NEURAL / "candidate_rust_weighted_training_10027.json"
DATA_OUT = NEURAL / "candidate_mixed_offsplit_training_10038.json"
RUN_OUT = NEURAL / "candidate_mixed_offsplit_training_run_10038.json"
LIVE = runtime.LIVE
SEED = 20261113
LEARNING_RATE = 5e-7
PYTHON_REPEATS = 4
RUST_REPEATS = 2
EOS = "<｜end▁of▁sentence｜>"
PYTHON_SOURCE_KIND = "epoch_10024_gate_passed_training_example"
RUST_SOURCE_KIND = "model_proposal_epoch_10027"


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


def _python_prompt(name: str, spec: str, code: str, task_id: str,
                   source_kind: str, source_sha256: str, tests_sha256: str,
                   receipt_sha256: str) -> dict:
    match = re.search(r"\bdef\s+([A-Za-z_]\w*)\s*\(", spec)
    if not match or match.group(1) != name:
        raise ValueError(f"PYTHON_SPEC_ENTRYPOINT_MISMATCH:{name}")
    prompt = (
        "SYSTEM: Write one self-contained, correct, standard-library python function. "
        "Do not depend on other top-level helpers. Return only one fenced code block; "
        "no tests or explanation.\n\nUSER: Implement: " + spec
        + "\n\nASSISTANT:"
    )
    completion = f"```python\n{code.strip()}\n```{EOS}"
    return {
        "id": task_id, "language": "python", "domain": "verified_offsplit",
        "function_name": name, "prompt": prompt, "completion": completion,
        "function_code": code, "source_kind": source_kind,
        "source_dataset": str(FUNCTION_DB), "source_sha256": source_sha256,
        "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "tests_sha256": tests_sha256, "gate_name": "existing_body_gate",
        "gate_status": "ALLOW", "gate_receipt_sha256": receipt_sha256,
        "task_id": task_id,
    }


def _rust_prompt(name: str, spec: str, code: str, task_id: str,
                 source_kind: str, source_sha256: str, tests_sha256: str,
                 receipt_sha256: str) -> dict:
    parsed = runtime.rust_signature(spec)
    if not parsed:
        raise ValueError(f"RUST_SPEC_SIGNATURE_INVALID:{name}")
    header, description = parsed
    code_open = code.find("{", code.find("fn "))
    code_close = code.rfind("}")
    if code_open < 0 or code_close <= code_open:
        raise ValueError(f"RUST_STORED_FUNCTION_INVALID:{name}")
    body = code[code_open + 1:code_close].strip()
    prompt = (
        "# Implement one self-contained, correct standard-library Rust function. "
        "Do not depend on other top-level helpers. Handle empty and boundary inputs.\n"
        f"# Task: {description}\n{header}\n"
    )
    return {
        "id": task_id, "language": "rust", "domain": "verified_offsplit",
        "function_name": name, "prompt": prompt,
        "completion": body + "\n}\n" + EOS,
        "function_code": code, "source_kind": source_kind,
        "source_dataset": str(FUNCTION_DB), "source_sha256": source_sha256,
        "code_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
        "tests_sha256": tests_sha256, "gate_name": "existing_body_gate",
        "gate_status": "ALLOW", "gate_receipt_sha256": receipt_sha256,
        "task_id": task_id,
    }


def verified_store_samples(suite_hash: str, held_ids: set[str],
                           held_names: set[tuple[str, str]],
                           base_names: set[tuple[str, str]]) -> tuple[list[dict], dict]:
    db_hash_before = file_hash(FUNCTION_DB)
    uri = f"file:{FUNCTION_DB.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
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
            WHERE v.gate_status='ALLOW'
            ORDER BY f.language,f.function_name,v.version_id
        """).fetchall()

    selected: list[dict] = []
    seen: set[tuple[str, str]] = set(base_names)
    for row in rows:
        lang = str(row["language"])
        kind = str(row["source_kind"])
        if not ((lang == "python" and kind == PYTHON_SOURCE_KIND)
                or (lang == "rust" and kind == RUST_SOURCE_KIND)):
            continue
        name = str(row["function_name"])
        task_id = str(row["task_id"])
        pair = (lang, name)
        if task_id in held_ids or pair in held_names:
            raise ValueError(f"HELDOUT_STORE_OVERLAP:{lang}:{task_id}:{name}")
        if pair in seen:
            raise ValueError(f"DUPLICATE_SELECTED_FUNCTION:{lang}:{name}")
        code = str(row["code"])
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if code_hash != row["code_sha256"]:
            raise ValueError(f"STORE_CODE_HASH_MISMATCH:{task_id}")
        evidence = {
            "task_id": task_id, "language": lang,
            "function_key": row["function_key"], "code_sha256": row["code_sha256"],
            "tests_sha256": row["tests_sha256"], "gate": row["gate_name"],
            "status": row["gate_status"], "output": row["gate_output"],
            "created_utc": row["admitted_utc"],
        }
        if canonical_hash(evidence) != row["gate_receipt_sha256"]:
            raise ValueError(f"STORE_RECEIPT_HASH_MISMATCH:{task_id}")
        spec = str(row["specification"])
        if lang == "python":
            sample = _python_prompt(name, spec, code, task_id, kind,
                                    str(row["source_sha256"]), str(row["tests_sha256"]),
                                    str(row["gate_receipt_sha256"]))
        else:
            sample = _rust_prompt(name, spec, code, task_id, kind,
                                  str(row["source_sha256"]), str(row["tests_sha256"]),
                                  str(row["gate_receipt_sha256"]))
        selected.append(sample)
        seen.add(pair)

    counts = {lang: sum(x["language"] == lang for x in selected)
              for lang in ("python", "rust")}
    if counts != {"python": 8, "rust": 20}:
        raise ValueError(f"OFFSPLIT_ALLOW_COUNTS_INVALID:{counts}")
    if file_hash(FUNCTION_DB) != db_hash_before:
        raise RuntimeError("FUNCTION_STORE_CHANGED_DURING_READ")
    return selected, {"path": str(FUNCTION_DB), "sha256": db_hash_before,
                      "quick_check": "ok", "selected_counts": counts,
                      "verified_gate_receipts": len(selected)}


def main() -> int:
    for path in (PARENT / "adapter_model.safetensors", BASE_DATA,
                 FUNCTION_DB, SUITE):
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

    old_rust, retained_python, base_manifest = prior.load_old_samples(
        suite_hash, held_ids, held_names)
    base_names = {("python", str(row["function_name"]))
                  for row in retained_python}
    additions, store_manifest = verified_store_samples(
        suite_hash, held_ids, held_names, base_names)
    new_python = [x for x in additions if x["language"] == "python"]
    new_rust = [x for x in additions if x["language"] == "rust"]
    samples = retained_python + additions
    for sample in samples:
        if (sample.get("task_id") in held_ids
                or (sample["language"], sample["function_name"]) in held_names):
            raise ValueError("HELDOUT_SAMPLE_REJECTED:" + str(sample.get("id")))

    training_rows = (retained_python + new_python * PYTHON_REPEATS
                     + new_rust * RUST_REPEATS)
    random.Random(SEED).shuffle(training_rows)
    counts = {lang: sum(row["language"] == lang for row in samples)
              for lang in ("python", "rust")}
    expected_rows = len(retained_python) + len(new_python) * PYTHON_REPEATS + len(new_rust) * RUST_REPEATS
    if counts != {"python": 21, "rust": 20} or len(training_rows) != expected_rows:
        raise ValueError(f"TRAINING_COUNTS_INVALID:{counts}:{len(training_rows)}")

    before = runtime.evaluator.request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    parent_hash = file_hash(PARENT / "adapter_model.safetensors")
    store_hash = file_hash(FUNCTION_DB)
    dataset = {
        "schema": "viv_candidate_mixed_offsplit_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_candidate": str(PARENT), "parent_sha256": parent_hash,
        "base_dataset": base_manifest, "verified_function_store": store_manifest,
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": suite_hash,
        "accepted_source_counts": {
            "retained_python": len(retained_python),
            "validated_prior_rust_not_replayed": len(old_rust),
            "new_gate_accepted_python": len(new_python),
            "new_gate_accepted_rust": len(new_rust),
        },
        "language_counts": counts,
        "repeat_policy": {"retained_python": 1, "new_python": PYTHON_REPEATS,
                          "new_rust": RUST_REPEATS},
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
        "schema": "viv_candidate_mixed_offsplit_training_run_v1",
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
            epoch=10038, steps=len(training_rows), lr=LEARNING_RATE,
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
        "python_accepted": len(new_python), "rust_accepted": len(new_rust),
        "retained_python": len(retained_python), "training_rows": len(training_rows),
        "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "promoted": False,
    }, indent=2), flush=True)
    return 0 if run.get("status") == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
