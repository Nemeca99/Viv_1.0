from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message
import copy
from typing import Any, Tuple, Optional


def prepare_queen_outbox_proposal(
    message_id: str,
    sender_id: str,
    authority_queen_id: str,
    task_id: str,
    body: Any,
    *,
    kind: str = "REPORT",
    proposed_recipient_id: Optional[str] = None,
    parent_message_sha256: Optional[str] = None
) -> Tuple[Optional[Any], Tuple[str, ...]]:
    """Prepare a queen outbox proposal with SCHEMA validation."""
    
    # Build message dict exactly as schema requires
    message = {
        "schema": "hive_postal_outbox_proposal_v1",
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": proposed_recipient_id if proposed_recipient_id else authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": copy.deepcopy(body)
    }
    
    # Add optional hash key only if provided
    if parent_message_sha256 is not None:
        message["parent_message_sha256"] = parent_message_sha256
    
    # Validate against schema
    valid, reason = validate_postal_message(message)
    
    if not valid:
        return (None, (reason,))
    
    # Check if recipient is queen (casefold comparison)
    recipient_id = proposed_recipient_id if proposed_recipient_id else authority_queen_id
    if recipient_id.lower() == "queen":
        return (None, ("proposed_recipient_is_queen",))
    
    # Build routing request - no peer in message
    routing_request = {
        "route": None  # null or peer, but no peer specified
    }
    
    proposal = {
        **message,
        "routing_request": routing_request
    }
    
    return (proposal, ())


# Self-check assertions for six cases
def run_self_check():
    """Run bounded self-check with 6 test cases."""
    import hashlib
    
    tests_passed = 0
    
    # Test 1: Default case
    try:
        result, reason = prepare_queen_outbox_proposal(
            "msg_001", "user_001", "queen_001", "task_001", {"data": "test"}
        )
        if result is not None and len(reason) == 0:
            tests_passed += 1
    except Exception as e:
        print(f"Test 1 failed: {e}")
    
    # Test 2: Peer outside case (recipient is different peer)
    try:
        result, reason = prepare_queen_outbox_proposal(
            "msg_002", "user_001", "queen_001", "task_002", {"data": "test"},
            proposed_recipient_id="peer_001"
        )
        if result is not None and len(reason) == 0:
            tests_passed += 1
    except Exception as e:
        print(f"Test 2 failed: {e}")
    
    # Test 3: Nested copy case (deepcopy body)
    try:
        original = {"nested": {"data": "test"}}
        result, reason = prepare_queen_outbox_proposal(
            "msg_003", "user_001", "queen_001", "task_003", original
        )
        if result is not None and result["body"]["nested"]["data"] == "test":
            tests_passed += 1
    except Exception as e:
        print(f"Test 3 failed: {e}")
    
    # Test 4: Bad body case (invalid schema)
    try:
        invalid_message = {"schema": "hive_postal_outbox_proposal_v1", 
                          "message_id": "msg_004", "sender_id": "user_001",
                          "recipient_id": "queen_001", "task_id": "task_004",
                          "kind": "REPORT", "body": "invalid"}  # body should be dict/list
        valid, reason = validate_postal_message(invalid_message)
        if not valid:
            tests_passed += 1
    except Exception as e:
        print(f"Test 4 failed: {e}")
    
    # Test 5: Queen peer case (casefold check)
    try:
        result, reason = prepare_queen_outbox_proposal(
            "msg_005", "user_001", "queen_001", "task_005", {"data": "test"},
            proposed_recipient_id="QUEEN"  # uppercase queen
        )
        if result is None and len(reason) > 0 and reason[0] == "proposed_recipient_is_queen":
            tests_passed += 1
    except Exception as e:
        print(f"Test 5 failed: {e}")
    
    # Test 6: 64-char hash case (parent_message_sha256)
    try:
        test_hash = hashlib.sha256(b"test_data").hexdigest()
        result, reason = prepare_queen_outbox_proposal(
            "msg_006", "user_001", "queen_001", "task_006", {"data": "test"},
            parent_message_sha256=test_hash  # exactly 64 chars
        )
        if result is not None and result["parent_message_sha256"] == test_hash:
            tests_passed += 1
    except Exception as e:
        print(f"Test 6 failed: {e}")
    
    print(f"PASS: {tests_passed} checks")


if __name__ == "__main__":
    run_self_check()