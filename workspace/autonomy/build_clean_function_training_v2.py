"""Build a hash-receipted, gate-verified function-only candidate corpus."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
sys.path[:0] = [str(WORKSPACE), str(HERE)]
import evaluate_frozen_candidate_code_v1 as evaluator
import viv_code_learning_loop as gates

RUNS = HERE / "learning" / "deepseek_candidate_runs"
SOURCE = RUNS / "verified_multidomain_training_v1.json"
OUT = RUNS / "clean_function_training_v2.json"
EOS = "<｜end▁of▁sentence｜>"
FENCE = chr(96) * 3

EXTRA = [
("py_hamming_distance","python","def hamming_distance(a: int, b: int) -> int: count different bit positions", "def hamming_distance(a: int, b: int) -> int:\n    return (a ^ b).bit_count()", "assert hamming_distance(0,0)==0\nassert hamming_distance(5,3)==2\nassert hamming_distance(15,0)==4"),
("py_is_pangram","python","def is_pangram(text: str) -> bool: test for all English letters, ignoring case and nonletters", "def is_pangram(text: str) -> bool:\n    return set(c.lower() for c in text if c.isalpha()) >= set('abcdefghijklmnopqrstuvwxyz')", "assert is_pangram('The quick brown fox jumps over the lazy dog')\nassert not is_pangram('The quick brown fox')\nassert is_pangram('ABCDEFGHIJKLMNOPQRSTUVWXYZ')"),
("py_group_by_parity","python","def group_by_parity(values: list[int]) -> tuple[list[int], list[int]]: return even and odd values in separate lists, preserving order", "def group_by_parity(values: list[int]) -> tuple[list[int], list[int]]:\n    return ([x for x in values if x % 2 == 0], [x for x in values if x % 2 != 0])", "assert group_by_parity([3,2,4,1,6])==([2,4,6],[3,1])\nassert group_by_parity([])==([],[])\nassert group_by_parity([-2,-1,0])==([-2,0],[-1])"),
("py_count_occurrences","python","def count_occurrences(values: list[int], target: int) -> int: count target values", "def count_occurrences(values: list[int], target: int) -> int:\n    return sum(value == target for value in values)", "assert count_occurrences([1,2,2,3,2],2)==3\nassert count_occurrences([],1)==0\nassert count_occurrences([4,5],1)==0"),
("py_is_power_of_two","python","def is_power_of_two(value: int) -> bool: true only for positive powers of two", "def is_power_of_two(value: int) -> bool:\n    return value > 0 and (value & (value - 1)) == 0", "assert is_power_of_two(1)\nassert is_power_of_two(1024)\nassert not is_power_of_two(0)\nassert not is_power_of_two(12)"),
("py_find_peak","python","def find_peak_index(values: list[int]) -> int: return any index whose value is at least both neighbors; nonempty input", "def find_peak_index(values: list[int]) -> int:\n    for i, value in enumerate(values):\n        if (i == 0 or value >= values[i - 1]) and (i + 1 == len(values) or value >= values[i + 1]):\n            return i\n    raise ValueError('no peak')", "assert find_peak_index([1,3,2])==1\nassert find_peak_index([3,2,1])==0\nassert find_peak_index([1,2,3])==2\nassert find_peak_index([2,2])==0"),
("py_first_unique_char","python","def first_unique_char(text: str) -> str | None: return first character appearing once, or None", "def first_unique_char(text: str) -> str | None:\n    counts = {}\n    for char in text:\n        counts[char] = counts.get(char, 0) + 1\n    return next((char for char in text if counts[char] == 1), None)", "assert first_unique_char('swiss')=='w'\nassert first_unique_char('aabb') is None\nassert first_unique_char('') is None"),
("py_sum_positive","python","def sum_positive(values: list[int]) -> int: sum strictly positive values", "def sum_positive(values: list[int]) -> int:\n    return sum(value for value in values if value > 0)", "assert sum_positive([-2,0,3,4])==7\nassert sum_positive([-3,0])==0\nassert sum_positive([8])==8"),
("py_parse_int_or_none","python","def parse_int_or_none(text: str) -> int | None: parse base-ten integer with surrounding whitespace; None if invalid", "def parse_int_or_none(text: str) -> int | None:\n    try:\n        return int(text.strip(), 10)\n    except (ValueError, AttributeError):\n        return None", "assert parse_int_or_none('  -42 ')==-42\nassert parse_int_or_none('0')==0\nassert parse_int_or_none('4.2') is None\nassert parse_int_or_none('') is None"),
("py_longest_word","python","def longest_word(text: str) -> str: longest whitespace-separated word, first on ties, empty string if none", "def longest_word(text: str) -> str:\n    return max(text.split(), key=len, default='')", "assert longest_word('red blue green')=='green'\nassert longest_word('aa bb c')=='aa'\nassert longest_word('   ')==''"),
("rs_hamming_distance","rust","pub fn hamming_distance(a: u32, b: u32) -> u32: count differing bit positions", "pub fn hamming_distance(a: u32, b: u32) -> u32 {\n    (a ^ b).count_ones()\n}", "assert_eq!(hamming_distance(0,0),0);\nassert_eq!(hamming_distance(5,3),2);\nassert_eq!(hamming_distance(u32::MAX,0),32);"),
("rs_count_occurrences","rust","pub fn count_occurrences(values: &[i32], target: i32) -> usize: count target in slice", "pub fn count_occurrences(values: &[i32], target: i32) -> usize {\n    values.iter().filter(|&&value| value == target).count()\n}", "assert_eq!(count_occurrences(&[1,2,2,3],2),2);\nassert_eq!(count_occurrences(&[],1),0);"),
("rs_sum_positive","rust","pub fn sum_positive(values: &[i32]) -> i32: sum only strictly positive values", "pub fn sum_positive(values: &[i32]) -> i32 {\n    values.iter().copied().filter(|&value| value > 0).sum()\n}", "assert_eq!(sum_positive(&[-2,0,3,4]),7);\nassert_eq!(sum_positive(&[-1,0]),0);"),
("rs_is_power_of_two","rust","pub fn is_power_of_two(value: u64) -> bool: true only for positive powers of two", "pub fn is_power_of_two(value: u64) -> bool {\n    value != 0 && (value & (value - 1)) == 0\n}", "assert!(is_power_of_two(1));\nassert!(is_power_of_two(1024));\nassert!(!is_power_of_two(0));\nassert!(!is_power_of_two(12));"),
("rs_first_even","rust","pub fn first_even(values: &[i32]) -> Option<i32>: first even value, if any", "pub fn first_even(values: &[i32]) -> Option<i32> {\n    values.iter().copied().find(|value| value % 2 == 0)\n}", "assert_eq!(first_even(&[1,3,8,10]),Some(8));\nassert_eq!(first_even(&[1,3]),None);"),
("rs_dot_product","rust","pub fn dot_product(a: &[i32], b: &[i32]) -> Option<i32>: pairwise product sum only if lengths match", "pub fn dot_product(a: &[i32], b: &[i32]) -> Option<i32> {\n    if a.len() != b.len() { return None; }\n    Some(a.iter().zip(b).map(|(x,y)| x * y).sum())\n}", "assert_eq!(dot_product(&[1,2,3],&[4,5,6]),Some(32));\nassert_eq!(dot_product(&[],&[]),Some(0));\nassert_eq!(dot_product(&[1],&[]),None);"),
("rs_is_ascii_pangram","rust","pub fn is_ascii_pangram(text: &str) -> bool: test all 26 English letters, ignoring case", "pub fn is_ascii_pangram(text: &str) -> bool {\n    let mut seen = [false; 26];\n    for byte in text.bytes() {\n        let lower = byte.to_ascii_lowercase();\n        if lower.is_ascii_lowercase() { seen[(lower - b'a') as usize] = true; }\n    }\n    seen.into_iter().all(|present| present)\n}", "assert!(is_ascii_pangram(\"The quick brown fox jumps over the lazy dog\"));\nassert!(!is_ascii_pangram(\"quick brown fox\"));\nassert!(is_ascii_pangram(\"ABCDEFGHIJKLMNOPQRSTUVWXYZ\"));"),
("rs_parse_i64","rust","pub fn parse_i64(text: &str) -> Option<i64>: parse base-ten integer with surrounding whitespace", "pub fn parse_i64(text: &str) -> Option<i64> {\n    text.trim().parse::<i64>().ok()\n}", "assert_eq!(parse_i64(\" -42 \"),Some(-42));\nassert_eq!(parse_i64(\"0\"),Some(0));\nassert_eq!(parse_i64(\"4.2\"),None);"),
("rs_longest_word_len","rust","pub fn longest_word_len(text: &str) -> usize: character count of longest whitespace-separated word, or zero", "pub fn longest_word_len(text: &str) -> usize {\n    text.split_whitespace().map(|word| word.chars().count()).max().unwrap_or(0)\n}", "assert_eq!(longest_word_len(\"red blue green\"),5);\nassert_eq!(longest_word_len(\"   \"),0);"),
]

def sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def name_from_spec(spec: str) -> str | None:
    match = re.search(r"(?:def|pub\s+fn|fn)\s+([A-Za-z_]\w*)\s*\(", spec)
    return match.group(1) if match else None

def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    source_hash = source.pop("receipt_sha256")
    if sha_obj(source) != source_hash or sha_obj(source["samples"]) != source["training_sha256"]:
        raise ValueError("source dataset hash validation failed")
    rows, seen = [], set()
    counts = {"receipt_source": 0, "new_gate_pass": 0, "excluded": 0}
    for old in source["samples"]:
        spec = old["prompt"].split("USER:", 1)[-1].split("ASSISTANT:", 1)[0].strip()
        if old["category"].startswith("graduated_") or not name_from_spec(spec):
            counts["excluded"] += 1
            continue
        lang = "rust" if old["category"].startswith("rs_") else "python"
        code = evaluator.extract_requested_function(old["completion"], lang, spec)
        if not code:
            counts["excluded"] += 1
            continue
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        key = (lang, name_from_spec(spec), code_hash)
        if key in seen:
            continue
        seen.add(key)
        system = f"You write clean, standard-library {lang} code (do NOT import third-party packages like numpy). Reply with ONLY one fenced code block containing the implementation. No tests, no main, no explanation."
        prompt = f"SYSTEM: {system}\n\nUSER: Implement: {spec}\n\nASSISTANT:"
        rows.append({"id": old["category"], "category": f"{lang}_receipt", "prompt": prompt,
                     "completion": f"{FENCE}{lang}\n{code}\n{FENCE}{EOS}",
                     "source_kind": "receipt_verified_existing", "source_dataset_sha256": source_hash,
                     "code_sha256": code_hash})
        counts["receipt_source"] += 1
    gate_results = []
    for task_id, lang, spec, code, tests in EXTRA:
        gate = gates.gate_python if lang == "python" else gates.gate_rust
        if lang == "rust":
            tests = "#[test]\nfn candidate_reference_cases() {\n" + tests + "\n}"
        passed, error = gate(code, tests)
        gate_results.append({"id": task_id, "passed": bool(passed), "error": error[:2000]})
        if not passed:
            continue
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        key = (lang, name_from_spec(spec), code_hash)
        if key in seen:
            continue
        seen.add(key)
        system = f"You write clean, standard-library {lang} code (do NOT import third-party packages like numpy). Reply with ONLY one fenced code block containing the implementation. No tests, no main, no explanation."
        prompt = f"SYSTEM: {system}\n\nUSER: Implement: {spec}\n\nASSISTANT:"
        rows.append({"id": task_id, "category": f"{lang}_synthetic_gate_verified", "prompt": prompt,
                     "completion": f"{FENCE}{lang}\n{code}\n{FENCE}{EOS}",
                     "source_kind": "locally_authored_reference_passed_existing_docker_gate",
                     "spec_sha256": hashlib.sha256(spec.encode()).hexdigest(),
                     "code_sha256": code_hash, "tests_sha256": hashlib.sha256(tests.encode()).hexdigest(),
                     "gate": "rust" if lang == "rust" else "python"})
        counts["new_gate_pass"] += 1
    py = [r for r in rows if r["category"].startswith("python_")]
    rs = [r for r in rows if r["category"].startswith("rust_")]
    suite = json.loads((RUNS / "frozen_code_eval_v1.json").read_text(encoding="utf-8"))
    held_ids = {t["id"] for t in suite["held_out"]}
    overlap = held_ids & {r["id"] for r in rows}
    if overlap:
        raise ValueError(f"held-out identifiers in training: {sorted(overlap)}")
    balanced = py + (rs * ((len(py) + len(rs) - 1) // len(rs)))[:len(py)]
    payload = {"schema": "viv_clean_function_training_v2",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "source_dataset_sha256": source_hash, "heldout_suite_sha256": suite["suite_sha256"],
               "heldout_id_overlap": [], "python_unique": len(py), "rust_unique": len(rs),
               "source_counts": counts, "new_gate_results": gate_results,
               "samples": balanced, "training_sha256": sha_obj(balanced)}
    payload["receipt_sha256"] = sha_obj(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "receipt_sha256": payload["receipt_sha256"],
                      "python_unique": len(py), "rust_unique": len(rs),
                      "balanced_rows": len(balanced), "source_counts": counts,
                      "new_gate_failures": [r for r in gate_results if not r["passed"]]}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
