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
        (valid_envelope, "queen"),
        (valid_envelope, "drone_1"),
        ("not an object", "queen"),
        ({k: v for k, v in valid_envelope.items() if k != "task_id"}, "queen"),
        ({**valid_envelope, "recipient_id": " queen"}, "queen"),
        ({**valid_envelope, "kind": "UNKNOWN"}, "queen"),
        ({**valid_envelope, "body": []}, "queen"),
        (valid_envelope, " queen"),
    ]

    for index, (message, local_inbox_id) in enumerate(cases, start=1):
        actual = validate_message_for_local_inbox(message, local_inbox_id)
        expected_tuple = EXPECTED_RESULTS[index - 1][1]

        if actual != expected_tuple:
            print(f"Case {index}: expected {expected_tuple}, got {actual}")
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