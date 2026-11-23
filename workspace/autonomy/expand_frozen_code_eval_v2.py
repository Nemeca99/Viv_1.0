"""Freeze 50-per-language coding suite after ID/function leakage checks."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "learning" / "deepseek_candidate_runs"
SOURCE = RUNS / "frozen_code_eval_v1.json"
TRAINING = RUNS / "clean_function_training_v2.json"
OUT = RUNS / "frozen_code_eval_v2_1.json"

PY = [
 ("py_celsius_to_fahrenheit", "celsius_to_fahrenheit(c: float) -> float", "convert Celsius to Fahrenheit", "assert abs(celsius_to_fahrenheit(0)-32)<1e-9\nassert abs(celsius_to_fahrenheit(100)-212)<1e-9\nassert abs(celsius_to_fahrenheit(-40)+40)<1e-9"),
 ("py_fahrenheit_to_celsius", "fahrenheit_to_celsius(f: float) -> float", "convert Fahrenheit to Celsius", "assert abs(fahrenheit_to_celsius(32))<1e-9\nassert abs(fahrenheit_to_celsius(212)-100)<1e-9\nassert abs(fahrenheit_to_celsius(-40)+40)<1e-9"),
 ("py_is_leap_year", "is_leap_year(year: int) -> bool", "Gregorian leap year rule", "assert is_leap_year(2000)\nassert not is_leap_year(1900)\nassert is_leap_year(2024)\nassert not is_leap_year(2023)"),
 ("py_days_in_month", "days_in_month(year: int, month: int) -> int", "number of days in month 1..12; February respects leap years; invalid month raises ValueError", "assert days_in_month(2024,2)==29\nassert days_in_month(1900,2)==28\nassert days_in_month(2023,4)==30\nassert days_in_month(2023,12)==31\ntry:\n days_in_month(2023,13)\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_ceil_division", "ceil_division(a: int, b: int) -> int", "mathematical ceiling of a/b for nonzero divisor", "assert ceil_division(7,3)==3\nassert ceil_division(-7,3)==-2\nassert ceil_division(7,-3)==-2\nassert ceil_division(-6,3)==-2"),
 ("py_is_divisible", "is_divisible(value: int, divisor: int) -> bool", "whether value is evenly divisible; zero divisor returns False", "assert is_divisible(12,3)\nassert not is_divisible(13,3)\nassert is_divisible(0,7)\nassert not is_divisible(4,0)"),
 ("py_range_sum", "range_sum(start: int, end: int) -> int", "sum integers in inclusive ascending range; return zero when start exceeds end", "assert range_sum(1,5)==15\nassert range_sum(-2,2)==0\nassert range_sum(4,4)==4\nassert range_sum(5,2)==0"),
 ("py_pairwise_difference", "pairwise_difference(a: list[int], b: list[int]) -> list[int]", "absolute differences for paired values; reject unequal lengths with ValueError", "assert pairwise_difference([1,8,-2],[4,3,5])==[3,5,7]\nassert pairwise_difference([],[])==[]\ntry:\n pairwise_difference([1],[1,2])\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_running_total", "running_total(values: list[int]) -> list[int]", "prefix sums of values", "assert running_total([2,-1,4])==[2,1,5]\nassert running_total([])==[]\nassert running_total([0,0])==[0,0]"),
 ("py_take_every_other", "take_every_other(values: list[int]) -> list[int]", "return elements at even indices", "assert take_every_other([0,1,2,3,4])==[0,2,4]\nassert take_every_other([8])==[8]\nassert take_every_other([])==[]"),
 ("py_rotate_left", "rotate_left(values: list[int], k: int) -> list[int]", "rotate left by nonnegative k with wraparound; empty input stays empty", "assert rotate_left([1,2,3,4],1)==[2,3,4,1]\nassert rotate_left([1,2,3],5)==[3,1,2]\nassert rotate_left([],8)==[]"),
 ("py_chunked", "chunked(values: list[int], size: int) -> list[list[int]]", "split into consecutive chunks of positive size; final chunk may be shorter; nonpositive size raises ValueError", "assert chunked([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert chunked([],3)==[]\ntry:\n chunked([1],0)\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_partition_by_sign", "partition_by_sign(values: list[int]) -> tuple[list[int], list[int], list[int]]", "return negative, zero, and positive values in separate stable lists", "assert partition_by_sign([2,0,-1,3,-4,0])==([-1,-4],[0,0],[2,3])\nassert partition_by_sign([])==([],[],[])"),
 ("py_first_duplicate", "first_duplicate(values: list[int]) -> int | None", "return first value whose second occurrence appears earliest, or None", "assert first_duplicate([2,1,3,1,2])==1\nassert first_duplicate([1,2,3]) is None\nassert first_duplicate([]) is None"),
 ("py_unique_in_order", "unique_in_order(values: list[int]) -> list[int]", "remove later duplicates while keeping first occurrence order", "assert unique_in_order([3,1,3,2,1])==[3,1,2]\nassert unique_in_order([])==[]\nassert unique_in_order([4,4])==[4]"),
 ("py_intersection_in_order", "intersection_in_order(a: list[int], b: list[int]) -> list[int]", "distinct values present in both inputs, in first-input order", "assert intersection_in_order([3,1,3,2],[2,3])==[3,2]\nassert intersection_in_order([1,2],[4])==[]\nassert intersection_in_order([],[])==[]"),
 ("py_second_smallest_distinct", "second_smallest_distinct(values: list[int]) -> int | None", "second smallest distinct integer, or None if fewer than two distinct values", "assert second_smallest_distinct([4,1,1,3])==3\nassert second_smallest_distinct([-2,-5,8])==-2\nassert second_smallest_distinct([2,2]) is None"),
 ("py_has_adjacent_duplicate", "has_adjacent_duplicate(values: list[int]) -> bool", "whether equal values occur next to each other", "assert has_adjacent_duplicate([1,2,2,3])\nassert not has_adjacent_duplicate([1,2,1])\nassert not has_adjacent_duplicate([])"),
 ("py_is_monotonic", "is_monotonic(values: list[int]) -> bool", "whether values are nondecreasing or nonincreasing", "assert is_monotonic([1,2,2,4])\nassert is_monotonic([5,3,3,0])\nassert is_monotonic([1,1])\nassert not is_monotonic([1,3,2])"),
 ("py_sort_by_absolute", "sort_by_absolute(values: list[int]) -> list[int]", "sort by absolute value, keeping ordinary numeric order for equal absolute values", "assert sort_by_absolute([3,-1,2,-3])==[-1,2,-3,3]\nassert sort_by_absolute([])==[]"),
 ("py_is_subsequence", "is_subsequence(short: str, long: str) -> bool", "case-sensitive subsequence test", "assert is_subsequence('ace','abcde')\nassert not is_subsequence('aec','abcde')\nassert is_subsequence('','abc')\nassert is_subsequence('abc','abc')"),
 ("py_common_prefix", "common_prefix(words: list[str]) -> str", "longest shared prefix; empty input returns empty string", "assert common_prefix(['interview','internet','internal'])=='inter'\nassert common_prefix(['dog','cat'])==''\nassert common_prefix([])==''\nassert common_prefix(['same'])=='same'"),
 ("py_reverse_words", "reverse_words(text: str) -> str", "reverse word order and join with one space; discard surrounding and repeated whitespace", "assert reverse_words('  one  two three ' )=='three two one'\nassert reverse_words('')==''\nassert reverse_words('solo')=='solo'"),
 ("py_count_character", "count_character(text: str, target: str) -> int", "count exact character occurrences; target is one character", "assert count_character('banana','a')==3\nassert count_character('abc','z')==0\nassert count_character('','a')==0"),
 ("py_word_lengths", "word_lengths(text: str) -> list[int]", "character lengths of whitespace-separated words", "assert word_lengths('red blue')==[3,4]\nassert word_lengths('  ')==[]\nassert word_lengths('a bb')==[1,2]"),
 ("py_acronym", "acronym(text: str) -> str", "uppercase first character of each whitespace-separated word", "assert acronym('portable network graphics')=='PNG'\nassert acronym('')==''\nassert acronym('one')=='O'"),
 ("py_collapse_whitespace", "collapse_whitespace(text: str) -> str", "replace each whitespace run with one ASCII space and trim ends", "assert collapse_whitespace(' a\\t b  c\\n')=='a b c'\nassert collapse_whitespace('   ')==''\nassert collapse_whitespace('x')=='x'"),
 ("py_count_lines", "count_lines(text: str) -> int", "count newline-separated lines; empty string has zero lines and trailing newline adds no extra line", "assert count_lines('a\\nb')==2\nassert count_lines('a\\nb\\n')==2\nassert count_lines('')==0\nassert count_lines('one')==1"),
 ("py_matrix_trace", "matrix_trace(matrix: list[list[int]]) -> int", "sum main diagonal of square matrix; reject nonsquare matrix with ValueError", "assert matrix_trace([[1,2],[3,4]])==5\nassert matrix_trace([[7]])==7\nassert matrix_trace([])==0\ntry:\n matrix_trace([[1,2,3]])\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_matrix_row_sums", "matrix_row_sums(matrix: list[list[int]]) -> list[int]", "sum each row independently", "assert matrix_row_sums([[1,2],[3],[]])==[3,3,0]\nassert matrix_row_sums([])==[]"),
 ("py_diagonal_difference", "diagonal_difference(matrix: list[list[int]]) -> int", "absolute difference between main and anti-diagonal sums of a square matrix", "assert diagonal_difference([[1,2,3],[4,5,6],[7,8,9]])==0\nassert diagonal_difference([[1,2],[3,4]])==0\nassert diagonal_difference([])==0"),
 ("py_flatten_once", "flatten_once(matrix: list[list[int]]) -> list[int]", "flatten one list level from left to right", "assert flatten_once([[1,2],[],[3]])==[1,2,3]\nassert flatten_once([])==[]"),
 ("py_run_length_encode", "run_length_encode(text: str) -> list[tuple[str, int]]", "encode consecutive equal characters as character/count pairs", "assert run_length_encode('aaabbc')==[('a',3),('b',2),('c',1)]\nassert run_length_encode('')==[]\nassert run_length_encode('x')==[('x',1)]"),
 ("py_binary_search_first", "binary_search_first(values: list[int], target: int) -> int", "index of first target in ascending list, or -1", "assert binary_search_first([1,2,2,2,5],2)==1\nassert binary_search_first([1,3],2)==-1\nassert binary_search_first([],0)==-1"),
 ("py_clamp_all", "clamp_all(values: list[int], low: int, high: int) -> list[int]", "clamp each value to inclusive bounds; assume low <= high", "assert clamp_all([-2,2,8],0,5)==[0,2,5]\nassert clamp_all([],0,1)==[]"),
 ("py_merge_intervals", "merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]", "merge overlapping or touching inclusive intervals; return sorted intervals", "assert merge_intervals([(5,7),(1,3),(3,4)])==[(1,4),(5,7)]\nassert merge_intervals([])==[]\nassert merge_intervals([(2,2)])==[(2,2)]"),
 ("py_count_runs", "count_runs(values: list[int]) -> int", "count nonempty runs of equal adjacent values", "assert count_runs([1,1,2,2,2,1])==3\nassert count_runs([])==0\nassert count_runs([5])==1"),
 ("py_best_stock_profit", "best_stock_profit(prices: list[int]) -> int", "maximum positive later-minus-earlier price difference; zero if no profitable pair", "assert best_stock_profit([7,1,5,3,6,4])==5\nassert best_stock_profit([7,6,4,3])==0\nassert best_stock_profit([])==0"),
 ("py_sum_every_nth", "sum_every_nth(values: list[int], n: int) -> int", "sum elements at indices 0,n,2n; n must be positive", "assert sum_every_nth([1,2,3,4,5],2)==9\nassert sum_every_nth([],3)==0\ntry:\n sum_every_nth([1],0)\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_zip_to_dict", "zip_to_dict(keys: list[str], values: list[int]) -> dict[str, int]", "map paired keys to values; reject unequal lengths with ValueError; later duplicate key wins", "assert zip_to_dict(['a','b'],[1,2])=={'a':1,'b':2}\nassert zip_to_dict(['a','a'],[1,3])=={'a':3}\ntry:\n zip_to_dict(['a'],[])\n raise AssertionError()\nexcept ValueError: pass"),
 ("py_most_frequent", "most_frequent(values: list[int]) -> int | None", "most frequent integer; ties resolved by first value encountered; None for empty", "assert most_frequent([2,1,1,2])==2\nassert most_frequent([4,4,1])==4\nassert most_frequent([]) is None"),
 ("py_nth_from_end", "nth_from_end(values: list[int], n: int) -> int | None", "return one-based nth item from end; None when n is out of range or nonpositive", "assert nth_from_end([1,2,3],1)==3\nassert nth_from_end([1,2,3],3)==1\nassert nth_from_end([1],2) is None\nassert nth_from_end([1],0) is None"),
 ("py_is_valid_identifier", "is_valid_identifier(text: str) -> bool", "whether text is a valid Python identifier and is not a keyword", "assert is_valid_identifier('valid_name')\nassert not is_valid_identifier('2bad')\nassert not is_valid_identifier('class')\nassert not is_valid_identifier('')"),
 ("py_split_even_odd", "split_even_odd(values: list[int]) -> tuple[list[int], list[int]]", "return even and odd values separately, preserving order", "assert split_even_odd([1,2,3,4])==([2,4],[1,3])\nassert split_even_odd([])==([],[])"),
]

RS = [
 ("rs_celsius_to_fahrenheit", "pub fn celsius_to_fahrenheit(c: f64) -> f64", "convert Celsius to Fahrenheit", 'assert!((celsius_to_fahrenheit(0.0)-32.0).abs()<1e-9); assert!((celsius_to_fahrenheit(100.0)-212.0).abs()<1e-9); assert!((celsius_to_fahrenheit(-40.0)+40.0).abs()<1e-9);'),
 ("rs_fahrenheit_to_celsius", "pub fn fahrenheit_to_celsius(f: f64) -> f64", "convert Fahrenheit to Celsius", 'assert!((fahrenheit_to_celsius(32.0)).abs()<1e-9); assert!((fahrenheit_to_celsius(212.0)-100.0).abs()<1e-9); assert!((fahrenheit_to_celsius(-40.0)+40.0).abs()<1e-9);'),
 ("rs_is_leap_year", "pub fn is_leap_year(year: i32) -> bool", "Gregorian leap year rule", "assert!(is_leap_year(2000)); assert!(!is_leap_year(1900)); assert!(is_leap_year(2024)); assert!(!is_leap_year(2023));"),
 ("rs_days_in_month", "pub fn days_in_month(year: i32, month: u32) -> Option<u32>", "number of days in month 1..12, with leap February; None for invalid month", "assert_eq!(days_in_month(2024,2),Some(29)); assert_eq!(days_in_month(1900,2),Some(28)); assert_eq!(days_in_month(2023,4),Some(30)); assert_eq!(days_in_month(2023,13),None);"),
 ("rs_ceil_division", "pub fn ceil_division(a: i64, b: i64) -> Option<i64>", "mathematical ceiling of a/b; None for zero divisor", "assert_eq!(ceil_division(7,3),Some(3)); assert_eq!(ceil_division(-7,3),Some(-2)); assert_eq!(ceil_division(7,-3),Some(-2)); assert_eq!(ceil_division(4,0),None);"),
 ("rs_is_divisible", "pub fn is_divisible(value: i64, divisor: i64) -> bool", "evenly divisible; false for zero divisor", "assert!(is_divisible(12,3)); assert!(!is_divisible(13,3)); assert!(is_divisible(0,7)); assert!(!is_divisible(4,0));"),
 ("rs_range_sum", "pub fn range_sum(start: i64, end: i64) -> i64", "sum inclusive ascending range; zero when start exceeds end", "assert_eq!(range_sum(1,5),15); assert_eq!(range_sum(-2,2),0); assert_eq!(range_sum(4,4),4); assert_eq!(range_sum(5,2),0);"),
 ("rs_pairwise_difference", "pub fn pairwise_difference(a: &[i32], b: &[i32]) -> Option<Vec<i32>>", "absolute differences for paired values; None for unequal lengths", "assert_eq!(pairwise_difference(&[1,8,-2],&[4,3,5]),Some(vec![3,5,7])); assert_eq!(pairwise_difference(&[],&[]),Some(vec![])); assert_eq!(pairwise_difference(&[1],&[1,2]),None);"),
 ("rs_running_total", "pub fn running_total(values: &[i32]) -> Vec<i32>", "prefix sums", "assert_eq!(running_total(&[2,-1,4]),vec![2,1,5]); assert_eq!(running_total(&[]),Vec::<i32>::new());"),
 ("rs_take_every_other", "pub fn take_every_other(values: &[i32]) -> Vec<i32>", "return values at even indices", "assert_eq!(take_every_other(&[0,1,2,3,4]),vec![0,2,4]); assert_eq!(take_every_other(&[8]),vec![8]); assert_eq!(take_every_other(&[]),Vec::<i32>::new());"),
 ("rs_rotate_left", "pub fn rotate_left(values: &[i32], k: usize) -> Vec<i32>", "rotate left by k with wraparound; empty input stays empty", "assert_eq!(rotate_left(&[1,2,3,4],1),vec![2,3,4,1]); assert_eq!(rotate_left(&[1,2,3],5),vec![3,1,2]); assert_eq!(rotate_left(&[],8),Vec::<i32>::new());"),
 ("rs_chunked", "pub fn chunked(values: &[i32], size: usize) -> Option<Vec<Vec<i32>>>", "split into positive-sized chunks; None for zero size", "assert_eq!(chunked(&[1,2,3,4,5],2),Some(vec![vec![1,2],vec![3,4],vec![5]])); assert_eq!(chunked(&[],3),Some(vec![])); assert_eq!(chunked(&[1],0),None);"),
 ("rs_partition_by_sign", "pub fn partition_by_sign(values: &[i32]) -> (Vec<i32>, Vec<i32>, Vec<i32>)", "stable negative, zero, positive partitions", "assert_eq!(partition_by_sign(&[2,0,-1,3,-4,0]),(vec![-1,-4],vec![0,0],vec![2,3]));"),
 ("rs_first_duplicate", "pub fn first_duplicate(values: &[i32]) -> Option<i32>", "first value whose second occurrence appears earliest", "assert_eq!(first_duplicate(&[2,1,3,1,2]),Some(1)); assert_eq!(first_duplicate(&[1,2,3]),None);"),
 ("rs_unique_in_order", "pub fn unique_in_order(values: &[i32]) -> Vec<i32>", "remove later duplicates, preserving first occurrence order", "assert_eq!(unique_in_order(&[3,1,3,2,1]),vec![3,1,2]); assert_eq!(unique_in_order(&[]),Vec::<i32>::new());"),
 ("rs_intersection_in_order", "pub fn intersection_in_order(a: &[i32], b: &[i32]) -> Vec<i32>", "distinct values common to both slices in first-slice order", "assert_eq!(intersection_in_order(&[3,1,3,2],&[2,3]),vec![3,2]); assert_eq!(intersection_in_order(&[1,2],&[4]),Vec::<i32>::new());"),
 ("rs_second_smallest_distinct", "pub fn second_smallest_distinct(values: &[i32]) -> Option<i32>", "second smallest distinct value or None", "assert_eq!(second_smallest_distinct(&[4,1,1,3]),Some(3)); assert_eq!(second_smallest_distinct(&[-2,-5,8]),Some(-2)); assert_eq!(second_smallest_distinct(&[2,2]),None);"),
 ("rs_adjacent_duplicate", "pub fn has_adjacent_duplicate(values: &[i32]) -> bool", "whether equal values are adjacent", "assert!(has_adjacent_duplicate(&[1,2,2,3])); assert!(!has_adjacent_duplicate(&[1,2,1])); assert!(!has_adjacent_duplicate(&[]));"),
 ("rs_is_monotonic", "pub fn is_monotonic(values: &[i32]) -> bool", "whether values are nondecreasing or nonincreasing", "assert!(is_monotonic(&[1,2,2,4])); assert!(is_monotonic(&[5,3,3,0])); assert!(!is_monotonic(&[1,3,2]));"),
 ("rs_sort_by_absolute", "pub fn sort_by_absolute(values: &[i32]) -> Vec<i32>", "sort by absolute value, with numeric ascending tie order", "assert_eq!(sort_by_absolute(&[3,-1,2,-3]),vec![-1,2,-3,3]); assert_eq!(sort_by_absolute(&[]),Vec::<i32>::new());"),
 ("rs_is_subsequence", "pub fn is_subsequence(short: &str, long: &str) -> bool", "case-sensitive Unicode character subsequence", 'assert!(is_subsequence("ace","abcde")); assert!(!is_subsequence("aec","abcde")); assert!(is_subsequence("","abc"));'),
 ("rs_common_prefix", "pub fn common_prefix(words: &[&str]) -> String", "longest shared prefix or empty string", 'assert_eq!(common_prefix(&["interview","internet","internal"]),"inter"); assert_eq!(common_prefix(&["dog","cat"]),""); assert_eq!(common_prefix(&[]),"");'),
 ("rs_reverse_words", "pub fn reverse_words(text: &str) -> String", "reverse whitespace-separated word order and join with single spaces", 'assert_eq!(reverse_words(" one  two three "),"three two one"); assert_eq!(reverse_words(""),"");'),
 ("rs_count_character", "pub fn count_character(text: &str, target: char) -> usize", "count exact Unicode character occurrences", 'assert_eq!(count_character("banana",\'a\'),3); assert_eq!(count_character("abc",\'z\'),0);'),
 ("rs_word_lengths", "pub fn word_lengths(text: &str) -> Vec<usize>", "character counts for whitespace-separated words", 'assert_eq!(word_lengths("red blue"),vec![3,4]); assert_eq!(word_lengths("  "),Vec::<usize>::new());'),
 ("rs_acronym", "pub fn acronym(text: &str) -> String", "uppercase first character of whitespace-separated words", 'assert_eq!(acronym("portable network graphics"),"PNG"); assert_eq!(acronym(""),"");'),
 ("rs_collapse_whitespace", "pub fn collapse_whitespace(text: &str) -> String", "collapse whitespace runs to one ASCII space and trim ends", 'assert_eq!(collapse_whitespace(" a\\t b  c\\n"),"a b c"); assert_eq!(collapse_whitespace("   "),"");'),
 ("rs_count_lines", "pub fn count_lines(text: &str) -> usize", "count newline-separated lines; empty is zero; trailing newline adds no empty line", 'assert_eq!(count_lines("a\\nb"),2); assert_eq!(count_lines("a\\nb\\n"),2); assert_eq!(count_lines(""),0);'),
 ("rs_matrix_trace", "pub fn matrix_trace(matrix: &[Vec<i32>]) -> Option<i32>", "sum main diagonal of square matrix; None when nonsquare; empty matrix is square and returns Some(0)", "assert_eq!(matrix_trace(&[vec![1,2],vec![3,4]]),Some(5)); assert_eq!(matrix_trace(&[vec![7]]),Some(7)); assert_eq!(matrix_trace(&[]),Some(0)); assert_eq!(matrix_trace(&[vec![1,2]]),None);"),
 ("rs_matrix_row_sums", "pub fn matrix_row_sums(matrix: &[Vec<i32>]) -> Vec<i32>", "sum each row", "assert_eq!(matrix_row_sums(&[vec![1,2],vec![3],vec![]]),vec![3,3,0]); assert_eq!(matrix_row_sums(&[]),Vec::<i32>::new());"),
 ("rs_diagonal_difference", "pub fn diagonal_difference(matrix: &[Vec<i32>]) -> Option<u32>", "absolute difference of diagonal sums for square matrix; None for nonsquare; empty matrix returns Some(0)", "assert_eq!(diagonal_difference(&[vec![1,2,3],vec![4,5,6],vec![7,8,9]]),Some(0)); assert_eq!(diagonal_difference(&[vec![1,2],vec![3,4]]),Some(0)); assert_eq!(diagonal_difference(&[]),Some(0));"),
 ("rs_flatten_once", "pub fn flatten_once(matrix: &[Vec<i32>]) -> Vec<i32>", "flatten one vector level in order", "assert_eq!(flatten_once(&[vec![1,2],vec![],vec![3]]),vec![1,2,3]); assert_eq!(flatten_once(&[]),Vec::<i32>::new());"),
 ("rs_run_length_encode", "pub fn run_length_encode(text: &str) -> Vec<(char, usize)>", "encode adjacent equal Unicode characters as character/count pairs", 'assert_eq!(run_length_encode("aaabbc"),vec![(\'a\',3),(\'b\',2),(\'c\',1)]); assert_eq!(run_length_encode(""),Vec::<(char,usize)>::new());'),
 ("rs_binary_search_first", "pub fn binary_search_first(values: &[i32], target: i32) -> Option<usize>", "first target index in ascending slice, or None", "assert_eq!(binary_search_first(&[1,2,2,2,5],2),Some(1)); assert_eq!(binary_search_first(&[1,3],2),None); assert_eq!(binary_search_first(&[],0),None);"),
 ("rs_clamp_all", "pub fn clamp_all(values: &[i32], low: i32, high: i32) -> Vec<i32>", "clamp values to inclusive bounds; assume low <= high", "assert_eq!(clamp_all(&[-2,2,8],0,5),vec![0,2,5]); assert_eq!(clamp_all(&[],0,1),Vec::<i32>::new());"),
 ("rs_merge_intervals", "pub fn merge_intervals(intervals: &[(i32, i32)]) -> Vec<(i32, i32)>", "sort and merge overlapping or touching inclusive intervals", "assert_eq!(merge_intervals(&[(5,7),(1,3),(3,4)]),vec![(1,4),(5,7)]); assert_eq!(merge_intervals(&[]),Vec::<(i32,i32)>::new());"),
 ("rs_count_runs", "pub fn count_runs(values: &[i32]) -> usize", "count nonempty runs of equal adjacent values", "assert_eq!(count_runs(&[1,1,2,2,2,1]),3); assert_eq!(count_runs(&[]),0); assert_eq!(count_runs(&[5]),1);"),
 ("rs_best_stock_profit", "pub fn best_stock_profit(prices: &[i32]) -> i32", "maximum later-minus-earlier price difference, floored at zero", "assert_eq!(best_stock_profit(&[7,1,5,3,6,4]),5); assert_eq!(best_stock_profit(&[7,6,4,3]),0); assert_eq!(best_stock_profit(&[]),0);"),
 ("rs_sum_every_nth", "pub fn sum_every_nth(values: &[i32], n: usize) -> Option<i32>", "sum values at indices 0,n,2n; None when n is zero", "assert_eq!(sum_every_nth(&[1,2,3,4,5],2),Some(9)); assert_eq!(sum_every_nth(&[],3),Some(0)); assert_eq!(sum_every_nth(&[1],0),None);"),
 ("rs_nth_from_end", "pub fn nth_from_end(values: &[i32], n: usize) -> Option<i32>", "one-based nth value from end; None for zero or out of range", "assert_eq!(nth_from_end(&[1,2,3],1),Some(3)); assert_eq!(nth_from_end(&[1,2,3],3),Some(1)); assert_eq!(nth_from_end(&[1],0),None);"),
]

def digest(value: object) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()

def main() -> int:
    base = json.loads(SOURCE.read_text(encoding="utf-8"))
    base_hash = base.pop("suite_sha256")
    if digest(base) != base_hash:
        raise ValueError("source frozen suite hash mismatch")
    training = json.loads(TRAINING.read_text(encoding="utf-8"))
    train_ids = {row["id"] for row in training["samples"]}
    train_names = {"python": set(), "rust": set()}
    for row in training["samples"]:
        match = re.search(r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(", row["prompt"])
        if match:
            lang = "rust" if row["category"].startswith("rust_") else "python"
            train_names[lang].add(match.group(1))
    tasks = list(base["held_out"])
    additions = []
    for prefix, lang, rows in (("py", "python", PY), ("rs", "rust", RS)):
        if len(rows) < 40:
            raise ValueError(f"need at least 40 {lang} additions, found {len(rows)}")
        for task_id, signature, description, checks in rows[:40]:
            signature_name = re.match(r"(?:pub\s+fn\s+)?([A-Za-z_]\w*)\s*\(", signature)
            if not signature_name:
                raise ValueError(f"invalid signature: {task_id}")
            name = signature_name.group(1)
            if task_id in train_ids or name in train_names[lang]:
                raise ValueError(f"training overlap: {task_id} / {name}")
            if lang == "python":
                spec = f"def {signature}: {description}"
                tests = checks
            else:
                spec = f"{signature}: {description}"
                tests = "#[cfg(test)] mod t { use super::*; #[test] fn cases(){ " + checks + " } }"
            additions.append({"id": task_id, "lang": lang, "spec": spec, "tests": tests,
                              "source_kind": "locally_authored_frozen_task_v2"})
    existing_ids = {task["id"] for task in tasks}
    existing_names = {"python": set(), "rust": set()}
    for task in tasks:
        match = re.search(r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(", task["spec"])
        if match:
            existing_names[task["lang"]].add(match.group(1))
    if len(existing_ids) != len(tasks):
        raise ValueError("duplicate source task IDs")
    for item in additions:
        match = re.search(r"(?:def|pub\s+fn)\s+([A-Za-z_]\w*)\s*\(", item["spec"])
        if item["id"] in existing_ids or (match and match.group(1) in existing_names[item["lang"]]):
            raise ValueError(f"held-out duplicate: {item['id']}")
        existing_ids.add(item["id"])
        if match:
            existing_names[item["lang"]].add(match.group(1))
    tasks.extend(additions)
    counts = {lang: sum(task["lang"] == lang for task in tasks) for lang in ("python", "rust")}
    if counts != {"python": 50, "rust": 50}:
        raise ValueError(f"unexpected language counts: {counts}")
    payload = {"schema": "viv_frozen_candidate_code_eval_v2_1",
               "created_utc": datetime.now(timezone.utc).isoformat(),
               "parent_suite_sha256": base_hash,
               "training_dataset_sha256": training["receipt_sha256"],
               "training_id_overlap": [], "training_function_name_overlap": [],
               "held_out": tasks, "by_language": counts,
               "task_source": "original 20 retained; 80 new locally authored specifications and explicit deterministic cases"}
    payload["suite_sha256"] = digest(payload)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT), "suite_sha256": payload["suite_sha256"],
                      "parent_suite_sha256": base_hash, "by_language": counts,
                      "training_id_overlap": [], "training_function_name_overlap": [],
                      "new_tasks": len(additions)}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
