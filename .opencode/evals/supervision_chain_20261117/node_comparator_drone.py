"""composition_node_identity_candidate.py — pure comparator for node identity validation."""


def validate_node_identity(node: dict, expected: dict, expected_relay_count: int) -> str | None:
    """Validate a node against an expected signature and relay count.

    Returns None on success; error string on failure.
    Standard library only. No I/O, imports with side effects, databases, main block.
    """
    # Require node and expected to be dicts
    if not isinstance(node, dict) or not isinstance(expected, dict):
        return "node_identity_type_error: both node and expected must be dicts"

    # Require expected.gate_status == 'ALLOW'
    if expected.get("gate_status") != "ALLOW":
        return f"expected_gate_status_mismatch: got {expected.get('gate_status')!r}, want 'ALLOW'"

    # Require expected.language == 'python'
    if expected.get("language") != "python":
        return f"expected_language_mismatch: got {expected.get('language')!r}, want 'python'"

    # Required fields to compare: version_id, task_id, function_name, code_sha256, tests_sha256
    required_fields = ("version_id", "task_id", "function_name", "code_sha256", "tests_sha256")

    for field in required_fields:
        node_val = node.get(field)
        exp_val = expected.get(field)

        # Both must exist and have same type and value
        if node_val is None or exp_val is None:
            return f"node_identity_field_missing: {field}"
        if not isinstance(node_val, type(exp_val)):
            return f"node_identity_type_mismatch: {field} got {type(node_val).__name__}, expected {type(exp_val).__name__}"
        if node_val != exp_val:
            return f"node_identity_value_mismatch: {field} got {node_val!r}, expected {exp_val!r}"

    # Require node.relay_count to be int (not bool) and equal expected_relay_count
    relay_node = node.get("relay_count")
    if not isinstance(relay_node, int):
        return f"node_relay_count_type_error: got {type(relay_node).__name__}, want int"
    # bool is a subclass of int in Python; explicitly reject it
    if isinstance(relay_node, bool):
        return "node_relay_count_bool_error: relay_count must not be bool"

    if relay_node != expected_relay_count or not isinstance(expected_relay_count, int):
        return f"node_relay_count_mismatch: got {relay_node}, expected {expected_relay_count}"

    return None
