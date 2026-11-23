"""The single candidate-only Python curriculum test file for epoch 10017.

Add curriculum examples here as they are learned. The separate trainer gate-checks
each reference and derives the model samples from this file; held-out tasks stay
in the immutable frozen suite.
"""

CURRICULUM = [
    {
        "id": "py17_increment_value",
        "spec": "def increment_value(value: int) -> int: return value plus one",
        "code": "def increment_value(value):\n    return value + 1",
        "tests": "assert increment_value(0) == 1\nassert increment_value(-4) == -3\nassert increment_value(12) == 13",
    },
    {
        "id": "py17_is_multiple_of_three",
        "spec": "def is_multiple_of_three(value: int) -> bool: true exactly when value is divisible by three",
        "code": "def is_multiple_of_three(value):\n    return value % 3 == 0",
        "tests": "assert is_multiple_of_three(0)\nassert is_multiple_of_three(-9)\nassert not is_multiple_of_three(10)",
    },
    {
        "id": "py17_sum_up_to_n",
        "spec": "def sum_up_to_n(n: int) -> int: use a loop to sum the integers from zero through n; return zero when n is negative",
        "code": "def sum_up_to_n(n):\n    total = 0\n    for value in range(n + 1):\n        total += value\n    return total",
        "tests": "assert sum_up_to_n(0) == 0\nassert sum_up_to_n(5) == 15\nassert sum_up_to_n(-2) == 0",
    },
    {
        "id": "py17_count_ascii_vowels",
        "spec": "def count_ascii_vowels(text: str) -> int: count ASCII vowels in either case",
        "code": "def count_ascii_vowels(text):\n    vowels = 'aeiouAEIOU'\n    count = 0\n    for character in text:\n        if character in vowels:\n            count += 1\n    return count",
        "tests": "assert count_ascii_vowels('Viv AI') == 3\nassert count_ascii_vowels('rhythm') == 0\nassert count_ascii_vowels('') == 0",
    },
    {
        "id": "py17_running_maximums",
        "spec": "def running_maximums(values: list[int]) -> list[int]: return the maximum seen at each position; empty input returns an empty list",
        "code": "def running_maximums(values):\n    result = []\n    maximum = None\n    for value in values:\n        if maximum is None or value > maximum:\n            maximum = value\n        result.append(maximum)\n    return result",
        "tests": "assert running_maximums([2, 1, 5, 3]) == [2, 2, 5, 5]\nassert running_maximums([-4, -7]) == [-4, -4]\nassert running_maximums([]) == []",
    },
    {
        "id": "py17_flatten_rows",
        "spec": "def flatten_rows(rows: list[list[int]]) -> list[int]: use nested loops to concatenate rows in order",
        "code": "def flatten_rows(rows):\n    result = []\n    for row in rows:\n        for value in row:\n            result.append(value)\n    return result",
        "tests": "assert flatten_rows([[1, 2], [], [3]]) == [1, 2, 3]\nassert flatten_rows([]) == []\nassert flatten_rows([[]]) == []",
    },
    {
        "id": "py17_recursive_sum",
        "spec": "def recursive_sum(values: list[int]) -> int: sum a list recursively; the empty list sums to zero",
        "code": "def recursive_sum(values):\n    if not values:\n        return 0\n    return values[0] + recursive_sum(values[1:])",
        "tests": "assert recursive_sum([2, -1, 5]) == 6\nassert recursive_sum([7]) == 7\nassert recursive_sum([]) == 0",
    },
    {
        "id": "py17_recursive_factorial",
        "spec": "def recursive_factorial(n: int) -> int: compute factorial recursively; raise ValueError for negative input and return one for zero",
        "code": "def recursive_factorial(n):\n    if n < 0:\n        raise ValueError('negative input')\n    if n < 2:\n        return 1\n    return n * recursive_factorial(n - 1)",
        "tests": "assert recursive_factorial(0) == 1\nassert recursive_factorial(1) == 1\nassert recursive_factorial(5) == 120\ntry:\n    recursive_factorial(-1)\n    raise AssertionError()\nexcept ValueError:\n    pass",
    },
    {
        "id": "py17_recursive_gcd",
        "spec": "def recursive_gcd(a: int, b: int) -> int: return the nonnegative greatest common divisor using recursion",
        "code": "def recursive_gcd(a, b):\n    if b == 0:\n        return abs(a)\n    return recursive_gcd(b, a % b)",
        "tests": "assert recursive_gcd(54, 24) == 6\nassert recursive_gcd(-21, 14) == 7\nassert recursive_gcd(0, 0) == 0",
    },
    {
        "id": "py17_recursive_digit_sum",
        "spec": "def recursive_digit_sum(value: int) -> int: sum the decimal digits of the absolute value recursively",
        "code": "def recursive_digit_sum(value):\n    value = abs(value)\n    if value < 10:\n        return value\n    return value % 10 + recursive_digit_sum(value // 10)",
        "tests": "assert recursive_digit_sum(0) == 0\nassert recursive_digit_sum(-502) == 7\nassert recursive_digit_sum(12345) == 15",
    },
    {
        "id": "py17_all_adjacent_increasing",
        "spec": "def all_adjacent_increasing(values: list[int]) -> bool: true only when every value is greater than the previous one",
        "code": "def all_adjacent_increasing(values):\n    for index in range(1, len(values)):\n        if values[index] <= values[index - 1]:\n            return False\n    return True",
        "tests": "assert all_adjacent_increasing([1, 3, 8])\nassert not all_adjacent_increasing([1, 1])\nassert not all_adjacent_increasing([3, 2])\nassert all_adjacent_increasing([])",
    },
    {
        "id": "py17_sum_even_squares",
        "spec": "def sum_even_squares(values: list[int]) -> int: use a loop to square and sum only even integers",
        "code": "def sum_even_squares(values):\n    total = 0\n    for value in values:\n        if value % 2 == 0:\n            total += value * value\n    return total",
        "tests": "assert sum_even_squares([1, 2, -4, 3]) == 20\nassert sum_even_squares([]) == 0\nassert sum_even_squares([1, 3]) == 0",
    },
]

