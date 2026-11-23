"""Create a frozen candidate-only 10 Python + 10 Rust held-out suite."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
OUT = HERE / "learning" / "deepseek_candidate_runs" / "frozen_code_eval_v1.json"
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

PYTHON_TASKS = [
    {"id": "hold_py_clamp", "lang": "python", "spec": "def clamp(value: int, low: int, high: int) -> int: return value limited to the inclusive range low..high; assume low <= high", "tests": "assert clamp(5, 0, 10) == 5\nassert clamp(-3, 0, 10) == 0\nassert clamp(14, 0, 10) == 10\nassert clamp(4, 4, 4) == 4"},
    {"id": "hold_py_rotate_right", "lang": "python", "spec": "def rotate_right(xs: list[int], k: int) -> list[int]: rotate right by k positions, wrapping around; empty input returns empty; k may exceed length", "tests": "assert rotate_right([1, 2, 3, 4], 1) == [4, 1, 2, 3]\nassert rotate_right([1, 2, 3], 5) == [2, 3, 1]\nassert rotate_right([], 7) == []\nassert rotate_right([9], 3) == [9]"},
    {"id": "hold_py_merge_sorted", "lang": "python", "spec": "def merge_sorted(a: list[int], b: list[int]) -> list[int]: merge two ascending lists into one ascending list, preserving duplicates", "tests": "assert merge_sorted([1, 4, 8], [2, 4, 9]) == [1, 2, 4, 4, 8, 9]\nassert merge_sorted([], [1, 2]) == [1, 2]\nassert merge_sorted([3], []) == [3]\nassert merge_sorted([], []) == []"},
    {"id": "hold_py_dedupe_adjacent", "lang": "python", "spec": "def dedupe_adjacent(xs: list[int]) -> list[int]: remove only consecutive repeated values, keeping the first of each run", "tests": "assert dedupe_adjacent([1, 1, 2, 1, 1]) == [1, 2, 1]\nassert dedupe_adjacent([]) == []\nassert dedupe_adjacent([4, 4, 4]) == [4]\nassert dedupe_adjacent([1, 2, 3]) == [1, 2, 3]"},
    {"id": "hold_py_balanced_brackets", "lang": "python", "spec": "def balanced_brackets(text: str) -> bool: validate matching (), [], {} in a string; ignore all other characters", "tests": "assert balanced_brackets('a[(b)]') is True\nassert balanced_brackets('([)]') is False\nassert balanced_brackets('') is True\nassert balanced_brackets('x}') is False\nassert balanced_brackets('(((') is False"},
    {"id": "hold_py_median", "lang": "python", "spec": "def median(xs: list[int]) -> float | None: return the middle value of sorted xs, average the two middle values for even length, and return None for empty input", "tests": "assert median([9, 1, 5]) == 5\nassert median([1, 4, 7, 10]) == 5.5\nassert median([]) is None\nassert median([8]) == 8"},
    {"id": "hold_py_transpose", "lang": "python", "spec": "def transpose(matrix: list[list[int]]) -> list[list[int]]: transpose a rectangular matrix; empty matrix returns empty", "tests": "assert transpose([[1, 2, 3], [4, 5, 6]]) == [[1, 4], [2, 5], [3, 6]]\nassert transpose([[7]]) == [[7]]\nassert transpose([]) == []\nassert transpose([[], []]) == []"},
    {"id": "hold_py_longest_prefix", "lang": "python", "spec": "def longest_common_prefix(words: list[str]) -> str: return the longest prefix shared by every string; return empty string for no words", "tests": "assert longest_common_prefix(['flower', 'flow', 'flight']) == 'fl'\nassert longest_common_prefix(['dog', 'racecar', 'car']) == ''\nassert longest_common_prefix([]) == ''\nassert longest_common_prefix(['same', 'same']) == 'same'\nassert longest_common_prefix(['', 'abc']) == ''"},
    {"id": "hold_py_perfect_square", "lang": "python", "spec": "def is_perfect_square(n: int) -> bool: return whether non-negative integer n is a perfect square; do not use floating point", "tests": "assert is_perfect_square(0) is True\nassert is_perfect_square(1) is True\nassert is_perfect_square(81) is True\nassert is_perfect_square(80) is False\nassert is_perfect_square(10**12) is True"},
    {"id": "hold_py_is_sorted", "lang": "python", "spec": "def is_sorted(xs: list[int]) -> bool: return true when values are in nondecreasing order, including equal neighbors", "tests": "assert is_sorted([]) is True\nassert is_sorted([1]) is True\nassert is_sorted([1, 1, 3]) is True\nassert is_sorted([1, 3, 2]) is False"},
]

RUST_TASKS = [
    {"id": "hold_rs_clamp", "lang": "rust", "spec": "pub fn clamp(value: i32, low: i32, high: i32) -> i32: limit value to inclusive low..high; assume low <= high", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(clamp(5,0,10),5); assert_eq!(clamp(-3,0,10),0); assert_eq!(clamp(14,0,10),10); assert_eq!(clamp(4,4,4),4); } }"},
    {"id": "hold_rs_rotate_right", "lang": "rust", "spec": "pub fn rotate_right(xs: &[i32], k: usize) -> Vec<i32>: rotate right by k with wraparound; empty input returns empty", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(rotate_right(&[1,2,3,4],1),vec![4,1,2,3]); assert_eq!(rotate_right(&[1,2,3],5),vec![2,3,1]); assert_eq!(rotate_right(&[],7),Vec::<i32>::new()); assert_eq!(rotate_right(&[9],3),vec![9]); } }"},
    {"id": "hold_rs_merge_sorted", "lang": "rust", "spec": "pub fn merge_sorted(a: &[i32], b: &[i32]) -> Vec<i32>: merge ascending slices into ascending Vec, preserving duplicates", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(merge_sorted(&[1,4,8],&[2,4,9]),vec![1,2,4,4,8,9]); assert_eq!(merge_sorted(&[],&[1,2]),vec![1,2]); assert_eq!(merge_sorted(&[3],&[]),vec![3]); assert_eq!(merge_sorted(&[],&[]),Vec::<i32>::new()); } }"},
    {"id": "hold_rs_dedupe_adjacent", "lang": "rust", "spec": "pub fn dedupe_adjacent(xs: &[i32]) -> Vec<i32>: remove only consecutive equal values, keeping one from each run", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(dedupe_adjacent(&[1,1,2,1,1]),vec![1,2,1]); assert_eq!(dedupe_adjacent(&[]),Vec::<i32>::new()); assert_eq!(dedupe_adjacent(&[4,4,4]),vec![4]); assert_eq!(dedupe_adjacent(&[1,2,3]),vec![1,2,3]); } }"},
    {"id": "hold_rs_balanced_brackets", "lang": "rust", "spec": "pub fn balanced_brackets(text: &str) -> bool: validate (), [], {} and ignore all other characters", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert!(balanced_brackets(\"a[(b)]\")); assert!(!balanced_brackets(\"([)]\")); assert!(balanced_brackets(\"\")); assert!(!balanced_brackets(\"x}\")); assert!(!balanced_brackets(\"(((\")); } }"},
    {"id": "hold_rs_median", "lang": "rust", "spec": "pub fn median(xs: &[i32]) -> Option<f64>: sorted middle, average the two middle values for even length, None for empty", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(median(&[9,1,5]),Some(5.0)); assert_eq!(median(&[1,4,7,10]),Some(5.5)); assert_eq!(median(&[]),None); assert_eq!(median(&[8]),Some(8.0)); } }"},
    {"id": "hold_rs_transpose", "lang": "rust", "spec": "pub fn transpose(matrix: &[Vec<i32>]) -> Vec<Vec<i32>>: transpose rectangular input; empty matrix returns empty", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(transpose(&vec![vec![1,2,3],vec![4,5,6]]),vec![vec![1,4],vec![2,5],vec![3,6]]); assert_eq!(transpose(&vec![vec![7]]),vec![vec![7]]); assert_eq!(transpose(&[]),Vec::<Vec<i32>>::new()); assert_eq!(transpose(&vec![vec![],vec![]]),Vec::<Vec<i32>>::new()); } }"},
    {"id": "hold_rs_longest_prefix", "lang": "rust", "spec": "pub fn longest_common_prefix(words: &[&str]) -> String: longest shared prefix, empty for no words", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert_eq!(longest_common_prefix(&[\"flower\",\"flow\",\"flight\"]),\"fl\"); assert_eq!(longest_common_prefix(&[\"dog\",\"racecar\",\"car\"]),\"\"); assert_eq!(longest_common_prefix(&[]),\"\"); assert_eq!(longest_common_prefix(&[\"same\",\"same\"]),\"same\"); assert_eq!(longest_common_prefix(&[\"\",\"abc\"]),\"\"); } }"},
    {"id": "hold_rs_perfect_square", "lang": "rust", "spec": "pub fn is_perfect_square(n: u64) -> bool: whether n is a perfect square; use integer arithmetic only", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert!(is_perfect_square(0)); assert!(is_perfect_square(1)); assert!(is_perfect_square(81)); assert!(!is_perfect_square(80)); assert!(is_perfect_square(1_000_000_000_000)); } }"},
    {"id": "hold_rs_is_sorted", "lang": "rust", "spec": "pub fn is_sorted(xs: &[i32]) -> bool: true when values are nondecreasing, including equal neighbors", "tests": "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ assert!(is_sorted(&[])); assert!(is_sorted(&[1])); assert!(is_sorted(&[1,1,3])); assert!(!is_sorted(&[1,3,2])); } }"},
]


def main() -> int:
    if OUT.exists():
        raise FileExistsError(f"frozen evaluation set already exists: {OUT}")
    spec = importlib.util.spec_from_file_location("candidate_training_source", HERE / "run_deepseek_candidate_e2e.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    _, lineage = module.accepted_training_samples()
    training_ids = sorted({str(row["task"]) for row in lineage})
    test_ids = {row["id"] for row in PYTHON_TASKS + RUST_TASKS}
    overlap = sorted(test_ids.intersection(training_ids))
    if overlap or len(PYTHON_TASKS) != 10 or len(RUST_TASKS) != 10:
        raise AssertionError({"training_overlap": overlap, "python": len(PYTHON_TASKS), "rust": len(RUST_TASKS)})
    payload = {
        "schema": "viv_frozen_candidate_code_eval_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "split_policy": "task identifiers absent from receipt-verified training sample lineage; frozen before scoring",
        "training_task_ids": training_ids,
        "held_out": PYTHON_TASKS + RUST_TASKS,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    payload["suite_sha256"] = hashlib.sha256(canonical).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"suite": str(OUT), "suite_sha256": payload["suite_sha256"],
                      "python_tasks": len(PYTHON_TASKS), "rust_tasks": len(RUST_TASKS),
                      "training_task_count": len(training_ids), "overlap": overlap}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
