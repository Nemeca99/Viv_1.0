"""Real reference code for Viv to study and compare against.

STUDY: idiomatic examples of *other* functions, shown before every attempt.
REFERENCE: known-good solution per curriculum task, used only after an attempt
to compare her code against (diff plus behaviour on shared inputs).
"""

STUDY = {
    "python": [
        "def count_vowels(s: str) -> int:\n    return sum(1 for ch in s.lower() if ch in 'aeiou')",
        "import re\n\ndef slugify(s: str) -> str:\n    return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')",
        "def unique_sorted(xs: list[int]) -> list[int]:\n    return sorted(set(xs))",
        "def merge_counts(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:\n    out = dict(a)\n    for k, v in b.items():\n        out[k] = out.get(k, 0) + v\n    return out",
    ],
    "rust": [
        "pub fn sum_to(n: u64) -> u64 {\n    (1..=n).sum()\n}",
        "pub fn count_char(s: &str, c: char) -> usize {\n    s.chars().filter(|&x| x == c).count()\n}",
        "pub fn max_of(xs: &[i32]) -> Option<i32> {\n    xs.iter().copied().max()\n}",
        "pub fn gcd(mut a: u64, mut b: u64) -> u64 {\n    while b != 0 {\n        let t = b;\n        b = a % b;\n        a = t;\n    }\n    a\n}",
    ],
}

REFERENCE = {
    "py_reverse_string": "def reverse_string(s: str) -> str:\n    return s[::-1]",
    "py_factorial": "def factorial(n: int) -> int:\n    result = 1\n    for i in range(2, n + 1):\n        result *= i\n    return result",
    "py_is_palindrome": "def is_palindrome(s: str) -> bool:\n    cleaned = [c.lower() for c in s if c.isalnum()]\n    return cleaned == cleaned[::-1]",
    "py_word_freq": "def word_freq(text: str) -> dict[str, int]:\n    counts: dict[str, int] = {}\n    for w in text.lower().split():\n        counts[w] = counts.get(w, 0) + 1\n    return counts",
    "rs_fib": "pub fn fib(n: u32) -> u64 {\n    let (mut a, mut b) = (0u64, 1u64);\n    for _ in 0..n {\n        let t = a + b;\n        a = b;\n        b = t;\n    }\n    a\n}",
    "rs_is_prime": "pub fn is_prime(n: u64) -> bool {\n    if n < 2 {\n        return false;\n    }\n    let mut i = 2;\n    while i * i <= n {\n        if n % i == 0 {\n            return false;\n        }\n        i += 1;\n    }\n    true\n}",
    "rs_reverse": "pub fn reverse(s: &str) -> String {\n    s.chars().rev().collect()\n}",
}
