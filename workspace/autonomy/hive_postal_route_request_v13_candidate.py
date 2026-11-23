def prepare_routing_request(value):
    """Propose a routing request. None means no proposed route."""
    # Check for None - no proposed route
    if value is None:
        return (None, ("no_proposed_route",))
    
    # Must be a string first
    if not isinstance(value, str):
        return (None, ("invalid_type_not_string",))
    
    # Accept only non-empty strings with no surrounding whitespace
    s = value  # Preserve exact input - do NOT strip
    
    if not s:
        return (None, ("empty_string",))
    
    # Check for leading/trailing whitespace without stripping
    if s != s.strip():
        return (None, ("surrounding_whitespace_detected",))
    
    # Queen case-insensitive check
    if s.casefold() == "queen":
        return (None, ("recipient_is_queen",))
    
    # Must be a valid 64-character lowercase hex ID for drone IDs
    try:
        int(s, 16)
        if len(s) != 64 or not all(c in '0123456789abcdef' for c in s):
            return (None, ("invalid_hex_format",))
    except ValueError:
        return (None, ("not_valid_hex",))
    
    # Valid drone ID - accept and preserve exact string
    return ({"recipient_id": value}, ())


def self_check():
    """Run exactly eight self-check cases."""
    test_cases = [
        None,  # Case 1: None means no proposed route
        "drone_001",  # Case 2: Valid drone ID (64-char lowercase hex)
        "a" * 64 + "b" * 58,  # Case 3: Valid 64-character lowercase hex ID
        "queen",  # Case 4: Queen case-insensitive
        "QUEEN",  # Case 5: Queen uppercase
        "  queen  ",  # Case 6: Leading whitespace (should fail)
        "",  # Case 7: Empty string
        123,  # Case 8: Non-string integer
    ]
    
    results = []
    for i, test in enumerate(test_cases):
        result = prepare_routing_request(test)
        is_valid = result[0] is not None and isinstance(result[0], dict)
        status = "PASS" if is_valid else "FAIL"
        results.append((i+1, status))
    
    # Print only PASS: 8 checks on success (all must pass)
    all_passed = all(r[1] == "PASS" for r in results)
    if all_passed:
        print("PASS: 8 checks")
    else:
        print(f"FAIL: {results}")


if __name__ == "__main__":
    import sys
    
    # Check for --self-check flag
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        self_check()
    else:
        # Default behavior - prepare routing request
        value = None
        result = prepare_routing_request(value)
        print(f"Result: {result}")
