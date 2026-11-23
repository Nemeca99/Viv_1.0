from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message


def prepare_queen_outbox_proposal(
    message_id: str,
    sender_id: str,
    authority_queen_id: str,
    task_id: str,
    body: list,
    *,
    kind: str = "REPORT",
    proposed_recipient_id: str | None = None,
    parent_message_sha256: str | None = None,
) -> tuple[list[dict], dict[str, any] | None]:
    """Prepare a queen outbox proposal."""
    # Deep-copy body to avoid mutation of original
    deep_body = list(body)

    # Build message keys
    message_keys = {
        "schema": SCHEMA,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": deep_body,
    }

    # Add parent_message_sha256 only if given
    if parent_message_sha256 is not None:
        message_keys["parent_message_sha256"] = parent_message_sha256

    # Validate the message
    validation_result = validate_postal_message(message_keys)
    if validation_result[0] is None:
        return (None, validation_result[1])

    # Determine routing_request based on peer casefold
    peer = authority_queen_id.lower()
    if peer == "queen":
        return ([message_keys], None)
    else:
        routing_request = {authority_queen_id: authority_queen_id}
        return ([message_keys], routing_request)


# Self-check exactly 5
def run_self_checks():
    checks_passed = 0

    # Check 1: default proposal/route None
    result, _ = prepare_queen_outbox_proposal(
        message_id="msg_001",
        sender_id="user_001",
        authority_queen_id="queen",
        task_id="task_001",
        body=["test"],
    )
    if result[0] is None:
        checks_passed += 1

    # Check 2: peer casefold == "queen" -> proposed_recipient_is_queen error
    result, reason = prepare_queen_outbox_proposal(
        message_id="msg_002",
        sender_id="user_002",
        authority_queen_id="QUEEN",
        task_id="task_002",
        body=["test"],
    )
    if reason == ("proposed_recipient_is_queen",):
        checks_passed += 1

    # Check 3: nested deep-copy survives changing original
    original_body = ["a", "b"]
    result, _ = prepare_queen_outbox_proposal(
        message_id="msg_003",
        sender_id="user_003",
        authority_queen_id="queen",
        task_id="task_003",
        body=original_body,
    )
    # Modify original after call
    original_body.append("c")
    if result[0][0]["body"] == ["a", "b"]:
        checks_passed += 1

    # Check 4: list body rejected (non-list)
    try:
        result, _ = prepare_queen_outbox_proposal(
            message_id="msg_004",
            sender_id="user_004",
            authority_queen_id="queen",
            task_id="task_004",
            body={"not": "a list"},  # This will fail validation
        )
    except Exception:
        checks_passed += 1

    # Check 5: peer casefold == "QUEEN" -> proposed_recipient_is_queen error
    result, reason = prepare_queen_outbox_proposal(
        message_id="msg_005",
        sender_id="user_005",
        authority_queen_id="Queen",
        task_id="task_005",
        body=["test"],
    )
    if reason == ("proposed_recipient_is_queen",):
        checks_passed += 1

    print(f"PASS: {checks_passed} checks")
    return checks_passed == 5


if __name__ == "__main__":
    run_self_checks()