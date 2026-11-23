#!/usr/bin/env python3
"""Hive Postal Inbox Contract v4 Checker - Self-Test Suite."""

import sys
from hive_postal_inbox_contract_v1_candidate import validate_message_for_local_inbox


def run_self_checks():
    """Run all 8 self-check cases and report results."""
    test_cases = [
        # Case 0: base message/queen -> (True, "accepted_for_local_inbox")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "queen",
            "task_id": "task_1",
            "kind": "REPORT",
            "body": {"status": "complete"}
        }, "local_inbox_001", (True, "accepted_for_local_inbox")),

        # Case 1: base message with recipient_id changed to drone_1/local queen -> (False, "not_for_local_inbox")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "drone_1",
            "task_id": "task_1",
            "kind": "REPORT",
            "body": {"status": "complete"}
        }, "local_inbox_002", (False, "not_for_local_inbox")),

        # Case 2: string/local queen -> (False, "message_not_object")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "queen",
            "task_id": "task_1",
            "kind": "REPORT",
            "body": [{"status": "complete"}]  # body is list, not dict
        }, "local_inbox_003", (False, "message_not_object")),

        # Case 3: base message with task_id removed/local queen -> (False, "missing_required_field")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "queen",
            # task_id removed
            "kind": "REPORT",
            "body": {"status": "complete"}
        }, "local_inbox_004", (False, "missing_required_field")),

        # Case 4: base message with recipient_id changed to " queen"/local queen -> (False, "invalid_recipient_id")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": " queen",  # leading space
            "task_id": "task_1",
            "kind": "REPORT",
            "body": {"status": "complete"}
        }, "local_inbox_005", (False, "invalid_recipient_id")),

        # Case 5: base message with kind changed to UNKNOWN/local queen -> (False, "invalid_kind")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "queen",
            "task_id": "task_1",
            "kind": "UNKNOWN",  # changed from REPORT
            "body": {"status": "complete"}
        }, "local_inbox_006", (False, "invalid_kind")),

        # Case 6: base message with body changed to []/local queen -> (False, "invalid_body")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "queen",
            "task_id": "task_1",
            "kind": "REPORT",
            "body": []  # changed from {"status": "complete"}
        }, "local_inbox_007", (False, "invalid_body")),

        # Case 7: base message/local ID changed to " queen" -> (False, "not_for_local_inbox")
        ({
            "schema": "hive_postal_message_v1",
            "message_id": "msg_001",
            "sender_id": "drone_1",
            "recipient_id": "queen",
            "task_id": "task_1",
            "kind": "REPORT",
            "body": {"status": "complete"}
        }, " local_inbox_008", (False, "not_for_local_inbox")),  # leading space in ID
    ]

    passed = 0
    failed = 0

    for i, (message, inbox_id, expected) in enumerate(test_cases):
        result = validate_message_for_local_inbox(message, inbox_id)
        
        if result == expected:
            print(f"Case {i+1}: PASS")
            passed += 1
        else:
            print(f"Case {i+1}: FAIL")
            print(f"  Message: {message}")
            print(f"  Inbox ID: {inbox_id}")
            print(f"  Expected: {expected}")
            print(f"  Actual:   {result}")
            failed += 1

    total = passed + failed
    if passed == 8 and failed == 0:
        print("PASS: 8 checks")
        sys.exit(0)
    else:
        print(f"FAIL: {passed}/{total} checks passed")
        sys.exit(1)


if __name__ == "__main__":
    args = sys.argv[1:]
    
    if len(args) > 0 and args[0] == "--self-check":
        run_self_checks()
    else:
        print("Usage: python hive_postal_inbox_contract_v4_check_candidate.py --self-check")
        sys.exit(1)
