"""Build a new candidate-only coding corpus from references that pass existing gates."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates

RUNS = HERE / "learning" / "deepseek_candidate_runs"
SUITE = RUNS / "frozen_code_eval_v2_1.json"
PRIOR = RUNS / "clean_function_training_v2.json"
OUT = RUNS / "candidate_coding_training_v3.json"
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3

PY = [
 ("py_sum_squares", "def sum_squares(values: list[int]) -> int: sum the square of each integer", "def sum_squares(values):\n    return sum(value * value for value in values)", "assert sum_squares([1,-2,3])==14\nassert sum_squares([])==0"),
 ("py_integer_power", "def integer_power(base: int, exponent: int) -> int: integer exponentiation; exponent must be nonnegative", "def integer_power(base, exponent):\n    if exponent < 0: raise ValueError('negative exponent')\n    result = 1\n    for _ in range(exponent): result *= base\n    return result", "assert integer_power(3,4)==81\nassert integer_power(5,0)==1\ntry:\n integer_power(2,-1)\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_digit_sum_abs", "def digit_sum_abs(value: int) -> int: sum decimal digits of absolute value", "def digit_sum_abs(value):\n    return sum(int(char) for char in str(abs(value)))", "assert digit_sum_abs(-502)==7\nassert digit_sum_abs(0)==0"),
 ("py_is_odd", "def is_odd(value: int) -> bool: whether integer is odd", "def is_odd(value):\n    return value % 2 != 0", "assert is_odd(-3)\nassert not is_odd(0)\nassert is_odd(7)"),
 ("py_vector_scale", "def vector_scale(values: list[float], factor: float) -> list[float]: multiply each vector element by factor", "def vector_scale(values, factor):\n    return [value * factor for value in values]", "assert vector_scale([1.5,-2.0],2)==[3.0,-4.0]\nassert vector_scale([],4)==[]"),
 ("py_matrix_add", "def matrix_add(a: list[list[int]], b: list[list[int]]) -> list[list[int]]: elementwise sum of equal-shaped matrices; otherwise raise ValueError", "def matrix_add(a, b):\n    if len(a) != len(b) or any(len(x) != len(y) for x,y in zip(a,b)): raise ValueError('shape mismatch')\n    return [[x+y for x,y in zip(row_a,row_b)] for row_a,row_b in zip(a,b)]", "assert matrix_add([[1,2],[3,4]],[[5,6],[7,8]])==[[6,8],[10,12]]\nassert matrix_add([],[])==[]\ntry:\n matrix_add([[1]],[[1,2]])\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_mean_or_none", "def mean_or_none(values: list[float]) -> float | None: arithmetic mean, or None for empty input", "def mean_or_none(values):\n    return sum(values) / len(values) if values else None", "assert mean_or_none([2.0,4.0])==3.0\nassert mean_or_none([]) is None"),
 ("py_minmax_or_none", "def minmax_or_none(values: list[int]) -> tuple[int, int] | None: minimum and maximum, or None when empty", "def minmax_or_none(values):\n    return (min(values), max(values)) if values else None", "assert minmax_or_none([4,-2,7])==(-2,7)\nassert minmax_or_none([]) is None"),
 ("py_insert_sorted", "def insert_sorted(values: list[int], value: int) -> list[int]: insert into ascending list after existing equal values", "def insert_sorted(values, value):\n    out = list(values)\n    i = 0\n    while i < len(out) and out[i] <= value: i += 1\n    out.insert(i, value)\n    return out", "assert insert_sorted([1,2,2,4],2)==[1,2,2,2,4]\nassert insert_sorted([],3)==[3]"),
 ("py_remove_at", "def remove_at(values: list[int], index: int) -> list[int] | None: return a copy without index; None when index invalid", "def remove_at(values, index):\n    if index < 0 or index >= len(values): return None\n    return values[:index] + values[index+1:]", "assert remove_at([1,2,3],1)==[1,3]\nassert remove_at([1],-1) is None\nassert remove_at([],0) is None"),
 ("py_seconds_to_hms", "def seconds_to_hms(seconds: int) -> tuple[int, int, int]: convert nonnegative seconds to hours, minutes, seconds", "def seconds_to_hms(seconds):\n    if seconds < 0: raise ValueError('negative')\n    hours, rest = divmod(seconds, 3600)\n    minutes, secs = divmod(rest, 60)\n    return hours, minutes, secs", "assert seconds_to_hms(3661)==(1,1,1)\nassert seconds_to_hms(59)==(0,0,59)\nassert seconds_to_hms(0)==(0,0,0)"),
 ("py_count_prefix", "def count_prefix(words: list[str], prefix: str) -> int: count case-sensitive words beginning with prefix", "def count_prefix(words, prefix):\n    return sum(word.startswith(prefix) for word in words)", "assert count_prefix(['preheat','prefix','heat'],'pre')==2\nassert count_prefix([], 'x')==0"),
 ("py_safe_divide", "def safe_divide(numerator: float, denominator: float) -> float | None: quotient, or None for zero denominator", "def safe_divide(numerator, denominator):\n    return None if denominator == 0 else numerator / denominator", "assert safe_divide(9,3)==3.0\nassert safe_divide(1,0) is None"),
 ("py_contains_all", "def contains_all(container: list[int], required: list[int]) -> bool: true when each required value appears in container", "def contains_all(container, required):\n    available = set(container)\n    return all(value in available for value in required)", "assert contains_all([1,2,3],[3,1])\nassert not contains_all([1],[1,2])\nassert contains_all([],[])"),
 ("py_format_hex", "def format_hex(value: int) -> str: lowercase hexadecimal without prefix; negative values use a leading minus", "def format_hex(value):\n    return ('-' if value < 0 else '') + format(abs(value), 'x')", "assert format_hex(255)=='ff'\nassert format_hex(0)=='0'\nassert format_hex(-16)=='-10'"),
 ("py_all_ascii_lowercase", "def all_ascii_lowercase(text: str) -> bool: true for nonempty strings containing only lowercase ASCII letters", "def all_ascii_lowercase(text):\n    return bool(text) and all('a' <= char <= 'z' for char in text)", "assert all_ascii_lowercase('abc')\nassert not all_ascii_lowercase('')\nassert not all_ascii_lowercase('aZ')\nassert not all_ascii_lowercase(chr(233))"),
]

RS = [
 ("rs_sum_squares", "pub fn sum_squares(values: &[i32]) -> i64: sum the square of each integer", "pub fn sum_squares(values: &[i32]) -> i64 { values.iter().map(|&x| (x as i64)*(x as i64)).sum() }", "assert_eq!(sum_squares(&[1,-2,3]),14); assert_eq!(sum_squares(&[]),0);"),
 ("rs_integer_power", "pub fn integer_power(base: i64, exponent: u32) -> i64: integer exponentiation", "pub fn integer_power(base: i64, exponent: u32) -> i64 { (0..exponent).fold(1, |acc, _| acc * base) }", "assert_eq!(integer_power(3,4),81); assert_eq!(integer_power(5,0),1);"),
 ("rs_digit_sum_abs", "pub fn digit_sum_abs(value: i64) -> u32: sum decimal digits of absolute value", "pub fn digit_sum_abs(value: i64) -> u32 { value.unsigned_abs().to_string().bytes().map(|b| (b-b'0') as u32).sum() }", "assert_eq!(digit_sum_abs(-502),7); assert_eq!(digit_sum_abs(0),0);"),
 ("rs_is_odd", "pub fn is_odd(value: i64) -> bool: whether integer is odd", "pub fn is_odd(value: i64) -> bool { value % 2 != 0 }", "assert!(is_odd(-3)); assert!(!is_odd(0)); assert!(is_odd(7));"),
 ("rs_vector_scale", "pub fn vector_scale(values: &[f64], factor: f64) -> Vec<f64>: multiply each vector element by factor", "pub fn vector_scale(values: &[f64], factor: f64) -> Vec<f64> { values.iter().map(|x| x*factor).collect() }", "assert_eq!(vector_scale(&[1.5,-2.0],2.0),vec![3.0,-4.0]); assert_eq!(vector_scale(&[],4.0),Vec::<f64>::new());"),
 ("rs_matrix_add", "pub fn matrix_add(a: &[Vec<i32>], b: &[Vec<i32>]) -> Option<Vec<Vec<i32>>>: elementwise sum for equal-shaped matrices", "pub fn matrix_add(a: &[Vec<i32>], b: &[Vec<i32>]) -> Option<Vec<Vec<i32>>> { if a.len()!=b.len() || a.iter().zip(b).any(|(x,y)| x.len()!=y.len()) { return None; } Some(a.iter().zip(b).map(|(x,y)| x.iter().zip(y).map(|(p,q)| p+q).collect()).collect()) }", "assert_eq!(matrix_add(&[vec![1,2],vec![3,4]],&[vec![5,6],vec![7,8]]),Some(vec![vec![6,8],vec![10,12]])); assert_eq!(matrix_add(&[],&[]),Some(vec![])); assert_eq!(matrix_add(&[vec![1]],&[vec![1,2]]),None);"),
 ("rs_mean_or_none", "pub fn mean_or_none(values: &[f64]) -> Option<f64>: arithmetic mean or None for empty input", "pub fn mean_or_none(values: &[f64]) -> Option<f64> { if values.is_empty() { None } else { Some(values.iter().sum::<f64>() / values.len() as f64) } }", "assert_eq!(mean_or_none(&[2.0,4.0]),Some(3.0)); assert_eq!(mean_or_none(&[]),None);"),
 ("rs_minmax_or_none", "pub fn minmax_or_none(values: &[i32]) -> Option<(i32,i32)>: minimum and maximum or None when empty", "pub fn minmax_or_none(values: &[i32]) -> Option<(i32,i32)> { Some((*values.iter().min()?,*values.iter().max()?)) }", "assert_eq!(minmax_or_none(&[4,-2,7]),Some((-2,7))); assert_eq!(minmax_or_none(&[]),None);"),
 ("rs_insert_sorted", "pub fn insert_sorted(values: &[i32], value: i32) -> Vec<i32>: insert after existing equal values into ascending values", "pub fn insert_sorted(values: &[i32], value: i32) -> Vec<i32> { let mut out=values.to_vec(); let i=out.partition_point(|&x| x<=value); out.insert(i,value); out }", "assert_eq!(insert_sorted(&[1,2,2,4],2),vec![1,2,2,2,4]); assert_eq!(insert_sorted(&[],3),vec![3]);"),
 ("rs_remove_at", "pub fn remove_at(values: &[i32], index: usize) -> Option<Vec<i32>>: copy without index or None if out of bounds", "pub fn remove_at(values: &[i32], index: usize) -> Option<Vec<i32>> { if index>=values.len() { return None; } let mut out=values.to_vec(); out.remove(index); Some(out) }", "assert_eq!(remove_at(&[1,2,3],1),Some(vec![1,3])); assert_eq!(remove_at(&[1],3),None); assert_eq!(remove_at(&[],0),None);"),
 ("rs_seconds_to_hms", "pub fn seconds_to_hms(seconds: u64) -> (u64,u64,u64): convert to hours, minutes, seconds", "pub fn seconds_to_hms(seconds: u64) -> (u64,u64,u64) { (seconds/3600,(seconds%3600)/60,seconds%60) }", "assert_eq!(seconds_to_hms(3661),(1,1,1)); assert_eq!(seconds_to_hms(59),(0,0,59)); assert_eq!(seconds_to_hms(0),(0,0,0));"),
 ("rs_count_prefix", "pub fn count_prefix(words: &[&str], prefix: &str) -> usize: count case-sensitive words beginning with prefix", "pub fn count_prefix(words: &[&str], prefix: &str) -> usize { words.iter().filter(|word| word.starts_with(prefix)).count() }", "assert_eq!(count_prefix(&[\"preheat\",\"prefix\",\"heat\"],\"pre\"),2); assert_eq!(count_prefix(&[],\"x\"),0);"),
 ("rs_safe_divide", "pub fn safe_divide(numerator: f64, denominator: f64) -> Option<f64>: quotient or None for zero denominator", "pub fn safe_divide(numerator: f64, denominator: f64) -> Option<f64> { if denominator==0.0 { None } else { Some(numerator/denominator) } }", "assert_eq!(safe_divide(9.0,3.0),Some(3.0)); assert_eq!(safe_divide(1.0,0.0),None);"),
 ("rs_contains_all", "pub fn contains_all(container: &[i32], required: &[i32]) -> bool: whether each required value appears in container", "pub fn contains_all(container: &[i32], required: &[i32]) -> bool { required.iter().all(|x| container.contains(x)) }", "assert!(contains_all(&[1,2,3],&[3,1])); assert!(!contains_all(&[1],&[1,2])); assert!(contains_all(&[],&[]));"),
 ("rs_format_hex", "pub fn format_hex(value: i64) -> String: lowercase hexadecimal without prefix; negative values have leading minus", "pub fn format_hex(value: i64) -> String { if value<0 { format!(\"-{:x}\",value.unsigned_abs()) } else { format!(\"{:x}\",value) } }", "assert_eq!(format_hex(255),\"ff\"); assert_eq!(format_hex(0),\"0\"); assert_eq!(format_hex(-16),\"-10\");"),
 ("rs_all_ascii_lowercase", "pub fn all_ascii_lowercase(text: &str) -> bool: nonempty and contains only lowercase ASCII letters", "pub fn all_ascii_lowercase(text: &str) -> bool { !text.is_empty() && text.bytes().all(|b| b'a'<=b && b<=b'z') }", "assert!(all_ascii_lowercase(\"abc\")); assert!(!all_ascii_lowercase(\"\")); assert!(!all_ascii_lowercase(\"aZ\")); assert!(!all_ascii_lowercase(\"é\"));"),
]

def obj_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()

def code_name(code: str, lang: str) -> str:
    pattern = r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\("
    match = re.search(pattern, code)
    if not match:
        raise ValueError("reference function name missing")
    return match.group(1)

def main() -> int:
    if OUT.exists():
        raise FileExistsError(OUT)
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    suite_hash = suite.pop("suite_sha256")
    if obj_hash(suite) != suite_hash:
        raise ValueError("evaluation suite hash mismatch")
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    prior_hash = prior.pop("receipt_sha256")
    if obj_hash(prior) != prior_hash or obj_hash(prior["samples"]) != prior["training_sha256"]:
        raise ValueError("prior training receipt/hash invalid")
    held_names = {lang: set() for lang in ("python", "rust")}
    for task in suite["held_out"]:
        held_names[task["lang"]].add(code_name(task["spec"], task["lang"]))
    prior_names = {lang: set() for lang in ("python", "rust")}
    prior_ids = set()
    for row in prior["samples"]:
        lang = "rust" if row["category"].startswith("rust_") else "python"
        prior_names[lang].add(code_name(row["completion"], lang))
        prior_ids.add(row["id"])
    rows, gates_seen, failures = [], [], []
    for lang, examples in (("python", PY), ("rust", RS)):
        if len(examples) != 16:
            raise ValueError(f"expected 16 {lang} examples, got {len(examples)}")
        for task_id, spec, code, checks in examples:
            name = code_name(spec, lang)
            if name in held_names[lang] or name in prior_names[lang] or task_id in prior_ids:
                raise ValueError(f"training leakage/duplicate: {task_id}/{name}")
            tests = checks
            if lang == "rust":
                tests = "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ " + checks + " } }"
            gate = gates.gate_python if lang == "python" else gates.gate_rust
            passed, error = gate(code, tests)
            gates_seen.append({"id": task_id, "lang": lang, "passed": bool(passed), "error": error[:2000]})
            if not passed:
                failures.append(task_id)
                continue
            system = f"You write correct standard-library {lang} functions. Return only one fenced code block, no tests or explanation."
            prompt = f"SYSTEM: {system}\n\nUSER: Implement: {spec}\n\nASSISTANT:"
            rows.append({"id": task_id, "category": f"{lang}_gate_verified_v3",
                         "prompt": prompt,
                         "completion": f"{FENCE}{lang}\n{code}\n{FENCE}{EOS}",
                         "source_kind": "locally_authored_reference_passed_existing_gate",
                         "spec_sha256": hashlib.sha256(spec.encode()).hexdigest(),
                         "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                         "tests_sha256": hashlib.sha256(tests.encode()).hexdigest(),
                         "gate": lang})
    py = [row for row in rows if row["category"].startswith("python_")]
    rs = [row for row in rows if row["category"].startswith("rust_")]
    if failures or len(py) != 16 or len(rs) != 16:
        raise ValueError(f"training examples failed gates: {failures}; counts={len(py)}/{len(rs)}")
    data = {"schema": "viv_candidate_coding_training_v3", "created_utc": datetime.now(timezone.utc).isoformat(),
            "base_dataset_sha256": prior_hash, "heldout_suite_sha256": suite_hash,
            "heldout_task_count": len(suite["held_out"]), "heldout_id_overlap": [],
            "heldout_function_name_overlap": [], "python_unique": len(py), "rust_unique": len(rs),
            "gate_results": gates_seen, "samples": py + rs,
            "training_sha256": obj_hash(py + rs), "parent_candidate": r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10008"}
    data["receipt_sha256"] = obj_hash(data)
    with OUT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(OUT), "receipt_sha256": data["receipt_sha256"],
                      "training_sha256": data["training_sha256"], "python": len(py), "rust": len(rs),
                      "heldout_suite_sha256": suite_hash, "gate_failures": failures}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
