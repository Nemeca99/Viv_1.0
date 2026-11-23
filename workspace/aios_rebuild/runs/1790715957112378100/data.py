"""
AIOS Viv Event Sourcing & Replay Projections (Data Core) Rebuild Template.
Strict AST deterministic template contract:
  - Imports: copy
  - Literal VARIABLES dictionary
  - def main(context, variables)
  - def sub_main_*(context, variables)
"""
import copy

# TEMPLATE VARIABLES BEGIN
VARIABLES = {
    "identity": 'Viv',
    "event_schema": 'hive_inventory_event_v1',
    "enforce_idempotency": True,
    "max_event_batch": 500,
}
# TEMPLATE VARIABLES END


def main(context, variables):
    """
    Project immutable event-sourced logs into balance and state snapshots.
    """
    updated = copy.deepcopy(dict(variables))
    events = list(context.get("events", []))

    seen_keys = set()
    processed_count = 0
    duplicate_count = 0

    for ev in events[: int(updated["max_event_batch"])]:
        key = str(ev.get("idempotency_key", ""))
        if bool(updated["enforce_idempotency"]) and key in seen_keys:
            duplicate_count += 1
            continue
        if key:
            seen_keys.add(key)
        processed_count += 1

    return {
        "ok": True,
        "identity": updated["identity"],
        "events_processed": processed_count,
        "duplicates_rejected": duplicate_count,
        "schema": updated["event_schema"],
        "variables": dict(updated),
    }


def sub_main_validate_schema(context, variables):
    """
    Submain step 1: Validate event payload shape.
    """
    updated = copy.deepcopy(dict(variables))
    return updated


def sub_main_project_state(context, variables):
    """
    Submain step 2: Compute replay state projections.
    """
    updated = copy.deepcopy(dict(variables))
    return updated
