"""Train a candidate-only mixed Python/Rust adapter from gated disjoint data.

The source curricula are immutable, hash-checked receipts. The frozen 100-task
suite remains evaluation-only. Training starts from epoch 10025 and writes only
epoch 10026 plus candidate run receipts; the live adapter is restored afterward.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]

import viv_sleep_trainer as trainer
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10025"
DEST = ROOT / "epoch_10026"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
NEURAL_RUNS = HERE / "learning" / "neural_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
FUNCTION_DB = NEURAL_RUNS / "candidate_verified_functions.sqlite3"
SOURCES = [
    RUNS / "candidate_python_training_10017.json",
    RUNS / "candidate_rust_training_10018.json",
    RUNS / "candidate_rust_training_10020.json",
    RUNS / "candidate_rust_training_10022.json",
    NEURAL_RUNS / "candidate_store_training_10025.json",
]
DATA_OUT = NEURAL_RUNS / "candidate_mixed_training_10026.json"
RUN_OUT = NEURAL_RUNS / "candidate_mixed_training_run_10026.json"
SEED, LEARNING_RATE, REPEATS = 20261129, 5e-7, 2
EOS = "<｜end▁of▁sentence｜>"


def canonical_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)


def write_authorized(path: Path, value: dict) -> None:
    decision = PrivacyCore().authorize_file_write(str(path))
    if decision.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate training artifact: {decision}")
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def task_name(sample: dict, lang: str) -> str:
    prompt = str(sample.get("prompt", ""))
    pattern = r"\bdef\s+([A-Za-z_]\w*)\s*\(" if lang == "python" else r"\bpub\s+fn\s+([A-Za-z_]\w*)\s*\("
    match = re.search(pattern, prompt)
    if not match:
        raise ValueError(f"TRAINING_FUNCTION_NAME_MISSING:{sample.get('id')}")
    return match.group(1)


def code_from_sample(sample: dict, lang: str) -> str:
    completion = str(sample["completion"])
    if completion.endswith(EOS):
        completion = completion[:-len(EOS)]
    if lang == "python":
        completion = re.sub(r"^```(?:python)?\s*", "", completion.strip())
        completion = re.sub(r"\s*```$", "", completion).rstrip()
        return completion
    match = re.search(r"pub\s+fn\s+[A-Za-z_]\w*\s*\(.*?\)\s*(?:->.*)?\{\s*$",
                      str(sample["prompt"]), re.S)
    if not match:
        raise ValueError(f"RUST_SIGNATURE_MISSING:{sample.get('id')}")
    return match.group(0).rstrip() + completion


def validate_source(path: Path, suite_hash: str) -> tuple[dict, str]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    claimed = envelope.pop("receipt_sha256", None)
    if canonical_hash(envelope) != claimed:
        raise ValueError(f"SOURCE_RECEIPT_HASH_MISMATCH:{path.name}")
    envelope["receipt_sha256"] = claimed
    if envelope.get("heldout_suite_sha256") != suite_hash:
        raise ValueError(f"SOURCE_SUITE_MISMATCH:{path.name}")
    if envelope.get("heldout_id_overlap") or envelope.get("heldout_function_name_overlap"):
        raise ValueError(f"SOURCE_REPORTED_HELDOUT_OVERLAP:{path.name}")
    samples = envelope.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError(f"SOURCE_SAMPLES_MISSING:{path.name}")
    expected_training_hash = envelope.get("training_sha256")
    if expected_training_hash not in {canonical_hash(samples), canonical_hash(samples * 2)}:
        raise ValueError(f"SOURCE_TRAINING_HASH_MISMATCH:{path.name}")
    gates = envelope.get("gate_results")
    if gates is not None:
        sample_ids = [str(row["id"]) for row in samples]
        gate_ids = [str(row["id"]) for row in gates]
        if sorted(sample_ids) != sorted(gate_ids) or not all(row.get("passed") is True for row in gates):
            raise ValueError(f"SOURCE_GATE_RECEIPT_INCOMPLETE:{path.name}")
    return envelope, file_hash(path)


def verify_store_sample(sample: dict) -> None:
    if not FUNCTION_DB.is_file():
        raise FileNotFoundError(FUNCTION_DB)
    uri = FUNCTION_DB.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_FUNCTION_DB_QUICK_CHECK_FAILED")
        row = db.execute("""
            SELECT f.function_key,f.language,v.task_id,v.code_sha256,v.tests_sha256,
                   v.gate_name,v.gate_status,v.gate_output,v.gate_receipt_sha256,v.admitted_utc
            FROM function_versions v JOIN functions f USING(function_key)
            WHERE v.version_id=?
        """, (sample["version_id"],)).fetchone()
    if row is None:
        raise ValueError("CANDIDATE_STORE_VERSION_MISSING")
    (function_key, lang, task_id, code_sha, tests_sha, gate, status,
     output, receipt_sha, created) = row
    if (lang != "python" or status != "ALLOW" or task_id != sample["id"].removeprefix("candidate_store_v9_")
            or code_sha != sample["code_sha256"] or receipt_sha != sample["gate_receipt_sha256"]):
        raise ValueError("CANDIDATE_STORE_GATE_RECORD_MISMATCH")
    gate_receipt = {"task_id": task_id, "language": lang, "function_key": function_key,
                    "code_sha256": code_sha, "tests_sha256": tests_sha, "gate": gate,
                    "status": status, "output": output, "created_utc": created}
    if canonical_hash(gate_receipt) != receipt_sha:
        raise ValueError("CANDIDATE_STORE_GATE_RECEIPT_HASH_MISMATCH")


def main() -> int:
    for path in (DATA_OUT, RUN_OUT, DEST):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite candidate artifact: {path}")
    for path in (*SOURCES, SUITE, PARENT / "adapter_model.safetensors"):
        if not path.is_file():
            raise FileNotFoundError(path)

    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if suite_hash != canonical_hash(suite):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {str(row["id"]) for row in suite["held_out"]}
    held_names = {(row["lang"], re.search(
        r"\bdef\s+([A-Za-z_]\w*)\s*\(" if row["lang"] == "python" else
        r"\bpub\s+fn\s+([A-Za-z_]\w*)\s*\(", row["spec"]).group(1))
        for row in suite["held_out"]}

    samples: list[dict] = []
    ids: set[str] = set()
    names: set[tuple[str, str]] = set()
    source_manifest = []
    store_source = None
    for path in SOURCES:
        envelope, digest = validate_source(path, suite_hash)
        source_manifest.append({"path": str(path), "file_sha256": digest,
                                "receipt_sha256": envelope["receipt_sha256"],
                                "schema": envelope.get("schema"),
                                "sample_count": len(envelope["samples"])})
        rows = envelope["samples"]
        if path.name == "candidate_store_training_10025.json":
            rows = [row for row in rows if str(row["id"]).endswith(
                "template_adapters_as_posix_model_trial_10024")]
            if len(rows) != 1:
                raise ValueError("EXPECTED_ONE_NEW_AS_POSIX_STORE_SAMPLE")
            verify_store_sample(rows[0])
            store_source = str(path)
        for row in rows:
            lang = "python" if "python" in str(row.get("category", "")) else "rust"
            if path.name == "candidate_store_training_10025.json":
                lang = "python"
            ident = str(row["id"])
            name = task_name(row, lang)
            key = (lang, name)
            if ident in held_ids or key in held_names:
                raise ValueError(f"FROZEN_HELDOUT_OVERLAP:{ident}:{key}")
            if ident in ids or key in names:
                raise ValueError(f"DUPLICATE_TRAINING_EXAMPLE:{ident}:{key}")
            code = code_from_sample(row, lang)
            if hashlib.sha256(code.encode("utf-8")).hexdigest() != row.get("code_sha256"):
                raise ValueError(f"TRAINING_CODE_HASH_MISMATCH:{ident}")
            ids.add(ident)
            names.add(key)
            samples.append({**row, "language": lang, "function_name": name,
                            "source_dataset": path.name})

    if store_source is None:
        raise ValueError("CANDIDATE_STORE_SAMPLE_NOT_VERIFIED")
    counts = {lang: sum(row["language"] == lang for row in samples)
              for lang in ("python", "rust")}
    if counts != {"python": 13, "rust": 28}:
        raise ValueError(f"UNEXPECTED_LANGUAGE_COUNTS:{counts}")

    # Each source receipt reports its held-out checks. Independently compare all
    # combined task IDs and function names against the canonical frozen split.
    if ids & held_ids or names & held_names:
        raise ValueError("COMBINED_TRAINING_HELDOUT_OVERLAP")

    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    seed = SEED
    random.Random(seed).shuffle(samples)
    training_rows = samples * REPEATS
    dataset = {
        "schema": "viv_candidate_mixed_gate_accepted_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_candidate": str(PARENT),
        "parent_sha256": file_hash(PARENT / "adapter_model.safetensors"),
        "frozen_suite_path": str(SUITE), "frozen_suite_sha256": suite_hash,
        "source_receipts": source_manifest,
        "source_samples": len(samples), "language_counts": counts,
        "repeat_count": REPEATS, "training_rows": len(training_rows),
        "heldout_id_overlap": [], "heldout_function_name_overlap": [],
        "sample_ids": sorted(ids),
        "samples": samples,
        "training_sha256": canonical_hash(training_rows),
        "live_adapter_at_build": before.get("active_adapter"),
        "promoted": False, "topology_write": False, "persistent_memory_write": False,
    }
    dataset["receipt_sha256"] = canonical_hash(dataset)
    write_authorized(DATA_OUT, dataset)

    import torch
    from transformers import set_seed
    random.seed(seed)
    torch.manual_seed(seed)
    set_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    run = {
        "schema": "viv_candidate_mixed_coding_training_run_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA_OUT), "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_sha256": dataset["training_sha256"],
        "source_receipts": source_manifest, "source_samples": len(samples),
        "language_counts": counts, "training_rows": len(training_rows),
        "seed": seed, "learning_rate": LEARNING_RATE,
        "steps_requested": len(training_rows), "parent": str(PARENT),
        "parent_sha256": dataset["parent_sha256"], "frozen_suite_sha256": suite_hash,
        "live_before": before, "promoted": False, "topology_write": False,
        "persistent_memory_write": False,
    }
    quiesced = False
    try:
        state = request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(state))
        quiesced = True
        result = trainer.run_sleep_training(
            epoch=10026, steps=len(training_rows), lr=LEARNING_RATE,
            parent_adapter=PARENT, training_samples=training_rows,
        )
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
    run["receipt_sha256"] = canonical_hash(run)
    write_authorized(RUN_OUT, run)
    print(json.dumps({
        "dataset_receipt": str(DATA_OUT), "training_receipt": str(RUN_OUT),
        "status": run["status"], "candidate_sha256": run.get("candidate_sha256"),
        "source_samples": len(samples), "language_counts": counts,
        "training_rows": len(training_rows), "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "promoted": False,
    }, ensure_ascii=False, indent=2), flush=True)
    return 0 if run["status"] == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
