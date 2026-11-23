from __future__ import annotations

import argparse
import re
import sys

SCHEMA = "hive_postal_message_v1"
REQUIRED_KEYS = frozenset({
    "schema", "message_id", "sender_id", "recipient_id", "task_id", "kind", "body",
})
ALLOWED_KEYS = REQUIRED_KEYS | {"parent_message_sha256"}
VALID_KINDS = frozenset({"REPORT", "SELF_PROMPT", "ROUTED_REPORT", "ACK", "STOP"})


def validate_postal_message(message: object) -> tuple[bool, str]:
    """Validate only the postal envelope shape; this does not authorize routing."""
    if not isinstance(message, dict):
        return False, "message_not_object"
    missing = REQUIRED_KEYS - message.keys()
    if missing:
        return False, "missing_required_field"
    if message.keys() - ALLOWED_KEYS:
        return False, "unknown_field"
    if message["schema"] != SCHEMA:
        return False, "invalid_schema"
    for field in ("message_id", "sender_id", "recipient_id", "task_id", "kind"):
        value = message[field]
        if not isinstance(value, str) or not value or value != value.strip():
            return False, f"invalid_{field}"
    if message["kind"] not in VALID_KINDS:
        return False, "invalid_kind"
    if not isinstance(message["body"], dict):
        return False, "invalid_body"
    if "parent_message_sha256" in message:
        parent = message["parent_message_sha256"]
        if not isinstance(parent, str) or re.fullmatch(r"[0-9a-f]{64}", parent) is None:
            return False, "invalid_parent_hash"
    return True, "accepted"


def _self_check() -> int:
    valid = {
        "schema": SCHEMA,
        "message_id": "msg_001",
        "sender_id": "drone_1",
        "recipient_id": "queen",
        "task_id": "task_1",
        "kind": "REPORT",
        "body": {"status": "complete"},
    }
    cases = [
        (valid, True),
        ("not an object", False),
        ({key: value for key, value in valid.items() if key != "task_id"}, False),
        ({**valid, "sender_id": " "}, False),
        ({**valid, "kind": "UNKNOWN"}, False),
        ({**valid, "body": []}, False),
        ({**valid, "unexpected": True}, False),
        ({**valid, "parent_message_sha256": "bad"}, False),
        ({**valid, "parent_message_sha256": "a" * 64}, True),
    ]
    for index, (message, expected) in enumerate(cases, start=1):
        actual, _ = validate_postal_message(message)
        if actual is not expected:
            print(f"Case {index}: expected {expected}, got {actual}")
            return 1
    print("PASS: postal envelope checks")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Postal envelope candidate validator")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if not args.self_check:
        parser.error("--self-check is required")
    return _self_check()


if __name__ == "__main__":
    raise SystemExit(main())