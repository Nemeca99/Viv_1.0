"""Gate new disjoint Rust practice and train an isolated candidate from epoch 10016."""
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
import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
PARENT = ROOT / "epoch_10016"
DEST = ROOT / "epoch_10018"
RUNS = HERE / "learning" / "deepseek_candidate_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
DATA = RUNS / "candidate_rust_training_10018.json"
PREFLIGHT = RUNS / "candidate_rust_preflight_10018.json"
RUN_RECEIPT = RUNS / "candidate_rust_training_run_10018.json"
SEED, LEARNING_RATE, STEPS = 20261142, 5e-7, 48
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3

# Distinct, gate-checkable Rust compositions. No held-out function names are
# used; the preflight also checks every prior training receipt before training.
EXAMPLES = [
    ("sum_odd_positions", "pub fn sum_odd_positions(values: &[i32]) -> i64: sum values at odd zero-based indices",
     "pub fn sum_odd_positions(values: &[i32]) -> i64 { values.iter().enumerate().filter(|(i,_)| i % 2 == 1).map(|(_,v)| i64::from(*v)).sum() }",
     "assert_eq!(sum_odd_positions(&[2,5,7,3]),8); assert_eq!(sum_odd_positions(&[]),0); assert_eq!(sum_odd_positions(&[-4,-6]),-6);"),
    ("first_index_equal", "pub fn first_index_equal(values: &[i32], target: i32) -> Option<usize>: return the first index equal to target",
     "pub fn first_index_equal(values: &[i32], target: i32) -> Option<usize> { values.iter().position(|&value| value == target) }",
     "assert_eq!(first_index_equal(&[4,2,4],4),Some(0)); assert_eq!(first_index_equal(&[1,3],2),None); assert_eq!(first_index_equal(&[],0),None);"),
    ("sign_counts", "pub fn sign_counts(values: &[i32]) -> (usize, usize, usize): count negative, zero, and positive values in that order",
     "pub fn sign_counts(values: &[i32]) -> (usize, usize, usize) { let (mut neg,mut zero,mut pos)=(0,0,0); for &value in values { if value < 0 { neg+=1; } else if value == 0 { zero+=1; } else { pos+=1; } } (neg,zero,pos) }",
     "assert_eq!(sign_counts(&[-2,0,3,-1,0]),(2,2,1)); assert_eq!(sign_counts(&[]),(0,0,0));"),
    ("nonnegative_prefix", "pub fn nonnegative_prefix(values: &[i32]) -> Vec<i32>: copy values up to but not including the first negative value",
     "pub fn nonnegative_prefix(values: &[i32]) -> Vec<i32> { let mut out=Vec::new(); for &value in values { if value < 0 { break; } out.push(value); } out }",
     "assert_eq!(nonnegative_prefix(&[0,2,4,-1,8]),vec![0,2,4]); assert_eq!(nonnegative_prefix(&[-1,2]),vec![]); assert_eq!(nonnegative_prefix(&[3,4]),vec![3,4]);"),
    ("decimal_digit_count", "pub fn decimal_digit_count(value: i64) -> usize: count decimal digits in the absolute value; zero has one digit",
     "pub fn decimal_digit_count(value: i64) -> usize { let mut n=value.unsigned_abs(); let mut count=1; while n>=10 { n/=10; count+=1; } count }",
     "assert_eq!(decimal_digit_count(0),1); assert_eq!(decimal_digit_count(-502),3); assert_eq!(decimal_digit_count(i64::MIN),19);"),
    ("uppercase_ascii_count", "pub fn uppercase_ascii_count(text: &str) -> usize: count ASCII uppercase letters only",
     "pub fn uppercase_ascii_count(text: &str) -> usize { text.bytes().filter(|b| b.is_ascii_uppercase()).count() }",
     "assert_eq!(uppercase_ascii_count(\"Viv AI\"),3); assert_eq!(uppercase_ascii_count(\"éA\"),1); assert_eq!(uppercase_ascii_count(\"\"),0);"),
    ("chunk_sums", "pub fn chunk_sums(values: &[i32], width: usize) -> Option<Vec<i64>>: sum consecutive chunks of width; return None when width is zero",
     "pub fn chunk_sums(values: &[i32], width: usize) -> Option<Vec<i64>> { if width==0 { return None; } Some(values.chunks(width).map(|chunk| chunk.iter().map(|&x| i64::from(x)).sum()).collect()) }",
     "assert_eq!(chunk_sums(&[1,2,3,4,5],2),Some(vec![3,7,5])); assert_eq!(chunk_sums(&[],3),Some(vec![])); assert_eq!(chunk_sums(&[1],0),None);"),
    ("longest_word_bytes", "pub fn longest_word_bytes(words: &[&str]) -> Option<usize>: return the byte length of the longest word, or None for no words",
     "pub fn longest_word_bytes(words: &[&str]) -> Option<usize> { words.iter().map(|word| word.len()).max() }",
     "assert_eq!(longest_word_bytes(&[\"a\",\"tree\",\"owl\"]),Some(4)); assert_eq!(longest_word_bytes(&[]),None); assert_eq!(longest_word_bytes(&[\"\"]),Some(0));"),
    ("rising_prefix_length", "pub fn rising_prefix_length(values: &[i32]) -> usize: return the length of the longest strictly increasing prefix",
     "pub fn rising_prefix_length(values: &[i32]) -> usize { if values.is_empty() { return 0; } let mut end=1; while end<values.len() && values[end]>values[end-1] { end+=1; } end }",
     "assert_eq!(rising_prefix_length(&[1,3,5,2,9]),3); assert_eq!(rising_prefix_length(&[4,3]),1); assert_eq!(rising_prefix_length(&[]),0);"),
    ("discard_nonpositive", "pub fn discard_nonpositive(values: &[i32]) -> Vec<i32>: return only values greater than zero, preserving order",
     "pub fn discard_nonpositive(values: &[i32]) -> Vec<i32> { values.iter().copied().filter(|&value| value>0).collect() }",
     "assert_eq!(discard_nonpositive(&[-2,3,0,1]),vec![3,1]); assert_eq!(discard_nonpositive(&[]),vec![]);"),
    ("index_weighted_sum", "pub fn index_weighted_sum(values: &[i32]) -> i64: sum each value multiplied by its one-based index",
     "pub fn index_weighted_sum(values: &[i32]) -> i64 { values.iter().enumerate().map(|(i,&value)| (i as i64+1)*i64::from(value)).sum() }",
     "assert_eq!(index_weighted_sum(&[2,3,4]),20); assert_eq!(index_weighted_sum(&[-1,2]),3); assert_eq!(index_weighted_sum(&[]),0);"),
    ("binary_string", "pub fn binary_string(value: i32) -> String: return the base-two representation, with a leading minus sign for negative values",
     "pub fn binary_string(value: i32) -> String { if value < 0 { format!(\"-{:b}\",value.unsigned_abs()) } else { format!(\"{:b}\",value) } }",
     "assert_eq!(binary_string(0),\"0\"); assert_eq!(binary_string(13),\"1101\"); assert_eq!(binary_string(-5),\"-101\");"),
]


