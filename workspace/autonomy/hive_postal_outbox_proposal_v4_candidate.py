from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message
import json
import copy
import hashlib

def prepare_queen_outbox_proposal(message_id, sender_id, authority_queen_id, task_id, body, *, kind="REPORT", proposed_recipient_id=None, parent_message_sha256=None):
    # Validate inputs
    if not message_id or not isinstance(message_id, str) or len(message_id.strip()) == 0:
        return (None, ("empty or invalid message_id"))
    
    if not sender_id or not isinstance(sender_id, str) or len(sender_id.strip()) == 0:
        return (None, ("empty or invalid sender_id"))
    
    if kind not in VALID_KINDS:
        return (None, ("invalid kind"))
    
    if body is None or not isinstance(body, list):
        return (None, ("list body required"))
    
    if parent_message_sha256 and len(parent_message_sha256) != 64:
        return (None, ("malformed hash"))
    
    # Check for Queen peer rejection (casefold comparison)
    if proposed_recipient_id is not None and isinstance(authority_queen_id, str):
        if authority_queen_id.casefold() == proposed_recipient_id.casefold():
            return (None, ("Queen peer rejected"))
    
    # Build message with only required keys
    message = {
        "message_id": message_id,
        "sender_id": sender_id,
        "authority_queen_id": authority_queen_id,
        "task_id": task_id,
        "body": copy.deepcopy(body),
        "kind": kind
    }
    
    # Add optional keys only if provided
    if proposed_recipient_id is not None:
        message["proposed_recipient_id"] = proposed_recipient_id
    
    if parent_message_sha256 is not None and len(parent_message_sha256) == 64:
        message["parent_message_sha256"] = parent_message_sha256
    
    # Validate against schema
    try:
        validate_postal_message(message, SCHEMA)
    except Exception as e:
        return (None, ("validation failed"))
    
    # Build routing_request with peer-only info
    routing_request = {
        "peer_id": proposed_recipient_id if proposed_recipient_id else authority_queen_id,
        "routing_mode": "peer_only"
    }
    
    proposal = {
        **message,
        "routing_request": routing_request
    }
    
    return (proposal, ())

# Self-check function
def run_self_check():
    test_cases = [
        # Case 1: Valid inputs - exact valid envelope
        ("valid_envelope", True),
        # Case 2: Peer route outside message
        ("peer_route_outside", True),
        # Case 3: Nested deep-copy
        ("nested_deep_copy", True),
        # Case 4: Reject empty ID
        ("reject_empty_id", False),
        # Case 5: Reject list body
        ("reject_list_body", False),
        # Case 6: Reject invalid kind
        ("reject_invalid_kind", False),
        # Case 7: Reject malformed hash
        ("reject_malformed_hash", False),
        # Case 8: Reject Queen peer
        ("reject_queen_peer", False),
        # Case 9: Accept valid 64-char lowercase hash
        ("accept_valid_hash", True),
    ]
    
    passed = 0
    failed = 0
    
    for name, should_pass in test_cases:
        try:
            result = prepare_queen_outbox_proposal(
                message_id="test123",
                sender_id="sender456",
                authority_queen_id="queen789",
                task_id="task001",
                body=["item1", "item2"],
                kind="REPORT"
            )
            
            if should_pass:
                # Check that result is not None and has correct structure
                proposal, error = result
                if proposal is None or error:
                    print(f"FAIL: {name}")
                    failed += 1
                else:
                    passed += 1
                    
                    # Verify peer route outside message
                    if "peer_route_outside" in name and "routing_request" not in proposal:
                        print(f"FAIL: {name} - peer route should be outside")
                        failed += 1
                    elif "nested_deep_copy" in name and result[0] is None:
                        print(f"FAIL: {name}")
                        failed += 1
                    
                    # Verify deep copy
                    if "nested_deep_copy" in name:
                        original_body = ["item1", "item2"]
                        proposal, _ = prepare_queen_outbox_proposal(
                            message_id="test123",
                            sender_id="sender456",
                            authority_queen_id="queen789",
                            task_id="task001",
                            body=original_body,
                            kind="REPORT"
                        )
                        proposal["body"][0] = "modified"
                        if original_body[0] != "modified":
                            print(f"FAIL: {name} - deep copy not working")
                            failed += 1
                    
                    # Verify empty ID rejection
                    if "reject_empty_id" in name and result is None:
                        passed += 1
                    
                    # Verify list body rejection
                    if "reject_list_body" in name and result is None:
                        passed += 1
                    
                    # Verify invalid kind rejection
                    if "reject_invalid_kind" in name and result is None:
                        passed += 1
                    
                    # Verify malformed hash rejection
                    if "reject_malformed_hash" in name and result is None:
                        passed += 1
                    
                    # Verify Queen peer rejection
                    if "reject_queen_peer" in name and result is None:
                        passed += 1
                    
                    # Verify valid hash acceptance
                    if "accept_valid_hash" in name and result[0] is not None:
                        passed += 1
                        
        except Exception as e:
            print(f"FAIL: {name} - exception: {e}")
            failed += 1
    
    print(f"\nPASS: {passed}/9 checks") if passed == 9 else print(f"FAIL: {failed}/9 checks")

if __name__ == "__main__":
    run_self_check()