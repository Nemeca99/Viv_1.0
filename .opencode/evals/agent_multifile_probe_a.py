def normalize_label(value: str) -> str:
    return value.strip().lower()


def _verify() -> None:
    assert normalize_label("  LOCAL CODER  ") == "local coder"


if __name__ == "__main__":
    _verify()
    print("PASS: normalize_label")