def canonical_hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rust_name(code: str) -> str:
    match = re.search(r"pub\s+fn\s+([A-Za-z_]\w*)\s*\(", code)
    if not match:
        raise ValueError("RUST_FUNCTION_NAME_MISSING")
    return match.group(1)


def rust_signature(spec: str) -> tuple[str, str]:
    match = re.search(r"pub\s+fn\s+[A-Za-z_]\w*\s*\(", spec)
    if not match:
        raise ValueError("RUST_SPEC_SIGNATURE_MISSING")
    opening = spec.find("(", match.start())
    depth = 0
    close = -1
    for index in range(opening, len(spec)):
        if spec[index] == "(":
            depth += 1
        elif spec[index] == ")":
            depth -= 1
            if depth == 0:
                close = index
                break
    colon = spec.find(":", close + 1)
    if close < 0 or colon < 0:
        raise ValueError("RUST_SPEC_RETURN_TYPE_MISSING")
    return spec[:colon].strip() + " {", spec[colon + 1:].strip()


def request(path: str, payload: dict | None = None) -> dict:
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "application/json"} if body else {})
    with urllib.request.urlopen(req, timeout=300) as response:
        return json.load(response)


def main() -> int:
    for path in (DATA, PREFLIGHT, RUN_RECEIPT):
        if path.exists():
            raise FileExistsError(path)
    if DEST.exists():
        raise FileExistsError(DEST)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if canonical_hash(suite) != suite_hash:
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    heldout = [row for row in suite["held_out"] if row["lang"] == "rust"]
    if len(heldout) != 50:
        raise ValueError("EXPECTED_50_RUST_HELDOUT_TASKS")
    held_ids = {row["id"] for row in heldout}
    held_names = {rust_name(row["spec"]) for row in heldout}
    old_ids: set[str] = set()
    old_names: set[str] = set()
    for path in RUNS.glob("*training*.json"):
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in old.get("samples", []):
            if not isinstance(row, dict):
                continue
            if row.get("id"):
                old_ids.add(str(row["id"]))
            match = re.search(r"pub\s+fn\s+([A-Za-z_]\w*)\s*\(", str(row.get("completion", "")))
            if match:
                old_names.add(match.group(1))

    samples = []
    gate_rows = []
    seen_names: set[str] = set()
    for suffix, spec, code, checks in EXAMPLES:
        task_id = "rust10018_" + suffix
        name = rust_name(spec)
        if name in held_names or name in old_names or name in seen_names or task_id in held_ids or task_id in old_ids:
            raise ValueError(f"TRAINING_HELDOUT_OR_PRIOR_OVERLAP:{task_id}:{name}")
        if rust_name(code) != name:
            raise ValueError(f"SPEC_CODE_NAME_MISMATCH:{task_id}")
        tests = "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ " + checks + " } }"
        passed, error = gates.gate_rust(code, tests)
        gate_rows.append({"id": task_id, "lang": "rust", "function": name,
                          "passed": bool(passed), "error": error[:2000]})
        print(json.dumps({"preflight_task": task_id, "passed": bool(passed),
                          "error": error[:160]}, ensure_ascii=False), flush=True)
        if not passed:
            continue
        header, description = rust_signature(spec)
        if not code.startswith(header):
            raise ValueError(f"RUST_SIGNATURE_BODY_MISMATCH:{task_id}")
        prompt = ("# Implement one self-contained, correct standard-library Rust function. "
                  "Do not depend on other top-level helpers. Handle empty and boundary inputs.\n"
                  f"# Task: {description}\n{header}\n")
        completion = code[len(header):]
        samples.append({
            "id": task_id,
            "category": "rust_gate_verified_v5",
            "prompt": prompt,
            "completion": completion + EOS,
            "source_kind": "locally_authored_reference_passed_existing_rust_gate",
            "format_contract": "candidate_coding_runtime_v1_rust_signature_prefix",
            "spec_sha256": hashlib.sha256(spec.encode()).hexdigest(),
            "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
            "tests_sha256": hashlib.sha256(tests.encode()).hexdigest(),
        })
        seen_names.add(name)
    if len(samples) != len(EXAMPLES) or not all(row["passed"] for row in gate_rows):
        raise RuntimeError("RUST_CURRICULUM_GATE_OR_COUNT_FAILURE")

    preflight = {
        "schema": "viv_candidate_rust_preflight_v5",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent": str(PARENT),
        "heldout_suite_sha256": suite_hash,
        "curriculum_file": str(Path(__file__).resolve()),
        "curriculum_sha256": file_hash(Path(__file__).resolve()),
        "unique_examples": len(samples),
        "heldout_id_overlap": [],
        "heldout_function_name_overlap": [],
        "prior_id_overlap": [],
        "prior_function_name_overlap": [],
        "gate_results": gate_rows,
        "all_gates_passed": True,
    }
    preflight["receipt_sha256"] = canonical_hash(preflight)
    PREFLIGHT.write_text(json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dataset = {
        "schema": "viv_candidate_rust_training_v5",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "parent_candidate": str(PARENT),
        "heldout_suite_sha256": suite_hash,
        "heldout_id_overlap": [],
        "heldout_function_name_overlap": [],
        "prior_id_overlap": [],
        "prior_function_name_overlap": [],
        "gate_results": gate_rows,
        "samples": samples,
        "training_sha256": canonical_hash(samples),
    }
    dataset["receipt_sha256"] = canonical_hash(dataset)
    DATA.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    before = request("/v1/status")
    if before.get("status") != "ACTIVE" or before.get("active_adapter") != LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(before))
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    training_rows = samples * 2
    run = {
        "schema": "viv_candidate_rust_training_run_v5",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(DATA),
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_sha256": canonical_hash(training_rows),
        "unique_rust_samples": len(samples),
        "training_rows": len(training_rows),
        "steps_requested": STEPS,
        "learning_rate": LEARNING_RATE,
        "seed": SEED,
        "parent": str(PARENT),
        "parent_sha256": file_hash(PARENT / "adapter_model.safetensors"),
        "heldout_suite_sha256": suite_hash,
        "live_before": before,
        "promoted": False,
        "topology_write": False,
        "persistent_memory_write": False,
    }
    quiesced = False
    error = None
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
            epoch=10018, steps=STEPS, lr=LEARNING_RATE,
            parent_adapter=PARENT, training_samples=training_rows,
        )
        if not result.get("ok"):
            raise RuntimeError("TRAINING_FAILED:" + json.dumps(result))
        run["training"] = result
        run["candidate_sha256"] = file_hash(DEST / "adapter_model.safetensors")
        run["status"] = "TRAINED_CANDIDATE"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        run["status"] = "TRAINING_FAILED"
        run["training_error"] = error
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
    RUN_RECEIPT.write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "preflight": str(PREFLIGHT),
        "dataset": str(DATA),
        "training_receipt": str(RUN_RECEIPT),
        "unique_examples": len(samples),
        "training_rows": len(training_rows),
        "status": run["status"],
        "candidate_sha256": run.get("candidate_sha256"),
        "live_restored": run.get("live_restored"),
        "active_adapter": run.get("live_after", {}).get("active_adapter"),
        "error": error,
        "promoted": False,
    }, indent=2), flush=True)
    return 0 if run["status"] == "TRAINED_CANDIDATE" and run.get("live_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
