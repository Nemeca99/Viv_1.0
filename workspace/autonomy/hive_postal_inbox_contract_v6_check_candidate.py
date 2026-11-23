from hive_postal_inbox_contract_v1_candidate import validate_message_for_local_inbox


EXPECTED_RESULTS = [
    ("valid/queen", (True, "accepted_for_local_inbox")),
    ("valid/drone_1", (False, "not_for_local_inbox")),
    ("string/queen", (False, "message_not_object")),
    ("missing task_id/queen", (False, "missing_required_field")),
    ("padded recipient/queen", (False, "invalid_recipient_id")),
    ("unknown kind/queen", (False, "invalid_kind")),
    ("list body/queen", (False, "invalid_body")),
    ("valid/padded local ID", (False, "not_for_local_inbox")),
]


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
        (valid_envelope, "queen"),
        
        # Case 2: valid envelope for another ID => not_for_local_inbox
        (valid_envelope, "drone_1"),
        
        # Case 3: string => message_not_object
        ("not an object", "queen"),
        
        # Case 4: missing task_id => missing_required_field
        ({k: v for k, v in valid_envelope.items() if k != "task_id"}, "queen"),
        
        # Case 5: padded recipient => invalid_recipient_id (envelope fails)
        ({**valid_envelope, "recipient_id": " queen"}, "queen"),
        
        # Case 6: kind UNKNOWN => invalid_kind (envelope fails)
        ({**valid_envelope, "kind": "UNKNOWN"}, "queen"),
        
        # Case 7: list body => invalid_body (envelope fails)
        ({**valid_envelope, "body": []}, "queen"),
        
        # Case 8: matching envelope with padded local ID => not_for_local_inbox
        (valid_envelope, " queen"),
    ]

    passed = 0
    for index, (message, local_inbox_id) in enumerate(cases, start=1):
        actual, reason = validate_message_for_local_inbox(message, local_inbox_id)
        expected = EXPECTED_RESULTS[index - 1][1]

        if actual is not expected or reason != expected[1]:
            print(f"Case {index}: expected {expected}, got ({actual}, {reason})")
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