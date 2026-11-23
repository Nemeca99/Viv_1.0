import copy
from hive_postal_message_contract_queen_v3_candidate import (
    copy as _copy,
    SCHEMA,
    validate_postal_message,
)


def prepare_queen_outbox_proposal(
    message_id: str,
    sender_id: str,
    authority_queen_id: str,
    task_id: str,
    body: str,
    *,
    kind: str = "REPORT",
    proposed_recipient_id: str | None = None,
    parent_message_sha256: str | None = None,
) -> tuple[dict[str, any] | None, tuple[str, ...]]:
    """Prepare a queen outbox proposal with validation."""
    
    # Deep-copy body to prevent mutation
    deep_body = copy.deepcopy(body)
    
    # Build envelope structure
    envelope = {
        "schema": SCHEMA,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": deep_body,
    }
    
    # Add optional parent_message_sha256 if provided
    if parent_message_sha256 is not None:
        envelope["parent_message_sha256"] = parent_message_sha256
    
    # Validate the envelope once
    valid, reason = validate_postal_message(envelope)
    
    # Handle invalid envelope
    if not valid:
        return (None, (reason,))
    
    # Peer validation logic
    peer = None
    if proposed_recipient_id is not None:
        peer = proposed_recipient_id
        
        # Check for empty or whitespace-only recipient
        trimmed_peer = peer.strip()
        if len(trimmed_peer) == 0:
            return (None, ("invalid_proposed_recipient_id",))
        
        # Check if peer changes the recipient (should remain authority_queen_id)
        if trimmed_peer != authority_queen_id:
            return (None, ("invalid_proposed_recipient_id",))
        
        # Check if peer is "QUEEN" (case-insensitive)
        if trimmed_peer.casefold() == "queen":
            return (None, ("proposed_recipient_is_queen",))
    
    # Build routing_request based on peer
    routing_request = None
    if peer is not None:
        routing_request = {"recipient_id": peer}
    
    # Create final proposal structure
    proposal = {
        "schema": "hive_postal_outbox_proposal_v1",
        "message": envelope,
        "routing_request": routing_request,
    }
    
    return (proposal, ())


# Self-check test
if __name__ == "__main__":
    import hashlib
    
    # Test case 1: Valid envelope with REPORT kind
    result = prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_001",
        body="Test message content",
        kind="REPORT",
    )
    
    proposal, errors = result
    
    # Verify structure
    assert proposal is not None, "Proposal should not be None"
    assert len(errors) == 0, f"Should have no errors, got: {errors}"
    assert proposal["schema"] == "hive_postal_outbox_proposal_v1", "Schema mismatch"
    assert proposal["message"]["kind"] == "REPORT", "Kind should be REPORT"
    
    # Verify deep-copy (body should not be mutated)
    original_body = "Test message content"
    prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_001",
        body=original_body,
        kind="REPORT",
    )
    
    # Test case 2: Invalid peer (empty string)
    result = prepare_queen_outbox_proposal(
        message_id="msg_002",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_002",
        body="Test",
        proposed_recipient_id="",
    )
    
    proposal, errors = result
    assert proposal is None, "Proposal should be None for invalid peer"
    assert len(errors) == 1, f"Should have one error, got: {errors}"
    assert errors[0] == ("invalid_proposed_recipient_id",), f"Wrong error: {errors}"
    
    # Test case 3: Peer changes recipient (should remain authority_queen_id)
    result = prepare_queen_outbox_proposal(
        message_id="msg_003",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_003",
        body="Test",
        proposed_recipient_id="other_peer",
    )
    
    proposal, errors = result
    assert proposal is None, "Proposal should be None when peer changes recipient"
    assert len(errors) == 1, f"Should have one error, got: {errors}"
    assert errors[0] == ("invalid_proposed_recipient_id",), f"Wrong error: {errors}"
    
    # Test case 4: Peer is "QUEEN" (case-insensitive)
    result = prepare_queen_outbox_proposal(
        message_id="msg_004",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_004",
        body="Test",
        proposed_recipient_id="QUEEN",
    )
    
    proposal, errors = result
    assert proposal is None, "Proposal should be None when peer is QUEEN"
    assert len(errors) == 1, f"Should have one error, got: {errors}"
    assert errors[0] == ("proposed_recipient_is_queen",), f"Wrong error: {errors}"
    
    # Test case 5: Invalid kind (not REPORT or valid postal message)
    result = prepare_queen_outbox_proposal(
        message_id="msg_005",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_005",
        body=["list", "body"],  # List body should be rejected
        kind="REPORT",
    )
    
    proposal, errors = result
    assert proposal is None, "Proposal should be None for list body"
    assert len(errors) == 1, f"Should have one error, got: {errors}"
    
    # Test case 6: Bad hash (parent_message_sha256 with wrong format)
    result = prepare_queen_outbox_proposal(
        message_id="msg_006",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_006",
        body="Test",
        parent_message_sha256="invalid_hash_format",  # Not a proper SHA-256 hex string
    )
    
    proposal, errors = result
    assert proposal is None, "Proposal should be None for invalid hash"
    assert len(errors) == 1, f"Should have one error, got: {errors}"
    
    # Test case 7: Peer is "queen" (lowercase)
    result = prepare_queen_outbox_proposal(
        message_id="msg_007",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_007",
        body="Test",
        proposed_recipient_id="queen",
    )
    
    proposal, errors = result
    assert proposal is None, "Proposal should be None when peer is 'queen'"
    assert len(errors) == 1, f"Should have one error, got: {errors}"
    assert errors[0] == ("proposed_recipient_is_queen",), f"Wrong error: {errors}"
    
    # Test case 8: Valid with parent_message_sha256
    valid_hash = hashlib.sha256(b"test").hexdigest()
    result = prepare_queen_outbox_proposal(
        message_id="msg_008",
        sender_id="sender_001",
        authority_queen_id="queen_main",
        task_id="task_008",
        body="Test with parent hash",
        kind="REPORT",
        proposed_recipient_id=None,
        parent_message_sha256=valid_hash,
    )
    
    proposal, errors = result
    assert proposal is not None, "Proposal should be valid"
    assert len(errors) == 0, f"Should have no errors, got: {errors}"
    assert proposal["message"]["parent_message_sha256"] == valid_hash, "Parent hash mismatch"
    
    print("PASS")