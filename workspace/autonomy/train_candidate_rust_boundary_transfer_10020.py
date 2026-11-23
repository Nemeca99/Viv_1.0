"""Train an isolated Rust boundary-transfer candidate from the Python-best parent."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import random
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]
import viv_code_learning_loop as gates

RUNS = HERE / "learning" / "deepseek_candidate_runs"
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10016"
DEST = ROOT / "epoch_10020"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
SUITE = RUNS / "frozen_code_eval_v2_1.json"
DATA = RUNS / "candidate_rust_training_10020.json"
PREFLIGHT = RUNS / "candidate_rust_preflight_10020.json"
RECEIPT = RUNS / "candidate_rust_training_run_10020.json"
API = "http://127.0.0.1:1234"
EOS = "<｜end▁of▁sentence｜>"
EPOCH = 10020
CHECK_PRIOR_FUNCTION_NAMES = True
SEED, LR, STEPS, REPEATS = 20261143, 1e-6, 24, 3

EXAMPLES = [
    ("first_adjacent_repeat", "pub fn first_adjacent_repeat(values: &[i32]) -> Option<i32>: return a value when it equals the next value, or None",
     "pub fn first_adjacent_repeat(values: &[i32]) -> Option<i32> { values.windows(2).find(|pair| pair[0] == pair[1]).map(|pair| pair[0]) }",
     "assert_eq!(first_adjacent_repeat(&[1,2,2,3]),Some(2)); assert_eq!(first_adjacent_repeat(&[1,2,3]),None); assert_eq!(first_adjacent_repeat(&[]),None); assert_eq!(first_adjacent_repeat(&[4]),None);"),
    ("count_adjacent_changes", "pub fn count_adjacent_changes(values: &[i32]) -> usize: count neighboring pairs whose values differ",
     "pub fn count_adjacent_changes(values: &[i32]) -> usize { values.windows(2).filter(|pair| pair[0] != pair[1]).count() }",
     "assert_eq!(count_adjacent_changes(&[1,1,2,2,1]),2); assert_eq!(count_adjacent_changes(&[]),0); assert_eq!(count_adjacent_changes(&[9]),0);"),
    ("safe_wrapped_index", "pub fn safe_wrapped_index(start: usize, offset: usize, length: usize) -> Option<usize>: advance cyclically by offset; return None when length is zero",
     "pub fn safe_wrapped_index(start: usize, offset: usize, length: usize) -> Option<usize> { if length == 0 { return None; } let start = start % length; let offset = offset % length; Some(if offset == 0 { start } else if start >= length - offset { start - (length - offset) } else { start + offset }) }",
     "assert_eq!(safe_wrapped_index(1,2,5),Some(3)); assert_eq!(safe_wrapped_index(4,3,5),Some(2)); assert_eq!(safe_wrapped_index(8,0,5),Some(3)); assert_eq!(safe_wrapped_index(0,1,0),None);"),
    ("checked_quotient", "pub fn checked_quotient(a: i64, b: i64) -> Option<i64>: divide with truncation toward zero; return None for zero divisor or overflow",
     "pub fn checked_quotient(a: i64, b: i64) -> Option<i64> { a.checked_div(b) }",
     "assert_eq!(checked_quotient(7,3),Some(2)); assert_eq!(checked_quotient(-7,3),Some(-2)); assert_eq!(checked_quotient(1,0),None); assert_eq!(checked_quotient(i64::MIN,-1),None);"),
    ("integer_sqrt_floor", "pub fn integer_sqrt_floor(n: u64) -> u64: return the greatest integer whose square is at most n without floating point",
     "pub fn integer_sqrt_floor(n: u64) -> u64 { let (mut low, mut high) = (0u64, n); while low <= high { let mid = low + (high - low) / 2; if mid == 0 || mid <= n / mid { low = mid + 1; } else { high = mid - 1; } } high }",
     "assert_eq!(integer_sqrt_floor(0),0); assert_eq!(integer_sqrt_floor(1),1); assert_eq!(integer_sqrt_floor(15),3); assert_eq!(integer_sqrt_floor(16),4); assert_eq!(integer_sqrt_floor(u64::MAX),u32::MAX as u64);"),
    ("optional_minimum", "pub fn optional_minimum(values: &[i32]) -> Option<i32>: return the smallest value, or None for an empty slice",
     "pub fn optional_minimum(values: &[i32]) -> Option<i32> { values.iter().copied().min() }",
     "assert_eq!(optional_minimum(&[4,-2,7]),Some(-2)); assert_eq!(optional_minimum(&[]),None); assert_eq!(optional_minimum(&[5]),Some(5));"),
    ("unicode_uppercase_unit_count", "pub fn unicode_uppercase_unit_count(text: &str) -> usize: count Unicode scalar values emitted by uppercasing every character",
     "pub fn unicode_uppercase_unit_count(text: &str) -> usize { text.chars().flat_map(char::to_uppercase).count() }",
     "assert_eq!(unicode_uppercase_unit_count(\"abc\"),3); assert_eq!(unicode_uppercase_unit_count(\"ß\"),2); assert_eq!(unicode_uppercase_unit_count(\"\"),0);"),
    ("minimum_maximum_pair", "pub fn minimum_maximum_pair(values: &[i32]) -> Option<(i32, i32)>: return the minimum and maximum, or None when empty",
     "pub fn minimum_maximum_pair(values: &[i32]) -> Option<(i32, i32)> { let mut iter = values.iter().copied(); let first = iter.next()?; let (mut low, mut high) = (first, first); for value in iter { low = low.min(value); high = high.max(value); } Some((low, high)) }",
     "assert_eq!(minimum_maximum_pair(&[3,-2,8]),Some((-2,8))); assert_eq!(minimum_maximum_pair(&[]),None); assert_eq!(minimum_maximum_pair(&[4]),Some((4,4)));"),
]

def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=body, headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)

def fn_name(source: str) -> str | None:
    match = re.search(r"pub\s+fn\s+([A-Za-z_]\w*)\s*\(", source)
    return match.group(1) if match else None

def main() -> int:
    for path in (DATA, PREFLIGHT, RECEIPT):
        if path.exists():
            raise FileExistsError(path)
    if DEST.exists():
        raise FileExistsError(DEST)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if digest(suite) != suite_hash:
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held = [row for row in suite["held_out"] if row["lang"] == "rust"]
    if len(held) != 50:
        raise ValueError("EXPECTED_50_RUST_HELDOUT_TASKS")
    held_ids = {row["id"] for row in held}
    held_names = {fn_name(row["spec"]) for row in held}
    old_ids: set[str] = set()
    old_names: set[str] = set()
    for path in RUNS.glob("*training*.json"):
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in previous.get("samples", []):
            if not isinstance(row, dict):
                continue
            if row.get("id"):
                old_ids.add(str(row["id"]))
            for field in ("prompt", "completion", "code", "spec"):
                if isinstance(row.get(field), str):
                    name = fn_name(row[field])
                    if name:
                        old_names.add(name)
    samples, gate_rows, seen_names = [], [], set()
    for name, spec, code, checks in EXAMPLES:
        task_id = f"rust{EPOCH}_" + name
        if name in held_names or (CHECK_PRIOR_FUNCTION_NAMES and name in old_names) or name in seen_names or task_id in held_ids or task_id in old_ids:
            raise ValueError(f"HELDOUT_OR_PRIOR_OVERLAP:{task_id}:{name}")
        signature, description = spec.rsplit(": ", 1)
        header = signature.strip() + " {"
        if fn_name(signature) != name or fn_name(code) != name or not code.startswith(header):
            raise ValueError("FUNCTION_SIGNATURE_MISMATCH:" + task_id)
        tests = "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ " + checks + " } }"
        passed, error = gates.gate_rust(code, tests)
        gate_rows.append({"id": task_id, "function": name, "passed": bool(passed), "error": error[:1500]})
        print(json.dumps({"preflight_task": task_id, "passed": bool(passed), "error": error[:150]}, ensure_ascii=False), flush=True)
        if not passed:
            continue
        prompt = ("# Implement one self-contained, correct standard-library Rust function. Do not depend on other top-level helpers. Handle empty and boundary inputs.\n"
                  f"# Task: {description}\n{header}\n")
        samples.append({"id": task_id, "category": "rust_gate_verified_boundary_transfer_v1",
                        "prompt": prompt, "completion": code[len(header):] + EOS,
                        "source_kind": "locally_authored_reference_passed_existing_rust_gate",
                        "format_contract": "candidate_coding_runtime_v1_rust_signature_prefix",
                        "spec_sha256": hashlib.sha256(spec.encode()).hexdigest(),
                        "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                        "tests_sha256": hashlib.sha256(tests.encode()).hexdigest()})
        seen_names.add(name)
    if len(samples) != len(EXAMPLES) or not all(row["passed"] for row in gate_rows):
        rejected = {"schema": "viv_candidate_rust_boundary_preflight_v1",
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "DENY", "suite_sha256": suite_hash,
                    "parent": str(PARENT), "gate_results": gate_rows,
                    "passed_examples": len(samples), "expected_examples": len(EXAMPLES),
                    "training_started": False}
        rejected["receipt_sha256"] = digest(rejected)
        PREFLIGHT.write_text(json.dumps(rejected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError("CURRICULUM_GATE_OR_COUNT_FAILURE")
    dataset = {"schema": "viv_candidate_rust_boundary_training_v1",
               "created_utc": datetime.now(timezone.utc).isoformat(), "parent_candidate": str(PARENT),
               "heldout_suite_sha256": suite_hash, "heldout_id_overlap": [],
               "heldout_function_name_overlap": [], "prior_id_overlap": [],
               "prior_function_name_overlap": [], "gate_results": gate_rows,
               "samples": samples, "training_sha256": digest(samples)}
    dataset["receipt_sha256"] = digest(dataset)
    DATA.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    preflight = {"schema": "viv_candidate_rust_boundary_preflight_v1",
                 "created_utc": datetime.now(timezone.utc).isoformat(), "dataset": str(DATA),
                 "dataset_sha256": file_hash(DATA), "dataset_receipt_sha256": dataset["receipt_sha256"],
                 "suite_sha256": suite_hash, "parent": str(PARENT),
                 "parent_sha256": file_hash(PARENT / "adapter_model.safetensors"),
                 "unique_examples": len(samples), "heldout_id_overlap": [],
                 "heldout_function_name_overlap": [], "prior_id_overlap": [],
                 "prior_function_name_overlap": [], "gate_results": gate_rows,
                 "learning_rate": LR, "steps_requested": STEPS, "repeats": REPEATS, "seed": SEED}
    preflight["receipt_sha256"] = digest(preflight)
    PREFLIGHT.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    topology_before = file_hash(HERE / "viv_code_topology.sqlite3")
    live_before = request("/v1/status")
    if live_before.get("status") != "ACTIVE" or live_before.get("active_adapter") != LIVE.name:
        raise RuntimeError("LIVE_ADAPTER_NOT_ACTIVE:" + json.dumps(live_before))
    import torch
    from transformers import set_seed
    import viv_sleep_trainer as trainer
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    train_rows = samples * REPEATS
    run = {"schema": "viv_candidate_rust_boundary_training_run_v1",
           "created_utc": datetime.now(timezone.utc).isoformat(), "dataset": str(DATA),
           "dataset_receipt_sha256": dataset["receipt_sha256"], "preflight": str(PREFLIGHT),
           "preflight_receipt_sha256": preflight["receipt_sha256"],
           "training_sha256": digest(train_rows), "unique_examples": len(samples),
           "training_rows": len(train_rows), "steps_requested": STEPS, "learning_rate": LR,
           "seed": SEED, "parent": str(PARENT), "parent_sha256": preflight["parent_sha256"],
           "suite_sha256": suite_hash, "live_before": live_before, "candidate_only": True,
           "promoted": False, "topology_write": False, "persistent_memory_write": False}
    quiesced = False
    try:
        state = request("/v1/quiesce", {})
        if state.get("status") != "QUIESCED":
            raise RuntimeError("QUIESCE_FAILED:" + json.dumps(state))
        quiesced = True
        random.seed(SEED)
        torch.manual_seed(SEED)
        set_seed(SEED)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(SEED)
        trained = trainer.run_sleep_training(epoch=EPOCH, steps=STEPS, lr=LR,
                                             parent_adapter=PARENT, training_samples=train_rows)
        if not trained.get("ok"):
            raise RuntimeError("TRAINING_FAILED:" + json.dumps(trained))
        run["training"] = trained
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
        live_after = request("/v1/status")
        run["live_after"] = live_after
        run["live_restored"] = live_after.get("status") == "ACTIVE" and live_after.get("active_adapter") == LIVE.name
    except Exception as exc:
        run["live_restored"] = False
        run["restore_status_error"] = f"{type(exc).__name__}: {exc}"
    run["topology_sha256_before"] = topology_before
    run["topology_sha256_after"] = file_hash(HERE / "viv_code_topology.sqlite3")
    run["receipt_sha256"] = digest(run)
    RECEIPT.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"dataset": str(DATA), "preflight": str(PREFLIGHT),
                      "training_receipt": str(RECEIPT), "status": run["status"],
                      "training": run.get("training"), "live_restored": run.get("live_restored"),
                      "topology_unchanged": run["topology_sha256_before"] == run["topology_sha256_after"],
                      "promoted": False}, indent=2), flush=True)
    return 0 if run.get("status") == "TRAINED_CANDIDATE" and run.get("live_restored") else 1

if __name__ == "__main__":
    raise SystemExit(main())
