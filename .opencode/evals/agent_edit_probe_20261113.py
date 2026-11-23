def count_nonempty(values: list[str]) -> int:
    return sum(1 for value in values if value.strip())


def _verify() -> None:
    assert count_nonempty([]) == 0
    assert count_nonempty(["a", " ", "bc", "\t"]) == 2
    assert count_nonempty(["  x  ", "\n"]) == 1


if __name__ == "__main__":
    _verify()
    print("PASS: count_nonempty ignores whitespace-only strings")
