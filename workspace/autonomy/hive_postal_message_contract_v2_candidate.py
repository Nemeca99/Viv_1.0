import argparse
import re
import sys


REQUIRED_KEYS = {"sender_id", "task_id", "parent_message_sha256"}
ALLOWED_KEYS = REQUIRED_KEYS | {"body", "kind"}
VALID_KINDS = {"REPORT", "REQUEST", "ACKNOWLEDGE"}

SCHEMA = {
    "required": REQUIRED_KEYS,
    "allowed": ALLOWED_KEYS,
    "valid_kind": VALID_KINDS,
}


def validate_postal_message(message):
    """Validate postal message structure and return (True, 'accepted') or (False, error_code)."""
    if not isinstance(message, dict):
        return False, "ERR_NON_DICT"

    # Type validation before string methods
    for key in REQUIRED_KEYS:
        if key not in message:
            return False, f"ERR_MISSING_{key.upper()}"

    sender_id = message.get("sender_id")
    task_id = message.get("task_id")
    parent_message_sha256 = message.get("parent_message_sha256")
    kind = message.get("kind", "")

    # Trim before string methods
    if not isinstance(sender_id, str):
        return False, "ERR_SENDER_ID_TYPE"
    sender_id = sender_id.strip()

    if not task_id:
        return False, "ERR_TASK_ID_EMPTY"

    # Validate kind exactly as listed
    if kind not in VALID_KINDS:
        return False, f"ERR_INVALID_KIND_{kind}"

    # Validate parent_message_sha256: lowercase-hex full match of 64 characters
    if not isinstance(parent_message_sha256, str):
        return False, "ERR_PARENT_HASH_TYPE"
    
    parent_hash = parent_message_sha256.strip()
    hex_pattern = re.compile(r'^[0-9a-f]{64}$')
    
    if not hex_pattern.match(parent_hash.lower()):
        return False, "ERR_MALFORMED_PARENT_HASH"

    return True, "accepted"


def main():
    parser = argparse.ArgumentParser(description="Postal message validator")
    parser.add_argument("--self-check", action="store_true", help="Run self-check mode")
    args = parser.parse_args()

    if args.self_check:
        # Self-check table of nine cases
        test_cases = [
            ({"sender_id": "test", "task_id": "123", "parent_message_sha256": "a" * 64}, True),
            ("not a dict", False),
            ({}, False),
            ({"sender_id": "", "task_id": "123", "parent_message_sha256": "a" * 64}, False),
            ({"sender_id": "test", "task_id": "123", "parent_message_sha256": "A" * 64, "kind": "REPORT"}, True),
            ({"sender_id": "test", "task_id": "123", "parent_message_sha256": "a" * 64}, False),
            ({"sender_id": "test", "task_id": "123", "parent_message_sha256": "invalid"}, False),
            ({"sender_id": "test", "task_id": "123", "parent_message_sha256": "a" * 64, "kind": "REPORT"}, True),
            ({"sender_id": "test", "task_id": "123", "parent_message_sha256": "a" * 64, "body": "hello", "kind": "REQUEST"}, True),
        ]

        all_passed = True
        for i, (msg, expected) in enumerate(test_cases):
            result = validate_postal_message(msg)
            actual = result[0] == expected
            
            if not actual:
                print(f"Case {i+1}: FAILED - expected {expected}, got {result}")
                all_passed = False

        if all_passed:
            print("PASS: postal envelope checks")
            sys.exit(0)
        else:
            sys.exit(1)
    else:
        # Normal validation mode
        message = None
        try:
            message = sys.stdin.read()
        except Exception:
            pass

        if not isinstance(message, str):
            print("ERR_INPUT_TYPE")
            sys.exit(1)

        result = validate_postal_message(message)
        if result[0]:
            print(result[1])
            sys.exit(0)
        else:
            print(result[1])
            sys.exit(1)


if __name__ == "__main__":
    main()