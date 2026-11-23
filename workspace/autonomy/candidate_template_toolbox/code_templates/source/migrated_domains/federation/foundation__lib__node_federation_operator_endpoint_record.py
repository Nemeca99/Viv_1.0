"""Strict, read-only intake gate for an operator-supplied endpoint record.

An absent operator record is represented explicitly and safely.  The validator
does not discover, resolve, fetch, contact, admit, or activate an endpoint; it
only verifies the parent readiness lineage and the closed missing-record
state.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
DEFAULT_OPERATOR_RECORD_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_OPERATOR_ENDPOINT_RECORD_CONTRACT.json"
)
DEFAULT_OPERATOR_RECORD = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_OPERATOR_ENDPOINT_RECORD.json"
)
RECORD_SCHEMA_VERSION = "viv_node_federation_operator_endpoint_record_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_operator_endpoint_record_contract_v1"
EXPECTED_STATUS = "MISSING_OPERATOR_ENDPOINT_IDENTITY"
EXPECTED_SOURCE = "OPERATOR_SUPPLIED_REQUIRED"
EXPECTED_NEXT_STATE = "MISSING_OPERATOR_ENDPOINT_IDENTITY"
EXPECTED_DECISION = "HOLD_MISSING_OPERATOR_ENDPOINT_IDENTITY"
REQUIRED_IDENTITY_FIELDS = (
    "operator_identity_sha256",
    "endpoint_id",
    "endpoint_class",
    "host",
    "port",
    "tls_server_name",
    "ca_certificate_sha256",
    "server_certificate_sha256",
    "node_id",
    "key_id",
    "public_key_sha256",
    "node_identity_hash",
    "lineage_hash",
    "endpoint_identity_fingerprint_sha256",
)


class OperatorEndpointRecordError(ValueError):
    """Raised when operator-record intake inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise OperatorEndpointRecordError(f"operator_endpoint_record_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorEndpointRecordError(f"operator_endpoint_record_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise OperatorEndpointRecordError(f"operator_endpoint_record_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationOperatorEndpointRecordValidator:
    """Validate the explicit missing-record fixture and future operator input."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_OPERATOR_RECORD_CONTRACT,
        record_path: Path = DEFAULT_OPERATOR_RECORD,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.record_path = Path(record_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.record = _load_json(self.record_path, "record")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.record_sha256 = _hash_file(self.record_path)
        parent = self.contract.get("parent_readiness")
        if not isinstance(parent, Mapping):
            raise OperatorEndpointRecordError("operator_endpoint_record_parent_section_missing")
        self.parent_contract_path = _resolve_repo_path(parent.get("contract_path"))
        self.parent_proposal_path = _resolve_repo_path(parent.get("proposal_path"))
        self.parent_receipt_path = _resolve_repo_path(parent.get("preflight_receipt_path"))
        if self.parent_contract_path is None or self.parent_proposal_path is None or self.parent_receipt_path is None:
            raise OperatorEndpointRecordError("operator_endpoint_record_parent_paths_invalid")
        self.parent_contract = _load_json(self.parent_contract_path, "parent_contract")
        self.parent_proposal = _load_json(self.parent_proposal_path, "parent_proposal")
        self.parent_receipt = _load_json(self.parent_receipt_path, "parent_receipt")
        self.parent_contract_sha256 = _hash_file(self.parent_contract_path)
        self.parent_proposal_sha256 = _hash_file(self.parent_proposal_path)
        self.parent_receipt_sha256 = _hash_file(self.parent_receipt_path)

    def validate(self) -> dict[str, Any]:
        """Return aggregate evidence for the missing or supplied operator record."""
        return self.evaluate_record(self.record, record_sha256=self.record_sha256)

    def evaluate_record(
        self,
        record: Mapping[str, Any] | Any,
        *,
        record_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory record without persistence or external effects."""
        format_reasons, hold_reasons = self._validate_inputs(record)
        if record_sha256 is None:
            record_sha256 = _hash_bytes(_canonical(dict(record))) if isinstance(record, Mapping) else None
        reason_codes = list(dict.fromkeys(format_reasons + hold_reasons))
        if not hold_reasons:
            hold_reasons.append("operator_endpoint_record_hold_reason_missing")
            reason_codes.append("operator_endpoint_record_hold_reason_missing")

        record_validated = not format_reasons
        safe_hold = (
            isinstance(record, Mapping)
            and record.get("record_status") == EXPECTED_STATUS
            and record.get("operator_endpoint_record_present") is False
            and record.get("real_endpoint_identity_supplied") is False
            and record.get("identity_complete") is False
            and record.get("record_admitted") is False
            and record.get("dns_resolution_allowed") is False
            and record.get("certificate_fetch_allowed") is False
            and record.get("socket_open_allowed") is False
            and record.get("network_contacted") is False
            and record.get("deployment_changed") is False
            and record.get("activation_allowed") is False
            and record.get("network_write_authorized") is False
            and record.get("automatic_discovery") is False
        )
        preflight_pass = record_validated and bool(hold_reasons) and safe_hold
        if not safe_hold:
            reason_codes.append("operator_endpoint_record_safe_hold_violated")
            preflight_pass = False
        if not record_validated:
            preflight_pass = False

        return {
            "preflight_pass": preflight_pass,
            "record_validated": record_validated,
            "decision": EXPECTED_DECISION,
            "safe_hold": safe_hold,
            "record_id": record.get("record_id") if isinstance(record, Mapping) else None,
            "record_status": record.get("record_status") if isinstance(record, Mapping) else None,
            "record_source": record.get("record_source") if isinstance(record, Mapping) else None,
            "record_sha256": record_sha256,
            "operator_record_contract_sha256": self.contract_sha256,
            "parent_readiness_contract_sha256": self.parent_contract_sha256,
            "parent_readiness_proposal_sha256": self.parent_proposal_sha256,
            "parent_readiness_receipt_sha256": self.parent_receipt_sha256,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "missing_required_fields": list(REQUIRED_IDENTITY_FIELDS),
            "parent_readiness_bound": not any(
                reason in reason_codes
                for reason in (
                    "parent_readiness_contract_hash_mismatch",
                    "parent_readiness_proposal_hash_mismatch",
                    "parent_readiness_receipt_hash_mismatch",
                    "parent_readiness_contract_path_mismatch",
                    "parent_readiness_proposal_path_mismatch",
                    "parent_readiness_receipt_path_mismatch",
                )
            ),
            "parent_readiness_verified": not any(
                reason in reason_codes
                for reason in ("parent_readiness_status_mismatch", "parent_readiness_decision_mismatch")
            ),
            "operator_endpoint_record_present": (
                record.get("operator_endpoint_record_present") is True if isinstance(record, Mapping) else False
            ),
            "real_endpoint_identity_supplied": (
                record.get("real_endpoint_identity_supplied") is True if isinstance(record, Mapping) else False
            ),
            "identity_complete": record.get("identity_complete") is True if isinstance(record, Mapping) else False,
            "record_admitted": False,
            "dns_resolution_allowed": (
                record.get("dns_resolution_allowed") is True if isinstance(record, Mapping) else False
            ),
            "certificate_fetch_allowed": (
                record.get("certificate_fetch_allowed") is True if isinstance(record, Mapping) else False
            ),
            "socket_open_allowed": record.get("socket_open_allowed") is True if isinstance(record, Mapping) else False,
            "network_contacted": False,
            "deployment_changed": False,
            "raw_record_persisted": False,
            "raw_record_retained": False,
        }

    def _validate_inputs(self, record: Mapping[str, Any] | Any) -> tuple[list[str], list[str]]:
        format_reasons: list[str] = []
        hold_reasons: list[str] = []
        contract = self.contract
        parent = contract.get("parent_readiness")
        required_fields = contract.get("required_identity_fields")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("operator_endpoint_record_contract_schema_mismatch")
        if not isinstance(parent, Mapping):
            format_reasons.append("operator_endpoint_record_parent_section_invalid")
            parent = {}
        if not isinstance(required_fields, list) or tuple(required_fields) != REQUIRED_IDENTITY_FIELDS:
            format_reasons.append("operator_endpoint_record_required_fields_invalid")
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("operator_endpoint_record_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("operator_endpoint_record_implementation_invalid")
            implementation = {}
        if parent.get("contract_sha256") != self.parent_contract_sha256:
            format_reasons.append("parent_readiness_contract_hash_mismatch")
        if parent.get("proposal_sha256") != self.parent_proposal_sha256:
            format_reasons.append("parent_readiness_proposal_hash_mismatch")
        if parent.get("preflight_receipt_sha256") != self.parent_receipt_sha256:
            format_reasons.append("parent_readiness_receipt_hash_mismatch")
        if _resolve_repo_path(parent.get("contract_path")) != self.parent_contract_path:
            format_reasons.append("parent_readiness_contract_path_mismatch")
        if _resolve_repo_path(parent.get("proposal_path")) != self.parent_proposal_path:
            format_reasons.append("parent_readiness_proposal_path_mismatch")
        if _resolve_repo_path(parent.get("preflight_receipt_path")) != self.parent_receipt_path:
            format_reasons.append("parent_readiness_receipt_path_mismatch")
        if self.parent_receipt.get("status") != parent.get("required_status"):
            format_reasons.append("parent_readiness_status_mismatch")
        if self.parent_receipt.get("preflight_result", {}).get("readiness_decision") != parent.get("required_decision"):
            format_reasons.append("parent_readiness_decision_mismatch")
        for field in (
            "network_sender",
            "dns_resolver",
            "certificate_fetcher",
            "filesystem_writer",
            "record_admission_capability",
            "activation_capability",
        ):
            if implementation.get(field) is not False:
                format_reasons.append(f"operator_endpoint_record_{field}_forbidden")

        if not isinstance(record, Mapping):
            format_reasons.append("operator_endpoint_record_must_be_object")
            return list(dict.fromkeys(format_reasons)), hold_reasons
        if record.get("schema_version") != RECORD_SCHEMA_VERSION:
            format_reasons.append("operator_endpoint_record_schema_mismatch")
        if record.get("record_status") != closed_fixture.get("record_status", EXPECTED_STATUS):
            format_reasons.append("operator_endpoint_record_status_invalid")
        if record.get("record_source") != closed_fixture.get("record_source", EXPECTED_SOURCE):
            format_reasons.append("operator_endpoint_record_source_invalid")
        if record.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("operator_endpoint_record_next_lifecycle_state_invalid")
        for field in REQUIRED_IDENTITY_FIELDS:
            if record.get(field) is not None:
                format_reasons.append(f"operator_endpoint_record_{field}_must_be_null_in_missing_fixture")
        for field in (
            "operator_endpoint_record_present",
            "real_endpoint_identity_supplied",
            "identity_complete",
            "record_admitted",
            "dns_resolution_allowed",
            "certificate_fetch_allowed",
            "socket_open_allowed",
            "network_contacted",
            "deployment_changed",
            "activation_allowed",
            "network_write_authorized",
            "automatic_discovery",
        ):
            if record.get(field) is not False:
                format_reasons.append(f"operator_endpoint_record_{field}_must_be_false_in_fixture")
        if self.parent_receipt.get("preflight_result", {}).get("missing_prerequisites"):
            hold_reasons.append("parent_readiness_reports_missing_operator_record")
        hold_reasons.append("operator_endpoint_identity_record_missing")
        hold_reasons.append("real_endpoint_identity_missing")
        hold_reasons.append("separate_activation_authorization_pending")
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(hold_reasons))


__all__ = [
    "DEFAULT_OPERATOR_RECORD",
    "DEFAULT_OPERATOR_RECORD_CONTRACT",
    "FederationOperatorEndpointRecordValidator",
    "OperatorEndpointRecordError",
]
