"""Admit a diverse Rust standard-library curriculum into the isolated store.

Every task is generated against epoch 10027, gated by the existing Rust body
gate, and recorded in an immutable receipt. Only ALLOW results become eligible
training rows; the frozen suite is consulted only for ID/name disjointness.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

import candidate_function_learning_loop as learner
import candidate_verified_function_store as store
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10027")
OUT = HERE / "learning" / "neural_runs" / "candidate_rust_transfer_learning_10036.json"

TASKS = [
    {
        "name": "first_ascii_digit_value",
        "spec": "pub fn first_ascii_digit_value(text: &str) -> Option<u8>: return the numeric value of the first ASCII digit in the text; return None if there is no ASCII digit",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(first_ascii_digit_value("room 7B"), Some(7));
            assert_eq!(first_ascii_digit_value("abc"), None);
            assert_eq!(first_ascii_digit_value("٣ 4"), Some(4));
            assert_eq!(first_ascii_digit_value(""), None);
        } }''',
    },
    {
        "name": "count_ascii_vowels",
        "spec": "pub fn count_ascii_vowels(text: &str) -> usize: count ASCII vowels a, e, i, o, u case-insensitively; ignore non-ASCII characters",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(count_ascii_vowels("Viv and VIV"), 3);
            assert_eq!(count_ascii_vowels("rhythm"), 0);
            assert_eq!(count_ascii_vowels("Élan"), 1);
            assert_eq!(count_ascii_vowels(""), 0);
        } }''',
    },
    {
        "name": "insert_sorted_i32",
        "spec": "pub fn insert_sorted_i32(values: &[i32], value: i32) -> Vec<i32>: insert value into an ascending slice and return a new ascending vector; place it after existing equal values and do not mutate the input",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(insert_sorted_i32(&[1, 3, 3, 8], 3), vec![1, 3, 3, 3, 8]);
            assert_eq!(insert_sorted_i32(&[], 4), vec![4]);
            assert_eq!(insert_sorted_i32(&[2, 5], 1), vec![1, 2, 5]);
            assert_eq!(insert_sorted_i32(&[2, 5], 9), vec![2, 5, 9]);
        } }''',
    },
    {
        "name": "mean_i32_checked_count",
        "spec": "pub fn mean_i32_checked_count(values: &[i32]) -> Option<f64>: return the arithmetic mean as f64, or None for empty input; accumulate in i64",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(mean_i32_checked_count(&[]), None);
            assert_eq!(mean_i32_checked_count(&[5]), Some(5.0));
            assert_eq!(mean_i32_checked_count(&[1, 2, 6]), Some(3.0));
            assert_eq!(mean_i32_checked_count(&[-2, 1]), Some(-0.5));
        } }''',
    },
    {
        "name": "count_even_sum_windows",
        "spec": "pub fn count_even_sum_windows(values: &[i32], width: usize) -> usize: count contiguous windows of exactly width whose i64 sum is even; width zero or width larger than the input returns zero",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(count_even_sum_windows(&[1, 1, 2, 2], 2), 2);
            assert_eq!(count_even_sum_windows(&[2, 4, 6], 1), 3);
            assert_eq!(count_even_sum_windows(&[1, 2], 3), 0);
            assert_eq!(count_even_sum_windows(&[1, 2], 0), 0);
            assert_eq!(count_even_sum_windows(&[], 1), 0);
        } }''',
    },
    {
        "name": "sum_indexed_i64_checked",
        "spec": "pub fn sum_indexed_i64_checked(values: &[i64], indexes: &[usize]) -> Option<i64>: sum values at the requested indexes, returning None if any index is out of bounds or the sum overflows; an empty index list returns Some(0)",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(sum_indexed_i64_checked(&[4, 8, 12], &[0, 2]), Some(16));
            assert_eq!(sum_indexed_i64_checked(&[4, 8], &[]), Some(0));
            assert_eq!(sum_indexed_i64_checked(&[4], &[1]), None);
            assert_eq!(sum_indexed_i64_checked(&[i64::MAX, 1], &[0, 1]), None);
        } }''',
    },
    {
        "name": "common_first_character",
        "spec": "pub fn common_first_character(words: &[&str]) -> Option<char>: return the first Unicode scalar shared as the first character of every word; return None for empty input or if any word is empty or starts differently",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(common_first_character(&["rust", "route", "row"]), Some('r'));
            assert_eq!(common_first_character(&["éclair", "école"]), Some('é'));
            assert_eq!(common_first_character(&["", "abc"]), None);
            assert_eq!(common_first_character(&[]), None);
            assert_eq!(common_first_character(&["a", "b"]), None);
        } }''',
    },
    {
        "name": "duration_hours_minutes_seconds",
        "spec": "pub fn duration_hours_minutes_seconds(total: u64) -> (u64, u64, u64): split seconds into whole hours, remaining minutes, and remaining seconds",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(duration_hours_minutes_seconds(0), (0, 0, 0));
            assert_eq!(duration_hours_minutes_seconds(59), (0, 0, 59));
            assert_eq!(duration_hours_minutes_seconds(3600), (1, 0, 0));
            assert_eq!(duration_hours_minutes_seconds(7384), (2, 3, 4));
            assert_eq!(duration_hours_minutes_seconds(u64::MAX).2 < 60, true);
        } }''',
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"Refusing overwrite: {OUT}")
    adapter = CANDIDATE / "adapter_model.safetensors"
    if not adapter.is_file():
        raise FileNotFoundError(adapter)

    suite = json.loads(store.SUITE_PATH.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256", None)
    if suite_hash != store.canonical_hash(suite):
        raise ValueError("FROZEN_SUITE_HASH_MISMATCH")
    held_ids = {str(row["id"]) for row in suite["held_out"]}
    held_names = set()
    for row in suite["held_out"]:
        match = re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(", row["spec"])
        if match:
            held_names.add((row["lang"], match.group(1)))

    with sqlite3.connect(store.DB_PATH.as_uri() + "?mode=ro", uri=True) as db:
        existing = {(row[0], row[1]) for row in db.execute(
            "SELECT language,function_name FROM functions")}
    for task in TASKS:
        task_id = "candidate_rust_transfer_10036_" + task["name"]
        task_name = ("rust", task["name"])
        if task_id in held_ids or task_name in held_names or task_name in existing:
            raise ValueError("TASK_OR_FUNCTION_COLLISION:" + task["name"])

    store_hash_before = sha(store.DB_PATH)
    topology = HERE / "viv_code_topology.sqlite3"
    memory = ROOT / "aios_rebuild" / "memory" / "persistent_memory.json"
    topology_hash_before, memory_hash_before = sha(topology), sha(memory)
    candidate_hash = sha(adapter)
    live_before = learner.model_runtime.evaluator.request("/v1/status")
    if live_before.get("status") != "ACTIVE" or live_before.get("active_adapter") != learner.LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(live_before))

    outcomes = []
    for task_spec in TASKS:
        task = {
            "id": "candidate_rust_transfer_10036_" + task_spec["name"],
            "lang": "rust", "spec": task_spec["spec"], "tests": task_spec["tests"],
        }
        result = learner.learn_one(task, domain="rust.transfer", candidate=CANDIDATE)
        outcomes.append({"task": task, "result": result})
        print(json.dumps({
            "task": task["id"], "state": result["state"],
            "proposal_count": result.get("proposal_count"),
            "code_sha256": result.get("code_sha256"),
        }), flush=True)

    live_after = learner.model_runtime.evaluator.request("/v1/status")
    payload = {
        "schema": "viv_candidate_rust_transfer_learning_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": str(CANDIDATE), "candidate_sha256": candidate_hash,
        "frozen_suite_sha256": suite_hash,
        "source": "epoch10027 candidate-generated proposals; deterministic Rust gate; only ALLOW examples trainable",
        "tasks": outcomes,
        "accepted_count": sum(x["result"]["state"].startswith("ADMITTED") for x in outcomes),
        "unadmitted_count": sum(not x["result"]["state"].startswith("ADMITTED") for x in outcomes),
        "candidate_store_sha256_before": store_hash_before,
        "candidate_store_sha256_after": sha(store.DB_PATH),
        "topology_sha256_before": topology_hash_before,
        "topology_sha256_after": sha(topology),
        "persistent_memory_sha256_before": memory_hash_before,
        "persistent_memory_sha256_after": sha(memory),
        "live_before": live_before, "live_after": live_after,
        "live_restored": live_after.get("status") == "ACTIVE" and live_after.get("active_adapter") == learner.LIVE.name,
        "promoted": False, "topology_write": False, "persistent_memory_write": False,
    }
    # Hash the same JSON values that will be serialized (not any in-memory
    # tuples), so verification after a JSON round-trip is exact.
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    payload["receipt_sha256"] = store.canonical_hash(payload)
    authorization = PrivacyCore().authorize_file_write(str(OUT))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied receipt: {authorization}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "receipt": str(OUT), "accepted": payload["accepted_count"],
        "unadmitted": payload["unadmitted_count"],
        "live_restored": payload["live_restored"], "promoted": False,
    }, indent=2), flush=True)
    return 0 if payload["live_restored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
