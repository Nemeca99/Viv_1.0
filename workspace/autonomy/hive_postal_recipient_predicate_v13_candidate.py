def is_valid_drone_recipient(value):
    if not isinstance(value, str) or value.strip() == "" or value.strip().casefold() == "queen":
        return False
    return True

if __name__ == "__main__":
    import sys
    
    test_cases = [
        ("drone_2", True),
        ("queen", False),
        (" QUEEN", False),
        (None, False),
        (123, False)
    ]
    
    passed = 0
    for value, expected in test_cases:
        result = is_valid_drone_recipient(value)
        if result == expected:
            print(f"PASS: {value!r}")
            passed += 1
        else:
            print(f"FAIL: {value!r} -> got {result}, expected {expected}")
            sys.exit(1)
    
    print(f"PASS: {len(test_cases)} checks")
