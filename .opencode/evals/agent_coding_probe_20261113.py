def sum_even(values: list[int]) -> int:
    return sum(value for value in values if value % 2 == 0)


def _verify() -> None:
    assert sum_even([]) == 0
    assert sum_even([1, 2, 3, 4]) == 6
    assert sum_even([-6, -3, 0, 5, 8]) == 2


if __name__ == "__main__":
    _verify()
    print("PASS: sum_even handles empty, mixed, negative, and zero values")
