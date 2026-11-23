def normalize_words(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value.strip()]


def _verify() -> None:
    assert normalize_words([" Apple ", "", "BANANA", "  "]) == ["apple", "banana"]
    assert normalize_words([]) == []


if __name__ == "__main__":
    _verify()
    print("PASS: normalize_words trims, lowercases, and skips blanks")
