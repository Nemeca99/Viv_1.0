from hive_postal_message_contract_queen_v3_candidate import validate_postal_message
from hive_postal_inbox_match_v20_candidate import message_matches_local_inbox


def validate_message_for_local_inbox(message, local_inbox_id):
    """Compose envelope validator and inbox match; do not duplicate logic."""
    # First validate the postal envelope shape
    is_valid, reason = validate_postal_message(message)
    
    if not is_valid:
        return False, reason
    
    # Then check inbox matching (case-sensitive exact match only)
    if message_matches_local_inbox(message, local_inbox_id):
        return True, "accepted_for_local_inbox"
    else:
        return False, "not_for_local_inbox"


def _self_check() -> int:
    """Run self-check with exactly eight test cases."""
    valid_envelope = {
        "schema": "hive_postal_message_v1",
        "message_id": "msg_001",
        "sender_id": "drone_1",
        "recipient_id": "queen",
        "task_id": "task_1",
        "kind": "REPORT",
        "body": {"status": "complete"},
    }
    
    cases = [
        # Case 1: matching valid envelope => accepted
        (valid_envelope, "queen", True),
        
        # Case 2: valid envelope for another ID => not_for_local_inbox
        (valid_envelope, "drone_1", False),
        
        # Case 3: string => message_not_object
        ("not an object", "queen", False),
        
        # Case 4: missing task_id => missing_required_field
        ({key: value for key, value in valid_envelope.items() if key != "task_id"}, "queen", False),
        
        # Case 5: padded recipient => invalid_recipient_id (envelope fails)
        ({**valid_envelope, "recipient_id": " queen"}, "queen", False),
        
        # Case 6: kind UNKNOWN => invalid_kind (envelope fails)
        ({**valid_envelope, "kind": "UNKNOWN"}, "queen", False),
        
        # Case 7: list body => invalid_body (envelope fails)
        ({**valid_envelope, "body": []}, "queen", False),
        
        # Case 8: matching envelope with padded local ID => not_for_local_inbox
        (valid_envelope, " queen", False),
    ]
    
    for index, (message, local_inbox_id, expected) in enumerate(cases, start=1):
        actual, reason = validate_message_for_local_inbox(message, local_inbox_id)
        
        # Check both result and reason match
        if actual is not expected:
            print(f"Case {index}: expected {expected}, got {actual} (reason: {reason})")
            return 1
        
        # Verify reason matches too
        if reason != "accepted_for_local_inbox":
            print(f"Case {index}: expected reason 'accepted_for_local_inbox', got '{reason}'")
            return 1
    
    print("PASS: 8 checks")
    return 0


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Inbox contract candidate validator")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    
    if not args.self_check:
        parser.error("--self-check is required")
    
    return _self_check()


if __name__ == "__main__":
    raise SystemExit(main())