# Candidate-only edge-composition probe. These signatures define a deterministic
# type-compatible edge set; the isolated RNN ranks choices within that set.
EDGE_COMPOSITION = {
    "primitives": {
        "increment": {"input": "int", "output": "int", "code": "def increment(value):\n    return value + 1"},
        "double": {"input": "int", "output": "int", "code": "def double(value):\n    return value * 2"},
        "square": {"input": "int", "output": "int", "code": "def square(value):\n    return value * value"},
        "is_even": {"input": "int", "output": "bool", "code": "def is_even(value):\n    return value % 2 == 0"},
        "bool_label": {"input": "bool", "output": "str", "code": "def bool_label(value):\n    return 'yes' if value else 'no'"},
    },
    "training": {
        "id": "edge_train_increment_double_even_label",
        "route": ["increment", "double", "is_even", "bool_label"],
        "tests": "assert compose_train(0) == 'yes'\nassert compose_train(1) == 'yes'\nassert compose_train(-3) == 'yes'",
    },
    "held_out": {
        "id": "edge_holdout_increment_square_even_label",
        "route": ["increment", "square", "is_even", "bool_label"],
        "tests": "assert compose_candidate(0) == 'no'\nassert compose_candidate(1) == 'yes'\nassert compose_candidate(2) == 'no'\nassert compose_candidate(3) == 'yes'\nassert compose_candidate(-1) == 'yes'\nassert compose_candidate(-2) == 'no'",
    },
    "candidate_edges": ["increment", "double", "square"],
}


if __name__ == "__main__":
    namespace = {}
    for item in CURRICULUM:
        exec(item["code"], namespace)
        exec(item["tests"], namespace)
    print(f"CURRICULUM_PASS={len(CURRICULUM)}")
    print("EDGE_COMPOSITION_CASES=2")
