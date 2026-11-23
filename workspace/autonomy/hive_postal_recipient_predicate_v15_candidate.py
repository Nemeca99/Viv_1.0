def is_valid_drone_recipient(value):
    if not isinstance(value, str):
        return False
    s = value.strip()
    return len(s) > 0 and s.casefold() != "queen"

if __name__ == "__main__":
    cases = [
        ("drone_2", True),
        ("queen", False),
        ("QUEEN", False),
        (" QUEEN", False),
        (" drone_2 ", False),
        ("", False),
        (None, False),
        (123, False),
    ]
    
    results = []
    for value, expected in cases:
        result = is_valid_drone_recipient(value)
        results.append(result == expected)
    
    if all(results):
        print("PASS: 8 checks")
        exit(0)
    else:
        print("FAIL")
        exit(1)
