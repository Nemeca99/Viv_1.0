def count_nonempty_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _verify() -> None:
    assert count_nonempty_lines("alpha\n\n beta \n") == 2


if __name__ == "__main__":
    _verify()
    print("PASS: count_nonempty_lines")
