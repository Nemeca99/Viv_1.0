import copy
from hive_postal_message_contract_queen_v3_candidate import SCHEMA, VALID_KINDS, validate_postal_message


def prepare_queen_outbox_proposal(
    message_id: str,
    sender_id: str,
    authority_queen_id: str,
    task_id: str,
    body: dict,
    *,
    kind: str = "REPORT",
    proposed_recipient_id: str | None = None,
    parent_message_sha256: str | None = None,
) -> tuple[dict | None, tuple[str, ...] | None]:
    if not isinstance(body, dict):
        return (None, ("body must be a dict",))

    deep_body = copy.deepcopy(body)

    message = {
        "schema": SCHEMA,
        "message_id": message_id,
        "sender_id": sender_id,
        "recipient_id": authority_queen_id,
        "task_id": task_id,
        "kind": kind,
        "body": deep_body,
    }

    if parent_message_sha256 is not None:
        message["parent_message_sha256"] = parent_message_sha256

    errors = validate_postal_message(message)
    if errors:
        return (None, tuple(errors))

    proposal = {
        "schema": "hive_postal_outbox_proposal_v1",
        "message": message,
        "routing_request": None,
    }

    if proposed_recipient_id is not None and proposed_recipient_id != authority_queen_id:
        proposal["routing_request"] = {"recipient_id": proposed_recipient_id}

    return (proposal, None)