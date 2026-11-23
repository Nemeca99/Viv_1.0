"""Strict, read-only intake gate for separate federation activation authority.

The gate records the absence of a separately supplied, time-bounded operator
authorization as a safe hold.  It binds the authorization intake to the
endpoint-record, activation-authority, and composite-readiness receipts, but
it cannot sign, admit, activate, contact, reauthorize, or write anything.
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
DEFAULT_AUTHORIZATION_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ACTIVATION_AUTHORIZATION_RECORD_CONTRACT.json"
)
DEFAULT_AUTHORIZATION_RECORD = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ACTIVATION_AUTHORIZATION_RECORD.json"
)
AUTHORIZATION_SCHEMA_VERSION = "viv_node_federation_activation_authorization_record_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_activation_authorization_record_contract_v1"
EXPECTED_STATUS = "MISSING_SEPARATE_ACTIVATION_AUTHORIZATION"
EXPECTED_SOURCE = "OPERATOR_SUPPLIED_REQUIRED"
EXPECTED_NEXT_STATE = "MISSING_SEPARATE_ACTIVATION_AUTHORIZATION"
EXPECTED_DECISION = "HOLD_MISSING_SEPARATE_ACTIVATION_AUTHORIZATION"
REQUIRED_AUTHORIZATION_FIELDS = (
    "authorization_record_id",
    "operator_identity_sha256",
    "operator_authorization_sha256",
    "authorization_scope_sha256",
    "authorization_issued_utc",
    "authorization_expires_utc",
    "operator_signature_sha256",
    "endpoint_identity_fingerprint_sha256",
    "node_identity_hash",
    "lineage_hash",
)
CLOSED_FALSE_FIELDS = (
    "authorization_record_present",
    "authorization_valid",
    "authorization_admitted",
    "authorization_signer_verified",
    "activation_authorized",
    "endpoint_contact_authorized",
    "network_write_authorized",
    "deployment_authorized",
    "network_contacted",
    "network_socket_opened",
    "activation_performed",
    "deployment_changed",
    "automatic_activation",
    "automatic_reauthorization",
    "raw_authorization_persisted",
)


class ActivationAuthorizationRecordError(ValueError):
    """Raised when activation-authorization intake inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise ActivationAuthorizationRecordError(
            f"activation_authorization_record_file_unreadable:{path}"
        ) from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationAuthorizationRecordError(
            f"activation_authorization_record_{label}_unreadable:{path}"
        ) from exc
    if not isinstance(value, dict):
        raise ActivationAuthorizationRecordError(
            f"activation_authorization_record_{label}_must_be_object:{path}"
        )
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationActivationAuthorizationRecordValidator:
    """Validate the explicit missing authorization record without side effects."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_AUTHORIZATION_CONTRACT,
        record_path: Path = DEFAULT_AUTHORIZATION_RECORD,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.record_path = Path(record_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.record = _load_json(self.record_path, "record")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.record_sha256 = _hash_file(self.record_path)

        parents = self.contract.get("parent_inputs")
        if not isinstance(parents, Mapping):
            raise ActivationAuthorizationRecordError("activation_authorization_record_parent_section_missing")

        endpoint = parents.get("operator_endpoint_record")
        activation = parents.get("activation_authority")
        readiness = parents.get("readiness")
        if not isinstance(endpoint, Mapping) or not isinstance(activation, Mapping) or not isinstance(readiness, Mapping):
            raise ActivationAuthorizationRecordError("activation_authorization_record_parent_sections_invalid")

        self.endpoint_record_path = _resolve_repo_path(endpoint.get("record_path"))
        self.endpoint_contract_path = _resolve_repo_path(endpoint.get("record_contract_path"))
        self.endpoint_receipt_path = _resolve_repo_path(endpoint.get("preflight_receipt_path"))
        self.activation_contract_path = _resolve_repo_path(activation.get("contract_path"))
        self.activation_proposal_path = _resolve_repo_path(activation.get("proposal_path"))
        self.activation_receipt_path = _resolve_repo_path(activation.get("preflight_receipt_path"))
        self.readiness_contract_path = _resolve_repo_path(readiness.get("contract_path"))
        self.readiness_proposal_path = _resolve_repo_path(readiness.get("proposal_path"))
        self.readiness_receipt_path = _resolve_repo_path(readiness.get("preflight_receipt_path"))
        paths = (
            self.endpoint_record_path,
            self.endpoint_contract_path,
            self.endpoint_receipt_path,
            self.activation_contract_path,
            self.activation_proposal_path,
            self.activation_receipt_path,
            self.readiness_contract_path,
            self.readiness_proposal_path,
            self.readiness_receipt_path,
        )
        if any(path is None for path in paths):
            raise ActivationAuthorizationRecordError("activation_authorization_record_parent_paths_invalid")

        self.endpoint_record = _load_json(self.endpoint_record_path, "endpoint_record")
        self.endpoint_contract = _load_json(self.endpoint_contract_path, "endpoint_contract")
        self.endpoint_receipt = _load_json(self.endpoint_receipt_path, "endpoint_receipt")
        self.activation_contract = _load_json(self.activation_contract_path, "activation_contract")
        self.activation_proposal = _load_json(self.activation_proposal_path, "activation_proposal")
        self.activation_receipt = _load_json(self.activation_receipt_path, "activation_receipt")
        self.readiness_contract = _load_json(self.readiness_contract_path, "readiness_contract")
        self.readiness_proposal = _load_json(self.readiness_proposal_path, "readiness_proposal")
        self.readiness_receipt = _load_json(self.readiness_receipt_path, "readiness_receipt")

        self.endpoint_record_sha256 = _hash_file(self.endpoint_record_path)
        self.endpoint_contract_sha256 = _hash_file(self.endpoint_contract_path)
        self.endpoint_receipt_sha256 = _hash_file(self.endpoint_receipt_path)
        self.activation_contract_sha256 = _hash_file(self.activation_contract_path)
        self.activation_proposal_sha256 = _hash_file(self.activation_proposal_path)
        self.activation_receipt_sha256 = _hash_file(self.activation_receipt_path)
        self.readiness_contract_sha256 = _hash_file(self.readiness_contract_path)
        self.readiness_proposal_sha256 = _hash_file(self.readiness_proposal_path)
        self.readiness_receipt_sha256 = _hash_file(self.readiness_receipt_path)

    def validate(self) -> dict[str, Any]:
        """Return aggregate evidence for the missing or supplied authorization record."""
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
            hold_reasons.append("activation_authorization_record_hold_reason_missing")
            reason_codes.append("activation_authorization_record_hold_reason_missing")

        record_validated = not format_reasons
        safe_hold = (
            isinstance(record, Mapping)
            and record.get("record_status") == EXPECTED_STATUS
            and all(record.get(field) is False for field in CLOSED_FALSE_FIELDS)
        )
        preflight_pass = record_validated and bool(hold_reasons) and safe_hold
        if not safe_hold:
            reason_codes.append("activation_authorization_record_safe_hold_violated")
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
            "authorization_record_contract_sha256": self.contract_sha256,
            "endpoint_record_sha256": self.endpoint_record_sha256,
            "endpoint_record_contract_sha256": self.endpoint_contract_sha256,
            "endpoint_record_receipt_sha256": self.endpoint_receipt_sha256,
            "activation_authority_contract_sha256": self.activation_contract_sha256,
            "activation_authority_proposal_sha256": self.activation_proposal_sha256,
            "activation_authority_receipt_sha256": self.activation_receipt_sha256,
            "readiness_contract_sha256": self.readiness_contract_sha256,
            "readiness_proposal_sha256": self.readiness_proposal_sha256,
            "readiness_receipt_sha256": self.readiness_receipt_sha256,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "missing_required_fields": list(REQUIRED_AUTHORIZATION_FIELDS),
            "parent_inputs_bound": not any(
                reason.endswith("_hash_mismatch") or reason.endswith("_path_mismatch") for reason in reason_codes
            ),
            "parent_inputs_verified": not any(
                reason.endswith("_status_mismatch") or reason.endswith("_decision_mismatch") for reason in reason_codes
            ),
            "authorization_record_present": (
                record.get("authorization_record_present") is True if isinstance(record, Mapping) else False
            ),
            "authorization_valid": record.get("authorization_valid") is True if isinstance(record, Mapping) else False,
            "authorization_admitted": False,
            "authorization_signer_verified": (
                record.get("authorization_signer_verified") is True if isinstance(record, Mapping) else False
            ),
            "activation_authorized": (
                record.get("activation_authorized") is True if isinstance(record, Mapping) else False
            ),
            "endpoint_contact_authorized": (
                record.get("endpoint_contact_authorized") is True if isinstance(record, Mapping) else False
            ),
            "network_write_authorized": (
                record.get("network_write_authorized") is True if isinstance(record, Mapping) else False
            ),
            "network_contacted": False,
            "network_socket_opened": False,
            "activation_performed": False,
            "deployment_changed": False,
            "raw_authorization_persisted": False,
            "raw_authorization_retained": False,
        }

    def _validate_inputs(self, record: Mapping[str, Any] | Any) -> tuple[list[str], list[str]]:
        format_reasons: list[str] = []
        hold_reasons: list[str] = []
        contract = self.contract
        parents = contract.get("parent_inputs")
        required_fields = contract.get("required_authorization_fields")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("activation_authorization_record_contract_schema_mismatch")
        if not isinstance(parents, Mapping):
            format_reasons.append("activation_authorization_record_parent_section_invalid")
            parents = {}
        if not isinstance(required_fields, list) or tuple(required_fields) != REQUIRED_AUTHORIZATION_FIELDS:
            format_reasons.append("activation_authorization_record_required_fields_invalid")
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("activation_authorization_record_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("activation_authorization_record_implementation_invalid")
            implementation = {}

        endpoint = parents.get("operator_endpoint_record")
        activation = parents.get("activation_authority")
        readiness = parents.get("readiness")
        if not isinstance(endpoint, Mapping) or not isinstance(activation, Mapping) or not isinstance(readiness, Mapping):
            format_reasons.append("activation_authorization_record_parent_sections_invalid")
            endpoint = endpoint if isinstance(endpoint, Mapping) else {}
            activation = activation if isinstance(activation, Mapping) else {}
            readiness = readiness if isinstance(readiness, Mapping) else {}

        def check_path_and_hash(
            section: Mapping[str, Any],
            path_field: str,
            expected_path: Path,
            hash_field: str,
            actual_hash: str,
            label: str,
        ) -> None:
            if _resolve_repo_path(section.get(path_field)) != expected_path:
                format_reasons.append(f"{label}_{path_field}_mismatch")
            if section.get(hash_field) != actual_hash:
                format_reasons.append(f"{label}_{hash_field}_mismatch")

        check_path_and_hash(endpoint, "record_path", self.endpoint_record_path, "record_sha256", self.endpoint_record_sha256, "endpoint_record")
        check_path_and_hash(
            endpoint,
            "record_contract_path",
            self.endpoint_contract_path,
            "record_contract_sha256",
            self.endpoint_contract_sha256,
            "endpoint_record",
        )
        check_path_and_hash(
            endpoint,
            "preflight_receipt_path",
            self.endpoint_receipt_path,
            "preflight_receipt_sha256",
            self.endpoint_receipt_sha256,
            "endpoint_record",
        )
        check_path_and_hash(activation, "contract_path", self.activation_contract_path, "contract_sha256", self.activation_contract_sha256, "activation_authority")
        check_path_and_hash(activation, "proposal_path", self.activation_proposal_path, "proposal_sha256", self.activation_proposal_sha256, "activation_authority")
        check_path_and_hash(
            activation,
            "preflight_receipt_path",
            self.activation_receipt_path,
            "preflight_receipt_sha256",
            self.activation_receipt_sha256,
            "activation_authority",
        )
        check_path_and_hash(readiness, "contract_path", self.readiness_contract_path, "contract_sha256", self.readiness_contract_sha256, "readiness")
        check_path_and_hash(readiness, "proposal_path", self.readiness_proposal_path, "proposal_sha256", self.readiness_proposal_sha256, "readiness")
        check_path_and_hash(
            readiness,
            "preflight_receipt_path",
            self.readiness_receipt_path,
            "preflight_receipt_sha256",
            self.readiness_receipt_sha256,
            "readiness",
        )

        if self.endpoint_receipt.get("status") != endpoint.get("required_preflight_status"):
            format_reasons.append("endpoint_record_preflight_status_mismatch")
        if self.endpoint_receipt.get("preflight_result", {}).get("decision") != endpoint.get("required_decision"):
            format_reasons.append("endpoint_record_preflight_decision_mismatch")
        if self.activation_receipt.get("status") != activation.get("required_preflight_status"):
            format_reasons.append("activation_authority_preflight_status_mismatch")
        if self.activation_receipt.get("preflight_result", {}).get("decision") != activation.get("required_decision"):
            format_reasons.append("activation_authority_preflight_decision_mismatch")
        if self.readiness_receipt.get("status") != readiness.get("required_preflight_status"):
            format_reasons.append("readiness_preflight_status_mismatch")
        if self.readiness_receipt.get("preflight_result", {}).get("readiness_decision") != readiness.get(
            "required_decision"
        ):
            format_reasons.append("readiness_preflight_decision_mismatch")

        if self.endpoint_record.get("record_status") != "MISSING_OPERATOR_ENDPOINT_IDENTITY":
            format_reasons.append("endpoint_record_state_mismatch")
        if self.endpoint_record.get("record_admitted") is not False:
            format_reasons.append("endpoint_record_admission_not_closed")
        if self.activation_receipt.get("preflight_result", {}).get("activation_eligible") is not False:
            format_reasons.append("activation_authority_eligibility_not_closed")
        if self.readiness_receipt.get("preflight_result", {}).get("safe_hold") is not True:
            format_reasons.append("readiness_safe_hold_not_closed")

        for field in (
            "network_sender",
            "filesystem_writer",
            "authorization_signer",
            "authorization_admission_capability",
            "activation_capability",
            "reauthorization_capability",
        ):
            if implementation.get(field) is not False:
                format_reasons.append(f"activation_authorization_record_{field}_forbidden")

        if not isinstance(record, Mapping):
            format_reasons.append("activation_authorization_record_must_be_object")
            return list(dict.fromkeys(format_reasons)), hold_reasons

        if record.get("schema_version") != AUTHORIZATION_SCHEMA_VERSION:
            format_reasons.append("activation_authorization_record_schema_mismatch")
        if record.get("record_status") != closed_fixture.get("record_status", EXPECTED_STATUS):
            format_reasons.append("activation_authorization_record_status_invalid")
        if record.get("record_source") != closed_fixture.get("record_source", EXPECTED_SOURCE):
            format_reasons.append("activation_authorization_record_source_invalid")
        if record.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("activation_authorization_record_next_lifecycle_state_invalid")
        for field in (
            "parent_endpoint_record_receipt_sha256",
            "parent_activation_authority_receipt_sha256",
            "parent_readiness_receipt_sha256",
        ):
            expected = {
                "parent_endpoint_record_receipt_sha256": self.endpoint_receipt_sha256,
                "parent_activation_authority_receipt_sha256": self.activation_receipt_sha256,
                "parent_readiness_receipt_sha256": self.readiness_receipt_sha256,
            }[field]
            if record.get(field) != expected:
                format_reasons.append(f"activation_authorization_record_{field}_mismatch")
        for field in REQUIRED_AUTHORIZATION_FIELDS:
            if record.get(field) is not None:
                format_reasons.append(f"activation_authorization_record_{field}_must_be_null_in_missing_fixture")
        for field in CLOSED_FALSE_FIELDS:
            if record.get(field) is not False:
                format_reasons.append(f"activation_authorization_record_{field}_must_be_false_in_fixture")

        hold_reasons.extend(("authorization_record_missing", "separate_activation_authorization_missing"))
        if self.endpoint_record.get("record_admitted") is False:
            hold_reasons.append("operator_endpoint_identity_record_missing")
        if self.readiness_receipt.get("preflight_result", {}).get("safe_hold") is True:
            hold_reasons.append("federation_readiness_safe_hold")
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(hold_reasons))


__all__ = [
    "DEFAULT_AUTHORIZATION_CONTRACT",
    "DEFAULT_AUTHORIZATION_RECORD",
    "ActivationAuthorizationRecordError",
    "FederationActivationAuthorizationRecordValidator",
]
