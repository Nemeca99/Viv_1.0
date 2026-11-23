"""Propose and gate fresh off-split Rust transfer examples for epoch10040."""
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

CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10038")
OUT = HERE / "learning" / "neural_runs" / "candidate_rust_transfer_learning_10039.json"

TASKS = [
    {
        "name": "unicode_uppercase_concat",
        "spec": "pub fn unicode_uppercase_concat(text: &str) -> String: return the Unicode uppercase expansion of every character in order; characters may expand to multiple characters; empty input returns an empty string",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(unicode_uppercase_concat("straße"), "STRASSE");
            assert_eq!(unicode_uppercase_concat("aΣ"), "AΣ");
            assert_eq!(unicode_uppercase_concat(""), "");
        } }''',
    },
    {
        "name": "min_max_pair",
        "spec": "pub fn min_max_pair(values: &[i32]) -> Option<(i32, i32)>: return the minimum and maximum values; return None for empty input",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(min_max_pair(&[]), None);
            assert_eq!(min_max_pair(&[7]), Some((7, 7)));
            assert_eq!(min_max_pair(&[4, -2, 9, 1]), Some((-2, 9)));
            assert_eq!(min_max_pair(&[i32::MIN, i32::MAX]), Some((i32::MIN, i32::MAX)));
        } }''',
    },
    {
        "name": "first_index_greater_than",
        "spec": "pub fn first_index_greater_than(values: &[i32], threshold: i32) -> Option<usize>: return the index of the first value strictly greater than threshold; return None if no value qualifies",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(first_index_greater_than(&[], 0), None);
            assert_eq!(first_index_greater_than(&[1, 3, 2, 5], 2), Some(1));
            assert_eq!(first_index_greater_than(&[1, 2], 2), None);
            assert_eq!(first_index_greater_than(&[-4, -2], -5), Some(0));
        } }''',
    },
    {
        "name": "checked_even_sum",
        "spec": "pub fn checked_even_sum(values: &[i64]) -> Option<i64>: sum only even values with checked addition; return None on overflow and Some(0) when there are no even values",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(checked_even_sum(&[]), Some(0));
            assert_eq!(checked_even_sum(&[1, 2, -4, 3]), Some(-2));
            assert_eq!(checked_even_sum(&[1, 3, 5]), Some(0));
            assert_eq!(checked_even_sum(&[i64::MAX - 1, 2]), None);
        } }''',
    },
    {
        "name": "clamped_window",
        "spec": "pub fn clamped_window(values: &[i32], start: usize, width: usize) -> Option<Vec<i32>>: copy the slice from start through start+width; return None if start is past the end, addition overflows, or the window exceeds the input; zero width at start==len returns Some(empty)",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(clamped_window(&[4, 5, 6, 7], 1, 2), Some(vec![5, 6]));
            assert_eq!(clamped_window(&[4, 5], 2, 0), Some(vec![]));
            assert_eq!(clamped_window(&[4, 5], 3, 0), None);
            assert_eq!(clamped_window(&[4, 5], 1, 2), None);
            assert_eq!(clamped_window(&[4], usize::MAX, 1), None);
        } }''',
    },
    {
        "name": "stable_partition_by_parity",
        "spec": "pub fn stable_partition_by_parity(values: &[i32]) -> (Vec<i32>, Vec<i32>): return (evens, odds), preserving the original order within each output vector",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(stable_partition_by_parity(&[]), (vec![], vec![]));
            assert_eq!(stable_partition_by_parity(&[3, 2, 4, 1, 6]), (vec![2, 4, 6], vec![3, 1]));
            assert_eq!(stable_partition_by_parity(&[-2, -3, 0]), (vec![-2, 0], vec![-3]));
        } }''',
    },
    {
        "name": "first_non_ascii_char",
        "spec": "pub fn first_non_ascii_char(text: &str) -> Option<char>: return the first Unicode scalar that is not ASCII; return None when all characters are ASCII or the input is empty",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(first_non_ascii_char(""), None);
            assert_eq!(first_non_ascii_char("abc"), None);
            assert_eq!(first_non_ascii_char("aé中"), Some('é'));
            assert_eq!(first_non_ascii_char("é"), Some('é'));
        } }''',
    },
    {
        "name": "zero_run_lengths",
        "spec": "pub fn zero_run_lengths(values: &[i32]) -> Vec<usize>: return the lengths of each maximal contiguous run of zero values, in input order; return an empty vector when there are no zeros",
        "tests": '''#[cfg(test)] mod t { use super::*; #[test] fn cases() {
            assert_eq!(zero_run_lengths(&[]), vec![]);
            assert_eq!(zero_run_lengths(&[1, 0, 0, 2, 0, 3, 0, 0, 0]), vec![2, 1, 3]);
            assert_eq!(zero_run_lengths(&[1, 2]), vec![]);
            assert_eq!(zero_run_lengths(&[0, 0]), vec![2]);
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
    for item in TASKS:
        task_id = "candidate_rust_transfer_10039_" + item["name"]
        task_name = ("rust", item["name"])
        if task_id in held_ids or task_name in held_names or task_name in existing:
            raise ValueError("TASK_OR_FUNCTION_COLLISION:" + item["name"])

    store_hash_before = sha(store.DB_PATH)
    topology = HERE / "viv_code_topology.sqlite3"
    memory = ROOT / "aios_rebuild" / "memory" / "persistent_memory.json"
    topology_hash_before, memory_hash_before = sha(topology), sha(memory)
    candidate_hash = sha(adapter)
    live_before = learner.model_runtime.evaluator.request("/v1/status")
    if live_before.get("status") != "ACTIVE" or live_before.get("active_adapter") != learner.LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(live_before))

    outcomes = []
    for item in TASKS:
        task = {"id": "candidate_rust_transfer_10039_" + item["name"],
                "lang": "rust", "spec": item["spec"], "tests": item["tests"]}
        result = learner.learn_one(task, domain="rust.transfer.boundary", candidate=CANDIDATE)
        outcomes.append({"task": task, "result": result})
        print(json.dumps({"task": task["id"], "state": result["state"],
                          "proposal_count": result.get("proposal_count"),
                          "code_sha256": result.get("code_sha256")}), flush=True)

    live_after = learner.model_runtime.evaluator.request("/v1/status")
    payload = {
        "schema": "viv_candidate_rust_transfer_learning_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": str(CANDIDATE), "candidate_sha256": candidate_hash,
        "frozen_suite_sha256": suite_hash,
        "source": "epoch10038 candidate-generated off-split proposals; deterministic Rust gate; only ALLOW examples trainable",
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
    payload = json.loads(json.dumps(payload, ensure_ascii=False))
    payload["receipt_sha256"] = store.canonical_hash(payload)
    authorization = PrivacyCore().authorize_file_write(str(OUT))
    if authorization.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied receipt: {authorization}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(OUT), "accepted": payload["accepted_count"],
                      "unadmitted": payload["unadmitted_count"],
                      "live_restored": payload["live_restored"], "promoted": False}, indent=2), flush=True)
    return 0 if payload["live_restored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
