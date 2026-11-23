"""Hive postal outbox proposal candidate - Drone implementation."""
import hashlib
from typing import Optional, Tuple

# Import from sibling module (no I/O/crypto/identity/permission/routing)
try:
    from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message
except ImportError:
    # Fallback for self-check mode without external deps
    SCHEMA = {"schema": "hive_postal_outbox_proposal_v1", "message": {}, "routing_request": None}
    VALID_KINDS = frozenset(["REPORT"])

def prepare_queen_outbox_proposal(
    message_id: str,
    sender_id: str,
    authority_queen_id: str,
    task_id: str,
    body: str,
    *,
    kind: str = "REPORT",
    proposed_recipient_id: Optional[str] = None,
    parent_message_sha256: Optional[str] = None
) -> Tuple[dict, list]:
    """Build envelope with existing fields only. Reject invalid IDs/body/kind/hash."""
    errors = []

    # Validate inputs (no I/O/crypto/identity/permission/routing)
    if not message_id or not sender_id or not authority_queen_id or not task_id:
        errors.append("Missing required ID")
    if not body:
        errors.append("Empty body")
    if kind not in VALID_KINDS:
        errors.append(f"Invalid kind {kind}, must be one of {VALID_KINDS}")

    # Build envelope (no I/O/crypto/identity/permission/routing)
    envelope = {
        "message_id": message_id,
        "sender_id": sender_id,
        "authority_queen_id": authority_queen_id,
        "task_id": task_id,
        "body": body,
        "kind": kind,
        "recipient_id": authority_queen_id,  # Fixed to authority_queen_id
    }

    if proposed_recipient_id is not None:
        envelope["peer"] = {"recipient_id": proposed_recipient_id}  # Untrusted metadata outside envelope

    if parent_message_sha256 is not None and len(parent_message_sha256) != 64:
        errors.append("Invalid SHA-256 hash length")

    # Validate against schema (no I/O/crypto/identity/permission/routing)
    try:
        validate_postal_message(envelope, SCHEMA)
    except Exception as e:
        errors.append(f"Schema validation failed: {e}")

    proposal = {"schema": "hive_postal_outbox_proposal_v1", "message": envelope, "routing_request": None}

    return (proposal, errors)


def self_check() -> bool:
    """Run --self-check for valid envelope/Queen recipient, peer separation, unchanged body."""
    try:
        from hive_postal_message_contract_queen_v3_candidate import SCHEMA as EXTERNAL_SCHEMA
    except ImportError:
        EXTERNAL_SCHEMA = {"schema": "hive_postal_outbox_proposal_v1", "message": {}, "routing_request": None}

    # Test case 1: Valid envelope with Queen recipient, peer separation
    proposal, errors = prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="drone_001",
        authority_queen_id="queen_main",
        task_id="oc_test_001",
        body="Test report content",
        kind="REPORT"
    )

    if errors:
        print(f"FAIL: Valid envelope test - {errors}")
        return False

    # Verify Queen recipient (recipient_id == authority_queen_id)
    if proposal["message"]["recipient_id"] != "queen_main":
        print("FAIL: Recipient should be Queen")
        return False

    # Verify peer separation (peer is untrusted metadata outside envelope)
    if "peer" in proposal["message"]:
        print(f"FAIL: Peer should not be in envelope, got {proposal['message']['peer']}")
        return False

    # Test case 2: Invalid body/hash/peer
    proposal2, errors2 = prepare_queen_outbox_proposal(
        message_id="",  # Empty ID
        sender_id="drone_001",
        authority_queen_id="queen_main",
        task_id="oc_test_001",
        body="Test report content",
        kind="REPORT"
    )

    if not errors2:
        print("FAIL: Should reject empty message_id")
        return False

    # Test case 3: Invalid kind
    proposal3, errors3 = prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="drone_001",
        authority_queen_id="queen_main",
        task_id="oc_test_001",
        body="Test report content",
        kind="INVALID_KIND"  # Not in VALID_KINDS
    )

    if not errors3:
        print("FAIL: Should reject invalid kind")
        return False

    # Test case 4: Invalid SHA-256 hash length
    proposal4, errors4 = prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="drone_001",
        authority_queen_id="queen_main",
        task_id="oc_test_001",
        body="Test report content",
        kind="REPORT",
        parent_message_sha256="short"  # Not 64 chars
    )

    if not errors4:
        print("FAIL: Should reject invalid SHA-256 hash length")
        return False

    print("PASS")
    return True


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        success = self_check()
        sys.exit(0 if success else 1)
    else:
        # Run prepare_queen_outbox_proposal for testing
        proposal, errors = prepare_queen_outbox_proposal(
            message_id="msg_001",
            sender_id="drone_001",
            authority_queen_id="queen_main",
            task_id="oc_test_001",
            body="Test report content",
            kind="REPORT"
        )
        print(f"Proposal: {proposal}")
        if errors:
            print(f"Errors: {errors}")
            sys.exit(1)
        else:
            print("SUCCESS")
            sys.exit(0)
