"""Read-only activation-authority gate for Viv federation.

The validator sits after deployment-record preflight and before any possible
transport capability.  It binds a proposed activation request to the parent
record, its contract, and its receipt, then proves that the current request
cannot self-authorize.  It has no signer, socket, DNS, subprocess, activation,
or filesystem-write capability and returns aggregate evidence only.
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
DEFAULT_AUTHORITY_CONTRACT = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_ACTIVATION_AUTHORITY_CONTRACT.json"
)
DEFAULT_AUTHORITY_PROPOSAL = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_ACTIVATION_AUTHORITY_PROPOSAL.json"
)
AUTHORITY_SCHEMA_VERSION = "viv_node_federation_activation_authority_proposal_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_activation_authority_contract_v1"
EXPECTED_REQUEST_STATUS = "PROPOSED_ACTIVATION_DENIED_NO_REAL_ENDPOINT"
EXPECTED_EVALUATION_MODE = "READ_ONLY_ACTIVATION_PREFLIGHT"
EXPECTED_SCOPE = "NO_CONTACT_NO_MUTATION"
EXPECTED_NEXT_STATE = "DENIED"
EXPECTED_PARENT_PREFLIGHT_STATUS = "PROPOSED_EXTERNAL_RECORD_PREFLIGHT_PASS_NO_CONTACT"
EXPECTED_PARENT_POLICY_DECISION = "DENY_DEPLOYMENT_POLICY"
EXPECTED_ENDPOINT_FIELDS = (
    "node_id",
    "key_id",
    "public_key_sha256",
    "node_identity_hash",
    "lineage_hash",
    "endpoint_id",
    "endpoint_class",
    "host",
    "port",
    "tls_server_name",
    "ca_certificate_sha256",
    "server_certificate_sha256",
)


class ActivationAuthorityError(ValueError):
    """Raised when activation-authority inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise ActivationAuthorityError(f"activation_authority_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ActivationAuthorityError(f"activation_authority_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise ActivationAuthorityError(f"activation_authority_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationActivationAuthorityValidator:
    """Validate a separate activation request without authorizing activation."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_AUTHORITY_CONTRACT,
        proposal_path: Path = DEFAULT_AUTHORITY_PROPOSAL,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        parent = self.contract.get("parent_deployment_record")
        if not isinstance(parent, Mapping):
            raise ActivationAuthorityError("activation_authority_parent_section_missing")
        self.parent_record_path = _resolve_repo_path(parent.get("record_path"))
        self.parent_record_contract_path = _resolve_repo_path(parent.get("record_contract_path"))
        self.parent_receipt_path = _resolve_repo_path(parent.get("preflight_receipt_path"))
        if self.parent_record_path is None or self.parent_record_contract_path is None or self.parent_receipt_path is None:
            raise ActivationAuthorityError("activation_authority_parent_paths_invalid")
        self.parent_record = _load_json(self.parent_record_path, "parent_record")
        self.parent_record_contract = _load_json(self.parent_record_contract_path, "parent_record_contract")
        self.parent_receipt = _load_json(self.parent_receipt_path, "parent_receipt")
        self.parent_record_sha256 = _hash_file(self.parent_record_path)
        self.parent_record_contract_sha256 = _hash_file(self.parent_record_contract_path)
        self.parent_receipt_sha256 = _hash_file(self.parent_receipt_path)

    def validate(self) -> dict[str, Any]:
        """Return a content-minimized, fail-closed activation preflight receipt."""
        return self.evaluate_proposal(self.proposal, proposal_sha256=self.proposal_sha256)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        proposal_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory request without persistence or side effects."""
        format_reasons, denial_reasons = self._validate_inputs(proposal)
        if proposal_sha256 is None:
            proposal_sha256 = _hash_bytes(_canonical(dict(proposal))) if isinstance(proposal, Mapping) else None
        reason_codes = list(dict.fromkeys(format_reasons + denial_reasons))
        if not denial_reasons:
            denial_reasons.append("activation_denial_reason_missing")
            reason_codes.append("activation_denial_reason_missing")

        proposal_validated = not format_reasons
        closed_flags = (
            isinstance(proposal, Mapping)
            and proposal.get("endpoint_contact_allowed") is False
            and proposal.get("activation_allowed") is False
            and proposal.get("network_write_authorized") is False
            and proposal.get("deployment_authorized") is False
            and proposal.get("network_contacted") is False
            and proposal.get("network_socket_opened") is False
            and proposal.get("activation_performed") is False
            and proposal.get("deployment_changed") is False
        )
        preflight_pass = proposal_validated and bool(denial_reasons) and closed_flags
        if not closed_flags:
            reason_codes.append("activation_authority_closed_flags_violated")
            preflight_pass = False
        if not proposal_validated:
            preflight_pass = False

        request_id = proposal.get("activation_request_id") if isinstance(proposal, Mapping) else None
        request_status = proposal.get("request_status") if isinstance(proposal, Mapping) else None
        endpoint_id = proposal.get("endpoint_id") if isinstance(proposal, Mapping) else None
        return {
            "preflight_pass": preflight_pass,
            "proposal_validated": proposal_validated,
            "activation_eligible": False,
            "decision": "DENY_ACTIVATION",
            "activation_request_id": request_id,
            "request_status": request_status,
            "evaluation_mode": proposal.get("evaluation_mode") if isinstance(proposal, Mapping) else None,
            "authority_scope": proposal.get("authority_scope") if isinstance(proposal, Mapping) else None,
            "endpoint_id": endpoint_id,
            "endpoint_class": proposal.get("endpoint_class") if isinstance(proposal, Mapping) else None,
            "requested_lifecycle_state": (
                proposal.get("requested_lifecycle_state") if isinstance(proposal, Mapping) else None
            ),
            "next_lifecycle_state": (
                proposal.get("next_lifecycle_state") if isinstance(proposal, Mapping) else None
            ),
            "proposal_sha256": proposal_sha256,
            "authority_contract_sha256": self.contract_sha256,
            "parent_record_sha256": self.parent_record_sha256,
            "parent_record_contract_sha256": self.parent_record_contract_sha256,
            "parent_preflight_receipt_sha256": self.parent_receipt_sha256,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "parent_record_bound": "parent_record_hash_mismatch" not in reason_codes,
            "parent_preflight_verified": "parent_preflight_status_mismatch" not in format_reasons,
            "real_endpoint_identity_supplied": (
                proposal.get("real_endpoint_identity_supplied") is True if isinstance(proposal, Mapping) else False
            ),
            "separate_activation_authorization_present": (
                proposal.get("operator_activation_authorization_present") is True
                if isinstance(proposal, Mapping)
                else False
            ),
            "endpoint_contact_allowed": (
                proposal.get("endpoint_contact_allowed") is True if isinstance(proposal, Mapping) else False
            ),
            "activation_allowed": (
                proposal.get("activation_allowed") is True if isinstance(proposal, Mapping) else False
            ),
            "network_contacted": (
                proposal.get("network_contacted") is True if isinstance(proposal, Mapping) else False
            ),
            "network_socket_opened": (
                proposal.get("network_socket_opened") is True if isinstance(proposal, Mapping) else False
            ),
            "activation_performed": (
                proposal.get("activation_performed") is True if isinstance(proposal, Mapping) else False
            ),
            "deployment_changed": (
                proposal.get("deployment_changed") is True if isinstance(proposal, Mapping) else False
            ),
            "raw_proposal_persisted": False,
            "raw_proposal_retained": False,
        }

    def _validate_inputs(self, proposal: Mapping[str, Any] | Any) -> tuple[list[str], list[str]]:
        format_reasons: list[str] = []
        denial_reasons: list[str] = []
        contract = self.contract
        parent_spec = contract.get("parent_deployment_record")
        eligibility = contract.get("activation_eligibility")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("activation_authority_contract_schema_mismatch")
        if not isinstance(parent_spec, Mapping):
            format_reasons.append("activation_authority_parent_section_invalid")
            parent_spec = {}
        if not isinstance(eligibility, Mapping):
            format_reasons.append("activation_authority_eligibility_section_invalid")
            eligibility = {}
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("activation_authority_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("activation_authority_implementation_section_invalid")
            implementation = {}

        if parent_spec.get("record_sha256") != self.parent_record_sha256:
            format_reasons.append("parent_record_hash_mismatch")
        if parent_spec.get("record_contract_sha256") != self.parent_record_contract_sha256:
            format_reasons.append("parent_record_contract_hash_mismatch")
        if parent_spec.get("preflight_receipt_sha256") != self.parent_receipt_sha256:
            format_reasons.append("parent_preflight_receipt_hash_mismatch")
        if _resolve_repo_path(parent_spec.get("record_path")) != self.parent_record_path:
            format_reasons.append("parent_record_path_mismatch")
        if _resolve_repo_path(parent_spec.get("record_contract_path")) != self.parent_record_contract_path:
            format_reasons.append("parent_record_contract_path_mismatch")
        if _resolve_repo_path(parent_spec.get("preflight_receipt_path")) != self.parent_receipt_path:
            format_reasons.append("parent_preflight_receipt_path_mismatch")
        if implementation.get("network_sender") is not False:
            format_reasons.append("activation_authority_network_sender_forbidden")
        if implementation.get("filesystem_writer") is not False:
            format_reasons.append("activation_authority_filesystem_writer_forbidden")
        if implementation.get("activation_capability") is not False:
            format_reasons.append("activation_authority_activation_capability_forbidden")
        if implementation.get("authorization_signer") is not False:
            format_reasons.append("activation_authority_signer_forbidden")

        parent_receipt_authority = self.parent_receipt.get("authority")
        if not isinstance(parent_receipt_authority, Mapping):
            format_reasons.append("parent_preflight_authority_section_missing")
            parent_receipt_authority = {}
        if self.parent_receipt.get("status") != parent_spec.get(
            "required_preflight_status", EXPECTED_PARENT_PREFLIGHT_STATUS
        ):
            format_reasons.append("parent_preflight_status_mismatch")
        if self.parent_receipt.get("record", {}).get("sha256") != self.parent_record_sha256:
            format_reasons.append("parent_receipt_record_hash_mismatch")
        if self.parent_receipt.get("record_contract", {}).get("sha256") != self.parent_record_contract_sha256:
            format_reasons.append("parent_receipt_record_contract_hash_mismatch")
        if self.parent_receipt.get("policy_result", {}).get("policy_decision") != parent_spec.get(
            "required_parent_policy_decision", EXPECTED_PARENT_POLICY_DECISION
        ):
            format_reasons.append("parent_policy_decision_mismatch")
        if parent_receipt_authority.get("deployment_authorized") is not False:
            format_reasons.append("parent_deployment_authority_not_closed")

        if not isinstance(proposal, Mapping):
            format_reasons.append("activation_authority_proposal_must_be_object")
            return list(dict.fromkeys(format_reasons)), denial_reasons

        if proposal.get("schema_version") != AUTHORITY_SCHEMA_VERSION:
            format_reasons.append("activation_authority_proposal_schema_mismatch")
        if proposal.get("request_status") != closed_fixture.get("request_status", EXPECTED_REQUEST_STATUS):
            format_reasons.append("activation_authority_request_status_invalid")
        if proposal.get("evaluation_mode") != closed_fixture.get("evaluation_mode", EXPECTED_EVALUATION_MODE):
            format_reasons.append("activation_authority_evaluation_mode_invalid")
        if proposal.get("authority_scope") != EXPECTED_SCOPE:
            format_reasons.append("activation_authority_scope_invalid")
        if proposal.get("parent_record_sha256") != self.parent_record_sha256:
            format_reasons.append("proposal_parent_record_hash_mismatch")
        if proposal.get("parent_record_contract_sha256") != self.parent_record_contract_sha256:
            format_reasons.append("proposal_parent_record_contract_hash_mismatch")
        if proposal.get("parent_preflight_receipt_sha256") != self.parent_receipt_sha256:
            format_reasons.append("proposal_parent_receipt_hash_mismatch")
        if proposal.get("parent_record_status") != self.parent_record.get("record_status"):
            format_reasons.append("proposal_parent_record_status_mismatch")
        if proposal.get("parent_policy_decision") != parent_spec.get(
            "required_parent_policy_decision", EXPECTED_PARENT_POLICY_DECISION
        ):
            format_reasons.append("proposal_parent_policy_decision_mismatch")
        for field in EXPECTED_ENDPOINT_FIELDS:
            if proposal.get(field) != self.parent_record.get(field):
                format_reasons.append(f"proposal_{field}_binding_mismatch")
        if proposal.get("endpoint_class") != "EXTERNAL":
            format_reasons.append("activation_authority_endpoint_class_invalid")
        if proposal.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("activation_authority_next_lifecycle_state_invalid")
        if proposal.get("reserved_test_net_address") is not True:
            format_reasons.append("activation_authority_reserved_fixture_required")
        if proposal.get("real_endpoint_identity_supplied") is not False:
            format_reasons.append("activation_authority_real_endpoint_must_be_closed_in_fixture")
        if proposal.get("operator_activation_authorization_present") is not False:
            format_reasons.append("activation_authority_separate_auth_must_be_closed_in_fixture")
        for field in (
            "authorization_record_id",
            "operator_authorization_sha256",
            "authorization_scope_sha256",
            "authorization_expires_utc",
            "operator_signature_sha256",
        ):
            if proposal.get(field) is not None:
                format_reasons.append(f"activation_authority_{field}_must_be_absent_in_fixture")
        for field in (
            "endpoint_contact_allowed",
            "activation_allowed",
            "network_write_authorized",
            "deployment_authorized",
            "network_contacted",
            "network_socket_opened",
            "activation_performed",
            "deployment_changed",
            "raw_payload_forwarding",
            "raw_payload_persistence",
        ):
            if proposal.get(field) is not False:
                format_reasons.append(f"activation_authority_{field}_must_be_closed")

        if self.parent_record.get("reserved_test_net_address") is True:
            denial_reasons.append("parent_record_is_reserved_test_fixture")
        if self.parent_record.get("record_status") != "OPERATOR_AUTHORIZED":
            denial_reasons.append("parent_record_not_operator_authorized")
        denial_reasons.append("parent_record_policy_denied")
        if proposal.get("real_endpoint_identity_supplied") is False:
            denial_reasons.append("real_endpoint_identity_missing")
        if proposal.get("operator_activation_authorization_present") is False:
            denial_reasons.append("separate_activation_authorization_missing")
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(denial_reasons))


__all__ = [
    "ActivationAuthorityError",
    "DEFAULT_AUTHORITY_CONTRACT",
    "DEFAULT_AUTHORITY_PROPOSAL",
    "FederationActivationAuthorityValidator",
]
