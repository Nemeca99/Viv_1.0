"""Deny-by-default validator for the Viv node-to-Master telemetry boundary.

This module validates aggregate node telemetry only. It does not send data,
read prompts, inspect knowledge, inspect expert content, or persist runtime
state. Unknown fields and content-shaped fields are rejected rather than
silently forwarded.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Mapping


HERE = Path(__file__).resolve().parent
DEFAULT_CONTRACT = HERE.parent / "artifacts" / "auto" / "agentic" / "NODE_TELEMETRY_CONTRACT.json"
HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
FORBIDDEN_VALUE_RE = re.compile(r"(?:prompt_sha256|span_id|trace_id|master_s_n|run_authorized|training_authorized)", re.IGNORECASE)


class TelemetryContractError(ValueError):
    """Raised when a node telemetry envelope violates the contract."""


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TelemetryContractError("telemetry_contract_must_be_object")
    return value


def _fail(reason: str) -> None:
    raise TelemetryContractError(reason)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"telemetry_field_must_be_object:{name}")
    return value


def _check_hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        _fail(f"telemetry_hash_invalid:{name}")


def _check_number(value: Any, name: str, *, minimum: float | None = None, maximum: float | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"telemetry_number_invalid:{name}")
    if minimum is not None and value < minimum:
        _fail(f"telemetry_number_below_minimum:{name}")
    if maximum is not None and value > maximum:
        _fail(f"telemetry_number_above_maximum:{name}")


def _scan_keys(value: Any, *, path: str, forbidden: tuple[str, ...], max_string_length: int) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(f"telemetry_key_must_be_string:{path}")
            lowered = key.casefold()
            if any(fragment in lowered for fragment in forbidden):
                _fail(f"telemetry_forbidden_field:{path}.{key}")
            _scan_keys(child, path=f"{path}.{key}", forbidden=forbidden, max_string_length=max_string_length)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_keys(child, path=f"{path}[{index}]", forbidden=forbidden, max_string_length=max_string_length)
    elif isinstance(value, str):
        if len(value) > max_string_length:
            _fail(f"telemetry_string_too_long:{path}")
        if FORBIDDEN_VALUE_RE.search(value):
            _fail(f"telemetry_forbidden_value_pattern:{path}")


def validate_telemetry(message: Mapping[str, Any], contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Validate one outbound envelope without returning or storing its content."""
    active = contract or load_contract()
    if active.get("status") not in {"PREPARED_READ_ONLY_NO_NETWORK_WRITES", "ACTIVE_VALIDATOR_NO_NETWORK_WRITES"}:
        _fail("telemetry_contract_status_not_admissible")
    if not isinstance(message, Mapping):
        _fail("telemetry_message_must_be_object")
    contract_message = _mapping(active.get("message_contract"), "message_contract")
    required = tuple(str(value) for value in contract_message.get("required_top_level_fields", ()))
    missing = [field for field in required if field not in message]
    if missing:
        _fail(f"telemetry_required_fields_missing:{','.join(missing)}")
    allowlist = _mapping(active.get("allowlist"), "allowlist")
    allowed_top = set(required)
    unknown = sorted(set(message) - allowed_top)
    if unknown:
        _fail(f"telemetry_unknown_top_level_fields:{','.join(str(value) for value in unknown)}")
    forbidden = tuple(str(value).casefold() for value in active.get("forbidden_key_fragments", ()))
    _scan_keys(message, path="message", forbidden=forbidden, max_string_length=int(contract_message.get("max_string_length", 256)))
    if message.get("schema_version") != active.get("schema_version") or message.get("contract_id") != active.get("contract_id"):
        _fail("telemetry_schema_or_contract_mismatch")
    if message.get("message_type") not in set(contract_message.get("message_types", ())):
        _fail("telemetry_message_type_invalid")
    if not isinstance(message.get("node_id"), str) or not message["node_id"]:
        _fail("telemetry_node_id_invalid")
    if isinstance(message.get("sequence"), bool) or not isinstance(message.get("sequence"), int) or message["sequence"] < 0:
        _fail("telemetry_sequence_invalid")
    emitted = message.get("emitted_utc")
    if not isinstance(emitted, str) or UTC_RE.fullmatch(emitted) is None:
        _fail("telemetry_timestamp_invalid")
    try:
        datetime.fromisoformat(emitted[:-1] + "+00:00")
    except ValueError as exc:
        raise TelemetryContractError("telemetry_timestamp_unparseable") from exc
    if message.get("node_state") not in set(contract_message.get("node_states", ())):
        _fail("telemetry_node_state_invalid")
    for section_name, field_names in allowlist.items():
        section = _mapping(message.get(section_name), section_name)
        unknown_fields = sorted(set(section) - set(field_names))
        if unknown_fields:
            _fail(f"telemetry_unknown_fields:{section_name}:{','.join(str(value) for value in unknown_fields)}")
    attestation = _mapping(message["identity_attestation"], "identity_attestation")
    for field in allowlist["identity_attestation"]:
        _check_hash(attestation[field], f"identity_attestation.{field}")
    lineage = _mapping(message["lineage"], "lineage")
    for field in allowlist["lineage"]:
        _check_hash(lineage[field], f"lineage.{field}")
    for name, value in _mapping(message["health"], "health").items():
        if name == "last_successful_probe_utc":
            if not isinstance(value, str) or UTC_RE.fullmatch(value) is None:
                _fail("telemetry_probe_timestamp_invalid")
        else:
            _check_number(value, f"health.{name}", minimum=0.0, maximum=1.0 if name == "probe_pass_rate" else None)
    for name, value in _mapping(message["resource"], "resource").items():
        _check_number(value, f"resource.{name}", minimum=0.0)
    for name, value in _mapping(message["security"], "security").items():
        if name.endswith("count") or name == "revocation_epoch":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _fail(f"telemetry_security_counter_invalid:{name}")
    for name, value in _mapping(message["capabilities"], "capabilities").items():
        if not isinstance(value, bool):
            _fail(f"telemetry_capability_flag_invalid:{name}")
    boundary = _mapping(message["boundary_attestation"], "boundary_attestation")
    for name, value in boundary.items():
        if not isinstance(value, bool):
            _fail(f"telemetry_boundary_flag_invalid:{name}")
    required_values = _mapping(active.get("required_boundary_values"), "required_boundary_values")
    for name, expected in required_values.items():
        if message.get("capabilities", {}).get(name) != expected and message.get("boundary_attestation", {}).get(name) != expected:
            _fail(f"telemetry_required_boundary_value:{name}")
    return {"valid": True, "message_type": message["message_type"], "node_state": message["node_state"], "sequence": message["sequence"]}


def build_telemetry_envelope(**fields: Any) -> dict[str, Any]:
    """Build and validate an allowlisted envelope; never accepts arbitrary content."""
    envelope = dict(fields)
    validate_telemetry(envelope)
    return envelope


__all__ = ["TelemetryContractError", "build_telemetry_envelope", "load_contract", "validate_telemetry"]
