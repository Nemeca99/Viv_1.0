def is_valid_drone_recipient(value):
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    return value.casefold() != "queen"


if __name__ == "__main__":
    cases = [("drone_2", True), ("queen", False), ("QUEEN", False), (" QUEEN", False), (" drone_2 ", False), ("", False), (None, False), (123, False)]
    if all(is_valid_drone_recipient(value) == expected for value, expected in cases):
        print("PASS: 8 checks")
    else:
        print("FAIL")
        exit(1)
