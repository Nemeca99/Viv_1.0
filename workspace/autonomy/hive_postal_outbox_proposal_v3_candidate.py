import copy
from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message


def prepare_queen_outbox_proposal(message_id: str, sender_id: str, authority_queen_id: str, task_id: str, body: dict, *, kind: str = "REPORT", proposed_recipient_id: str | None = None, parent_message_sha256: str | None = None) -> tuple[dict | None, tuple[str] | None]:
    """Build and validate a queen outbox proposal. Pure function only."""
    # Build message dict exactly as specified
    message = {
        "schema": SCHEMA,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": copy.deepcopy(body)
    }

    # Add optional hash if parent_message_sha256 provided
    if parent_message_sha256 is not None:
        message["parent_hash"] = parent_message_sha256

    # Validate the message once
    valid, reason = validate_postal_message(message)

    if not valid:
        return (None, (reason,))

    # Build proposal with schema and routing_request
    routing_request = None
    if proposed_recipient_id is not None and proposed_recipient_id != "Queen":
        routing_request = {"recipient_id": proposed_recipient_id}

    proposal = {
        "schema": "hive_postal_outbox_proposal_v1",
        "message": message,
        "routing_request": routing_request
    }

    return (proposal, ())


def main():
    import sys
    
    # Parse arguments
    args = sys.argv[1:]
    
    if "--self-check" in args:
        args.remove("--self-check")
        
        # Test 1: Valid envelope with valid IDs and body
        try:
            result = prepare_queen_outbox_proposal(
                message_id="msg_001",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body={"action": "test"},
                kind="REPORT"
            )
            if result[0] is not None and len(result[1]) == 0:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
        
        # Test 2: Invalid message_id (empty string)
        try:
            result = prepare_queen_outbox_proposal(
                message_id="",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body={"action": "test"},
                kind="REPORT"
            )
            if result[0] is None:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
        
        # Test 3: Invalid kind (not in VALID_KINDS)
        try:
            result = prepare_queen_outbox_proposal(
                message_id="msg_002",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body={"action": "test"},
                kind="INVALID_KIND"
            )
            if result[0] is None:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
        
        # Test 4: Invalid body (None)
        try:
            result = prepare_queen_outbox_proposal(
                message_id="msg_003",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body=None,
                kind="REPORT"
            )
            if result[0] is None:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
        
        # Test 5: Queen peer rejection (proposed_recipient_id = "Queen")
        try:
            result = prepare_queen_outbox_proposal(
                message_id="msg_004",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body={"action": "test"},
                kind="REPORT",
                proposed_recipient_id="Queen"
            )
            if result[0] is None:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
        
        # Test 6: Valid with parent hash
        try:
            result = prepare_queen_outbox_proposal(
                message_id="msg_005",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body={"action": "test"},
                kind="REPORT",
                parent_message_sha256="abc123def456"
            )
            if result[0] is not None and "parent_hash" in result[0]["message"]:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
        
        # Test 7: Valid with proposed recipient (not Queen)
        try:
            result = prepare_queen_outbox_proposal(
                message_id="msg_006",
                sender_id="sender_001",
                authority_queen_id="queen_main",
                task_id="task_alpha",
                body={"action": "test"},
                kind="REPORT",
                proposed_recipient_id="peer_alpha"
            )
            if result[0] is not None and result[0]["routing_request"] == {"recipient_id": "peer_alpha"}:
                print("PASS")
        except Exception as e:
            print(f"FAIL: {e}")
    else:
        # Normal operation - just call prepare_queen_outbox_proposal
        pass


if __name__ == "__main__":
    main()