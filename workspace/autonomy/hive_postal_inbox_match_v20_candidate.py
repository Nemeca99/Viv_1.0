def message_matches_local_inbox(message, local_inbox_id):
    """Envelope matching predicate only; does not deliver, authorize, infer hardware, or access files."""
    # Check if message is a dict
    if not isinstance(message, dict):
        return False
    
    # Check if both IDs are non-empty strings without surrounding whitespace
    if not isinstance(local_inbox_id, str) or not local_inbox_id or local_inbox_id != local_inbox_id.strip():
        return False
    
    recipient_id = message.get("recipient_id")
    if not isinstance(recipient_id, str) or not recipient_id or recipient_id != recipient_id.strip():
        return False
    
    # Case-sensitive exact match
    return recipient_id == local_inbox_id


def _self_check() -> int:
    """Run self-check with exactly eight test cases."""
    test_cases = [
        ({"recipient_id":"drone_1"}, "drone_1", True),
        ({"recipient_id":"drone_2"}, "drone_1", False),
        ({"recipient_id":"Drone_1"}, "drone_1", False),
        ({}, "drone_1", False),
        ("not-a-dict", "drone_1", False),
        ({"recipient_id":"drone_1"}, "", False),
        ({"recipient_id":"drone_1"}, " drone_1 ", False),
        ({"recipient_id":" drone_1 "}, "drone_1", False),
    ]
    
    for i, (message, local_inbox_id, expected) in enumerate(test_cases, start=1):
        result = message_matches_local_inbox(message, local_inbox_id)
        if result != expected:
            print(f"Case {i}: expected {expected}, got {result}")
            return 1
    
    print("PASS: 8 checks")
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inbox match candidate validator")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    
    if not args.self_check:
        parser.error("--self-check is required")
    
    return _self_check()


if __name__ == "__main__":
    raise SystemExit(main())
