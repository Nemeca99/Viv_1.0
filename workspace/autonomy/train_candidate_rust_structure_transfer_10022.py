"""Train a candidate-only Rust structure-transfer curriculum from epoch 10016."""
from pathlib import Path
import train_candidate_rust_boundary_transfer_10020 as experiment

experiment.EPOCH = 10022
experiment.CHECK_PRIOR_FUNCTION_NAMES = True
experiment.DEST = experiment.ROOT / "epoch_10022"
experiment.DATA = experiment.RUNS / "candidate_rust_training_10022.json"
experiment.PREFLIGHT = experiment.RUNS / "candidate_rust_preflight_10022.json"
experiment.RECEIPT = experiment.RUNS / "candidate_rust_training_run_10022.json"
# Keep parent, seed, learning rate, repetitions, and optimizer-step budget
# matched to epoch 10021; the curriculum examples are the changed variable.
experiment.SEED = 20261143
experiment.LR = 5e-6
experiment.STEPS = 24
experiment.REPEATS = 3

experiment.EXAMPLES = [
    (
        "checked_growth",
        "pub fn checked_growth(value: u32, increase: u32) -> Option<u32>: add the increase and return None if the result overflows",
        "pub fn checked_growth(value: u32, increase: u32) -> Option<u32> { value.checked_add(increase) }",
        "assert_eq!(checked_growth(7,3),Some(10)); assert_eq!(checked_growth(u32::MAX,1),None); assert_eq!(checked_growth(0,0),Some(0));",
    ),
    (
        "positive_total_wide",
        "pub fn positive_total_wide(values: &[i32]) -> i64: sum only values greater than zero using a wide result",
        "pub fn positive_total_wide(values: &[i32]) -> i64 { values.iter().copied().filter(|value| *value > 0).map(i64::from).sum() }",
        "assert_eq!(positive_total_wide(&[-2,0,3,4]),7); assert_eq!(positive_total_wide(&[]),0); assert_eq!(positive_total_wide(&[i32::MAX,i32::MAX]),4294967294);",
    ),
    (
        "last_index_at_least",
        "pub fn last_index_at_least(values: &[i32], threshold: i32) -> Option<usize>: return the last index whose value is at least the threshold",
        "pub fn last_index_at_least(values: &[i32], threshold: i32) -> Option<usize> { values.iter().rposition(|value| *value >= threshold) }",
        "assert_eq!(last_index_at_least(&[1,5,3,6],4),Some(3)); assert_eq!(last_index_at_least(&[4,2,4],4),Some(2)); assert_eq!(last_index_at_least(&[1,2],5),None); assert_eq!(last_index_at_least(&[],0),None);",
    ),
    (
        "ascii_digits_only",
        "pub fn ascii_digits_only(text: &str) -> String: keep only ASCII digit characters in their original order",
        "pub fn ascii_digits_only(text: &str) -> String { text.chars().filter(|ch| ch.is_ascii_digit()).collect() }",
        "assert_eq!(ascii_digits_only(\"a1B02!\"),\"102\"); assert_eq!(ascii_digits_only(\"\"),\"\"); assert_eq!(ascii_digits_only(\"１２3\"),\"3\");",
    ),
    (
        "strings_sorted_by_length",
        "pub fn strings_sorted_by_length(words: &[String]) -> Vec<String>: stably sort cloned words by Unicode character count",
        "pub fn strings_sorted_by_length(words: &[String]) -> Vec<String> { let mut result = words.to_vec(); result.sort_by_key(|word| word.chars().count()); result }",
        "let words = vec![String::from(\"z\"),String::from(\"cat\"),String::from(\"ox\"),String::from(\"bird\")]; assert_eq!(strings_sorted_by_length(&words),vec![String::from(\"z\"),String::from(\"ox\"),String::from(\"cat\"),String::from(\"bird\")]); let tied = vec![String::from(\"aa\"),String::from(\"bb\"),String::from(\"c\")]; assert_eq!(strings_sorted_by_length(&tied),vec![String::from(\"c\"),String::from(\"aa\"),String::from(\"bb\")]);",
    ),
    (
        "partition_nonnegative",
        "pub fn partition_nonnegative(values: &[i32]) -> (Vec<i32>, Vec<i32>): return nonnegative values first and negative values second, preserving order within each group",
        "pub fn partition_nonnegative(values: &[i32]) -> (Vec<i32>, Vec<i32>) { let mut nonnegative = Vec::new(); let mut negative = Vec::new(); for &value in values { if value >= 0 { nonnegative.push(value); } else { negative.push(value); } } (nonnegative, negative) }",
        "assert_eq!(partition_nonnegative(&[0,-2,4,-1,3]),(vec![0,4,3],vec![-2,-1])); assert_eq!(partition_nonnegative(&[]),(Vec::<i32>::new(),Vec::<i32>::new()));",
    ),
    (
        "cumulative_products_wide",
        "pub fn cumulative_products_wide(values: &[i64]) -> Vec<i64>: return each cumulative product from left to right",
        "pub fn cumulative_products_wide(values: &[i64]) -> Vec<i64> { let mut product = 1i64; let mut output = Vec::with_capacity(values.len()); for &value in values { product *= value; output.push(product); } output }",
        "assert_eq!(cumulative_products_wide(&[2,-3,4]),vec![2,-6,-24]); assert_eq!(cumulative_products_wide(&[]),Vec::<i64>::new()); assert_eq!(cumulative_products_wide(&[5,0,7]),vec![5,0,0]);",
    ),
    (
        "select_even_indices_i32",
        "pub fn select_even_indices_i32(values: &[i32]) -> Vec<i32>: copy values at indices 0, 2, 4 and so on",
        "pub fn select_even_indices_i32(values: &[i32]) -> Vec<i32> { values.iter().step_by(2).copied().collect() }",
        "assert_eq!(select_even_indices_i32(&[10,11,12,13,14]),vec![10,12,14]); assert_eq!(select_even_indices_i32(&[7]),vec![7]); assert_eq!(select_even_indices_i32(&[]),Vec::<i32>::new());",
    ),
]


if __name__ == "__main__":
    raise SystemExit(experiment.main())
