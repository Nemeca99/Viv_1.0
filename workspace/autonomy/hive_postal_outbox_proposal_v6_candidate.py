from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message
import copy

def prepare_queen_outbox_proposal(message_id: str, sender_id: str, authority_queen_id: str, task_id: str, body: dict, *, kind: str = "REPORT", proposed_recipient_id: str | None = None, parent_message_sha256: str | None = None) -> tuple[dict | None, tuple[str] | None]:
    """Prepare a queen outbox proposal with exact schema validation."""
    
    # Build the message structure exactly as specified
    message = {
        "schema": SCHEMA,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": copy.deepcopy(body)
    }
    
    # Add optional keys if provided
    if proposed_recipient_id is not None:
        message["proposed_recipient_id"] = proposed_recipient_id
    
    if parent_message_sha256 is not None:
        message["parent_message_sha256"] = parent_message_sha256
    
    # Validate the message once
    valid, reason = validate_postal_message(message)
    
    if not valid:
        return (None, (reason,))
    
    # Build routing request - never put proposal schema or peer inside message
    routing_request = {}
    if proposed_recipient_id is not None:
        routing_request["recipient_id"] = proposed_recipient_id
    
    proposal = {
        "schema": "hive_postal_outbox_proposal_v1",
        "message": message,
        "routing_request": routing_request
    }
    
    return (proposal, ())

# Self-check assertions
if __name__ == "__main__":
    # Test case 1: exact default values
    result = prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="drone_alpha",
        authority_queen_id="queen_primary",
        task_id="task_build",
        body={"status": "ready"}
    )
    
    proposal, _ = result[0]
    assert proposal["schema"] == "hive_postal_outbox_proposal_v1"
    assert proposal["message"]["schema"] == SCHEMA
    assert proposal["message"]["sender_id"] == "drone_alpha"
    assert proposal["message"]["recipient_id"] == "queen_primary"
    assert proposal["message"]["body"] == {"status": "ready"}
    
    # Test case 2: peer outside message (proposed_recipient_id should not be in message)
    result = prepare_queen_outbox_proposal(
        message_id="msg_002",
        sender_id="drone_beta",
        authority_queen_id="queen_secondary",
        task_id="task_test",
        body={"data": "test"},
        proposed_recipient_id="external_peer"
    )
    
    proposal, _ = result[0]
    assert "proposed_recipient_id" not in proposal["message"]
    assert proposal["routing_request"]["recipient_id"] == "external_peer"
    
    # Test case 3: nested deep copy - body should be independent
    original_body = {"nested": {"value": 42}}
    result = prepare_queen_outbox_proposal(
        message_id="msg_003",
        sender_id="drone_gamma",
        authority_queen_id="queen_tertiary",
        task_id="task_copy",
        body=original_body
    )
    
    proposal, _ = result[0]
    # Modify original and check message is independent
    original_body["nested"]["value"] = 999
    assert proposal["message"]["body"]["nested"]["value"] == 42
    
    # Test case 4: reject list body (should fail validation)
    result = prepare_queen_outbox_proposal(
        message_id="msg_004",
        sender_id="drone_delta",
        authority_queen_id="queen_quaternary",
        task_id="task_list",
        body=["item1", "item2"]  # List instead of dict
    )
    
    proposal, reason = result[0]
    assert proposal is None
    assert isinstance(reason, tuple) and len(reason) == 1
    
    # Test case 5: reject Queen peer (casefold check)
    result = prepare_queen_outbox_proposal(
        message_id="msg_005",
        sender_id="drone_epsilon",
        authority_queen_id="QUEEN_PRIMARY"  # Different case
    )
    
    proposal, reason = result[0]
    assert proposal is None
    assert isinstance(reason, tuple) and len(reason) == 1
    
    print("PASS: 5 checks")
