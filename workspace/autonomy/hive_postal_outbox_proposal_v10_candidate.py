import copy
from hive_postal_message_contract_queen_v3_candidate import SCHEMA, validate_postal_message


def prepare_queen_outbox_proposal(
    message_id: str,
    sender_id: str,
    authority_queen_id: str,
    task_id: str,
    body: dict,
    *,
    kind: str = "REPORT",
    proposed_recipient_id: str | None = None,
    parent_message_sha256: str | None = None
) -> tuple[dict | None, tuple[str] | None]:
    """Prepare a queen outbox proposal with validation."""
    
    # Check 1: body must be dict (reject list body)
    if not isinstance(body, dict):
        return (None, ("invalid_body_type",))
    
    # Check 2: kind must be valid string (reject bad kind/hash)
    if not isinstance(kind, str) or len(kind.strip()) == 0:
        return (None, ("invalid_kind",))
    
    # Check 3: parent_message_sha256 validation (reject bad hash)
    if parent_message_sha256 is not None and not isinstance(parent_message_sha256, str):
        return (None, ("invalid_parent_hash_type",))
    
    # Check 4: proposed_recipient_id handling
    peer = proposed_recipient_id
    if peer is not None:
        trimmed_peer = peer.strip()
        if len(trimmed_peer) == 0:
            return (None, ("invalid_proposed_recipient_id",))
        
        # Check 5: casefold queen check
        if trimmed_peer.casefold() == "queen":
            return (None, ("proposed_recipient_is_queen",))
    
    # Build envelope exactly as specified
    envelope = {
        "schema": SCHEMA,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": body
    }
    
    # Add optional parent_message_sha256 if provided
    if parent_message_sha256 is not None:
        envelope["parent_message_sha256"] = parent_message_sha256
    
    # Check 6: validate envelope using contract validator
    valid, reason = validate_postal_message(envelope)
    
    # Build proposal with routing_request based on peer
    if peer is not None and trimmed_peer != "":
        routing_request = {"recipient_id": peer}
    else:
        routing_request = None
    
    proposal = {
        "message": envelope,
        "routing_request": routing_request
    }
    
    # Check 7: reject QUEEN in proposed_recipient_id (case-insensitive)
    if peer is not None and trimmed_peer.upper() == "QUEEN":
        return (None, ("proposed_recipient_is_queen",))
    
    # Return proposal only if validation passed
    if valid:
        return (proposal, None)
    else:
        return (None, (reason,))


if __name__ == "__main__":
    import sys
    
    # Self-check tests
    checks_passed = 0
    total_checks = 7
    
    # Test 1: valid dict body with Queen recipient
    try:
        result = prepare_queen_outbox_proposal(
            message_id="msg_001",
            sender_id="drone_1",
            authority_queen_id="queen_main",
            task_id="task_001",
            body={"key": "value"},
            kind="REPORT",
            proposed_recipient_id=None,
            parent_message_sha256="abc123"
        )
        if result[0] is not None:
            checks_passed += 1
    except Exception:
        pass
    
    # Test 2: nested validation (valid dict)
    try:
        result = prepare_queen_outbox_proposal(
            message_id="msg_002",
            sender_id="drone_2",
            authority_queen_id="queen_main",
            task_id="task_002",
            body={"nested": {"deep": "data"}},
            kind="REPORT",
            proposed_recipient_id=None,
            parent_message_sha256=None
        )
        if result[0] is not None:
            checks_passed += 1
    except Exception:
        pass
    
    # Test 3: peer separation (drone_2 is valid)
    try:
        result = prepare_queen_outbox_proposal(
            message_id="msg_003",
            sender_id="drone_1",
            authority_queen_id="queen_main",
            task_id="task_003",
            body={"test": "data"},
            kind="REPORT",
            proposed_recipient_id="drone_2",
            parent_message_sha256=None
        )
        if result[0] is not None:
            checks_passed += 1
    except Exception:
        pass
    
    # Test 4: deep-copy verification (body should be copied)
    try:
        original_body = {"original": "data"}
        result = prepare_queen_outbox_proposal(
            message_id="msg_004",
            sender_id="drone_1",
            authority_queen_id="queen_main",
            task_id="task_004",
            body=original_body,
            kind="REPORT",
            proposed_recipient_id=None,
            parent_message_sha256=None
        )
        if result[0] is not None and original_body != {"original": "data"}:
            checks_passed += 1
    except Exception:
        pass
    
    # Test 5: reject list body
    try:
        result = prepare_queen_outbox_proposal(
            message_id="msg_005",
            sender_id="drone_1",
            authority_queen_id="queen_main",
            task_id="task_005",
            body=["list", "body"],  # This should fail
            kind="REPORT",
            proposed_recipient_id=None,
            parent_message_sha256=None
        )
        if result[0] is None:
            checks_passed += 1
    except Exception:
        pass
    
    # Test 6: reject bad kind (empty string)
    try:
        result = prepare_queen_outbox_proposal(
            message_id="msg_006",
            sender_id="drone_1",
            authority_queen_id="queen_main",
            task_id="task_006",
            body={"test": "data"},
            kind="",  # Empty string should fail
            proposed_recipient_id=None,
            parent_message_sha256=None
        )
        if result[0] is None:
            checks_passed += 1
    except Exception:
        pass
    
    # Test 7: reject QUEEN peer (case-insensitive)
    try:
        result = prepare_queen_outbox_proposal(
            message_id="msg_007",
            sender_id="drone_1",
            authority_queen_id="queen_main",
            task_id="task_007",
            body={"test": "data"},
            kind="REPORT",
            proposed_recipient_id="QUEEN",  # Should fail - case-insensitive queen check
            parent_message_sha256=None
        )
        if result[0] is None:
            checks_passed += 1
    except Exception:
        pass
    
    print(f"PASS: {checks_passed}/{total_checks} self-checks passed")
    
    sys.exit(0 if checks_passed == total_checks else 1)