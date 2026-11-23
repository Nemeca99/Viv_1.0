import sys
from hive_postal_inbox_contract_v1_candidate import validate_message_for_local_inbox

# Schema for hive_postal_message_v1
SCHEMA = {
    "required": ["envelope", "kind"],
    "properties": {
        "envelope": {"type": "object"},
        "kind": {"type": "string"}
    }
}

VALID_KINDS = ["REPORT", "TASK", "QUERY"]

def check_self():
    """Run 8 self-check cases."""
    
    # Valid envelope with schema hive_postal_message_v1
    valid_envelope = {
        "msg_id": "msg_001/drone_1/queen/task_1",
        "sender": "drone_1",
        "recipient": "queen",
        "task_id": "task_1"
    }
    
    # Valid envelope with drone_1 as recipient (not queen)
    valid_envelope_drone = {
        "msg_id": "msg_001/drone_1/queen/task_1",
        "sender": "drone_1",
        "recipient": "drone_1",
        "task_id": "task_1"
    }
    
    # String instead of object
    string_message = "hello world"
    
    # Envelope missing task_id
    envelope_missing_task = {
        "msg_id": "msg_001/drone_1/queen/task_1",
        "sender": "drone_1",
        "recipient": "queen"
    }
    
    # Padded recipient " queen" (with leading space)
    padded_recipient = " queen"
    
    # Kind UNKNOWN instead of REPORT/TASK/QUERY
    unknown_kind_envelope = {
        "msg_id": "msg_001/drone_1/queen/task_1",
        "sender": "drone_1",
        "recipient": "queen",
        "kind": "UNKNOWN"
    }
    
    # List instead of dict body
    list_body = ["item1", "item2"]
    
    # Valid envelope but padded local ID " queen"
    valid_envelope_padded_local = {
        "msg_id": "msg_001/drone_1/queen/task_1",
        "sender": "drone_1",
        "recipient": "queen",
        "task_id": "task_1"
    }
    
    # Test cases: (message, local_inbox_id, expected_full_tuple)
    test_cases = [
        # Case 0: valid envelope/queen -> (True, "accepted_for_local_inbox")
        (valid_envelope, "queen", (True, "accepted_for_local_inbox")),
        
        # Case 1: same envelope/drone_1 -> (False, "not_for_local_inbox")
        (valid_envelope_drone, "drone_1", (False, "not_for_local_inbox")),
        
        # Case 2: string/queen -> (False, "message_not_object")
        (string_message, "queen", (False, "message_not_object")),
        
        # Case 3: envelope missing task_id/queen -> (False, "missing_required_field")
        (envelope_missing_task, "queen", (False, "missing_required_field")),
        
        # Case 4: padded recipient " queen"/queen -> (False, "invalid_recipient_id")
        (valid_envelope, padded_recipient, (False, "invalid_recipient_id")),
        
        # Case 5: kind UNKNOWN/queen -> (False, "invalid_kind")
        (unknown_kind_envelope, "queen", (False, "invalid_kind")),
        
        # Case 6: list body/queen -> (False, "invalid_body")
        (list_body, "queen", (False, "invalid_body")),
        
        # Case 7: valid envelope/padded local ID " queen" -> (False, "not_for_local_inbox")
        (valid_envelope_padded_local, padded_recipient, (False, "not_for_local_inbox")),
    ]
    
    failed_cases = []
    
    for i, (message, local_inbox_id, expected) in enumerate(test_cases):
        try:
            result = validate_message_for_local_inbox(message, local_inbox_id)
            actual = result
            
            if actual != expected:
                print(f"Case {i}: MISMATCH")
                print(f"  Expected: {expected}")
                print(f"  Actual:   {actual}")
                failed_cases.append(i)
        except Exception as e:
            print(f"Case {i}: EXCEPTION - {e}")
            failed_cases.append(i)
    
    if failed_cases:
        print(f"\nFAILED: {len(failed_cases)} case(s) mismatched")
        for i in failed_cases:
            print(f"  Case {i}")
        sys.exit(1)
    else:
        print("PASS: 8 checks")
        sys.exit(0)

if __name__ == "__main__":
    args = sys.argv[1:]
    
    if len(args) > 0 and args[0] == "--self-check":
        check_self()
    else:
        print("Usage: python hive_postal_inbox_contract_v3_check_candidate.py --self-check")
        sys.exit(1)
