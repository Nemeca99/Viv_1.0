"""Candidate-only Rust transfer examples gated and admitted off the frozen split."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]

import candidate_function_learning_loop as learner
import candidate_verified_function_store as store
from aios_rebuild.privacy_core.privacy_core import PrivacyCore

CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10027")
OUT = HERE / "learning" / "neural_runs" / "candidate_rust_transfer_learning_10031.json"

# These are new training contracts, not held-out task copies. Their tests teach
# boundary handling and Rust iterator/type forms implicated by the eval misses.
TASKS = [
    {"name": "checked_power_u32", "spec": "pub fn checked_power_u32(base: u32, exponent: u32) -> Option<u64>: compute base raised to exponent using checked multiplication; exponent zero returns Some(1); return None on overflow", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(checked_power_u32(2,0),Some(1)); assert_eq!(checked_power_u32(2,10),Some(1024)); assert_eq!(checked_power_u32(0,9),Some(0)); assert_eq!(checked_power_u32(u32::MAX,3),None); } }'},
    {"name": "count_ascii_uppercase", "spec": "pub fn count_ascii_uppercase(text: &str) -> usize: count ASCII uppercase letters only; non-ASCII uppercase characters do not count", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(count_ascii_uppercase("AbC"),2); assert_eq!(count_ascii_uppercase(""),0); assert_eq!(count_ascii_uppercase("éÉZ"),1); } }'},
    {"name": "first_non_repeated_byte", "spec": "pub fn first_non_repeated_byte(values: &[u8]) -> Option<u8>: return the first byte that occurs exactly once, preserving input order; return None if no byte qualifies", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(first_non_repeated_byte(&[4,2,4,3,2]),Some(3)); assert_eq!(first_non_repeated_byte(&[8,8]),None); assert_eq!(first_non_repeated_byte(&[]),None); assert_eq!(first_non_repeated_byte(&[7]),Some(7)); } }'},
    {"name": "split_sign_runs", "spec": "pub fn split_sign_runs(values: &[i32]) -> Vec<(i8, usize)>: encode consecutive runs by sign as (sign, run_length), where negative is -1, zero is 0, positive is 1; empty input returns empty", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(split_sign_runs(&[-2,-1,0,0,3,4,-1]),vec![(-1,2),(0,2),(1,2),(-1,1)]); assert_eq!(split_sign_runs(&[]),Vec::<(i8,usize)>::new()); assert_eq!(split_sign_runs(&[0,0,0]),vec![(0,3)]); } }'},
    {"name": "zip_sum_checked", "spec": "pub fn zip_sum_checked(a: &[i64], b: &[i64]) -> Option<Vec<i64>>: add corresponding elements with checked addition; return None for unequal lengths or any overflow; empty equal slices return Some(empty vector)", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(zip_sum_checked(&[1,-2],&[3,5]),Some(vec![4,3])); assert_eq!(zip_sum_checked(&[],&[]),Some(vec![])); assert_eq!(zip_sum_checked(&[1],&[]),None); assert_eq!(zip_sum_checked(&[i64::MAX],&[1]),None); } }'},
    {"name": "longest_word_character_count", "spec": "pub fn longest_word_character_count(text: &str) -> usize: return the greatest Unicode scalar-value count among whitespace-separated words; empty or whitespace-only input returns zero", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(longest_word_character_count("red blueberry"),9); assert_eq!(longest_word_character_count("  \t\n"),0); assert_eq!(longest_word_character_count("é猫 aa"),2); } }'},
    {"name": "has_ascii_prefix_case_insensitive", "spec": "pub fn has_ascii_prefix_case_insensitive(text: &str, prefix: &str) -> bool: compare the prefix using ASCII case-insensitive rules; non-ASCII bytes are compared exactly; empty prefix matches", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert!(has_ascii_prefix_case_insensitive("Rustacean","rUsT")); assert!(has_ascii_prefix_case_insensitive("éclair","é")); assert!(!has_ascii_prefix_case_insensitive("éclair","É")); assert!(has_ascii_prefix_case_insensitive("abc","")); assert!(!has_ascii_prefix_case_insensitive("ab","abc")); } }'},
    {"name": "hex_digit_value", "spec": "pub fn hex_digit_value(ch: char) -> Option<u8>: map ASCII hexadecimal digits 0-9, a-f, A-F to values 0-15; return None for every other character", "tests": '#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(hex_digit_value(\'0\'),Some(0)); assert_eq!(hex_digit_value(\'9\'),Some(9)); assert_eq!(hex_digit_value(\'a\'),Some(10)); assert_eq!(hex_digit_value(\'F\'),Some(15)); assert_eq!(hex_digit_value(\'g\'),None); assert_eq!(hex_digit_value(\'é\'),None); } }'},
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
    held_names: set[tuple[str, str]] = set()
    for row in suite["held_out"]:
        m = re.search(r"\b(?:pub\s+fn|def)\s+([A-Za-z_]\w*)\s*\(", row["spec"])
        if m:
            held_names.add((row["lang"], m.group(1)))
    existing: set[tuple[str, str]] = set()
    with __import__("sqlite3").connect(store.DB_PATH.as_uri() + "?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("CANDIDATE_STORE_QUICK_CHECK_FAILED")
        existing = {(r[0], r[1]) for r in db.execute(
            "SELECT language,function_name FROM functions")}
    for task in TASKS:
        identity = ("rust", task["name"])
        task_id = "candidate_rust_transfer_10031_" + task["name"]
        if identity in held_names or identity in existing or task_id in held_ids:
            raise ValueError("TASK_OR_NAME_OVERLAP:" + task["name"])

    store_before = sha(store.DB_PATH)
    topology = HERE / "viv_code_topology.sqlite3"
    memory = ROOT / "aios_rebuild" / "memory" / "persistent_memory.json"
    topology_before, memory_before = sha(topology), sha(memory)
    candidate_hash = sha(adapter)
    live_before = learner.model_runtime.evaluator.request("/v1/status")
    if live_before.get("status") != "ACTIVE" or live_before.get("active_adapter") != learner.LIVE.name:
        raise RuntimeError("UNEXPECTED_LIVE_ADAPTER:" + json.dumps(live_before))

    results = []
    for task_def in TASKS:
        task = {"id": "candidate_rust_transfer_10031_" + task_def["name"],
                "lang": "rust", "spec": task_def["spec"], "tests": task_def["tests"]}
        result = learner.learn_one(task, domain="rust.transfer", candidate=CANDIDATE)
        results.append({"task": task, "result": result})
        print(json.dumps({"task": task["id"], "state": result["state"],
                          "proposal_count": result.get("proposal_count"),
                          "code_sha256": result.get("code_sha256")}), flush=True)

    live_after = learner.model_runtime.evaluator.request("/v1/status")
    payload = {
        "schema": "viv_candidate_rust_transfer_learning_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "candidate": str(CANDIDATE), "candidate_sha256": candidate_hash,
        "frozen_suite_sha256": suite_hash,
        "source": "candidate model proposals; existing Rust compile/test gate; ALLOW rows only enter training store",
        "tasks": results,
        "accepted_count": sum(x["result"]["state"].startswith("ADMITTED") for x in results),
        "unadmitted_count": sum(not x["result"]["state"].startswith("ADMITTED") for x in results),
        "candidate_store_sha256_before": store_before,
        "candidate_store_sha256_after": sha(store.DB_PATH),
        "topology_sha256_before": topology_before, "topology_sha256_after": sha(topology),
        "persistent_memory_sha256_before": memory_before, "persistent_memory_sha256_after": sha(memory),
        "live_before": live_before, "live_after": live_after,
        "live_restored": live_after.get("status") == "ACTIVE" and live_after.get("active_adapter") == learner.LIVE.name,
        "promoted": False, "topology_write": False, "persistent_memory_write": False,
    }
    payload["receipt_sha256"] = store.canonical_hash(payload)
    auth = PrivacyCore().authorize_file_write(str(OUT))
    if auth.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied receipt: {auth}")
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"receipt": str(OUT), "accepted": payload["accepted_count"],
                      "unadmitted": payload["unadmitted_count"],
                      "live_restored": payload["live_restored"], "promoted": False}, indent=2), flush=True)
    return 0 if payload["live_restored"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
