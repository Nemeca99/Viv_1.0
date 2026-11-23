"""Read-only endpoint-identity admission gate for Viv federation.

The gate validates an explicitly supplied identity bundle against the prior
activation-authority lineage.  The current fixture is intentionally reserved
TEST-NET data, so the result is a governed denial.  This module has no DNS,
certificate-fetch, socket, subprocess, activation, or filesystem-write path.
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
DEFAULT_IDENTITY_CONTRACT = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_ENDPOINT_IDENTITY_CONTRACT.json"
)
DEFAULT_IDENTITY_PROPOSAL = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_ENDPOINT_IDENTITY_PROPOSAL.json"
)
IDENTITY_SCHEMA_VERSION = "viv_node_federation_endpoint_identity_proposal_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_endpoint_identity_contract_v1"
EXPECTED_REQUEST_STATUS = "PROPOSED_ENDPOINT_IDENTITY_DENIED_RESERVED_FIXTURE"
EXPECTED_EVALUATION_MODE = "READ_ONLY_ENDPOINT_IDENTITY_PREFLIGHT"
EXPECTED_SCOPE = "NO_DNS_NO_CONTACT_NO_MUTATION"
EXPECTED_NEXT_STATE = "DENIED"
EXPECTED_PARENT_DECISION = "DENY_ACTIVATION"
IDENTITY_FIELDS = (
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


class EndpointIdentityError(ValueError):
    """Raised when endpoint-identity inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise EndpointIdentityError(f"endpoint_identity_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EndpointIdentityError(f"endpoint_identity_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise EndpointIdentityError(f"endpoint_identity_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _identity_body(value: Mapping[str, Any]) -> dict[str, Any]:
    return {field: value.get(field) for field in IDENTITY_FIELDS}


def endpoint_identity_fingerprint(value: Mapping[str, Any]) -> str:
    """Hash only the public endpoint/node identity binding, never content."""
    return _hash_bytes(_canonical(_identity_body(value)))


class FederationEndpointIdentityValidator:
    """Validate one endpoint identity proposal without admitting it."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_IDENTITY_CONTRACT,
        proposal_path: Path = DEFAULT_IDENTITY_PROPOSAL,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        parent = self.contract.get("parent_activation_authority")
        if not isinstance(parent, Mapping):
            raise EndpointIdentityError("endpoint_identity_parent_section_missing")
        self.parent_contract_path = _resolve_repo_path(parent.get("contract_path"))
        self.parent_proposal_path = _resolve_repo_path(parent.get("proposal_path"))
        self.parent_receipt_path = _resolve_repo_path(parent.get("preflight_receipt_path"))
        if self.parent_contract_path is None or self.parent_proposal_path is None or self.parent_receipt_path is None:
            raise EndpointIdentityError("endpoint_identity_parent_paths_invalid")
        self.parent_contract = _load_json(self.parent_contract_path, "parent_contract")
        self.parent_proposal = _load_json(self.parent_proposal_path, "parent_proposal")
        self.parent_receipt = _load_json(self.parent_receipt_path, "parent_receipt")
        self.parent_contract_sha256 = _hash_file(self.parent_contract_path)
        self.parent_proposal_sha256 = _hash_file(self.parent_proposal_path)
        self.parent_receipt_sha256 = _hash_file(self.parent_receipt_path)

    def validate(self) -> dict[str, Any]:
        """Return aggregate evidence for the file-backed identity proposal."""
        return self.evaluate_proposal(self.proposal, proposal_sha256=self.proposal_sha256)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        proposal_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory identity proposal without persistence or contact."""
        format_reasons, denial_reasons = self._validate_inputs(proposal)
        if proposal_sha256 is None:
            proposal_sha256 = _hash_bytes(_canonical(dict(proposal))) if isinstance(proposal, Mapping) else None
        reason_codes = list(dict.fromkeys(format_reasons + denial_reasons))
        if not denial_reasons:
            denial_reasons.append("endpoint_identity_denial_reason_missing")
            reason_codes.append("endpoint_identity_denial_reason_missing")

        proposal_validated = not format_reasons
        closed_flags = (
            isinstance(proposal, Mapping)
            and proposal.get("dns_resolution_allowed") is False
            and proposal.get("certificate_fetch_allowed") is False
            and proposal.get("socket_open_allowed") is False
            and proposal.get("network_contacted") is False
            and proposal.get("deployment_changed") is False
            and proposal.get("identity_admitted") is False
        )
        preflight_pass = proposal_validated and bool(denial_reasons) and closed_flags
        if not closed_flags:
            reason_codes.append("endpoint_identity_closed_flags_violated")
            preflight_pass = False
        if not proposal_validated:
            preflight_pass = False

        request_id = proposal.get("identity_request_id") if isinstance(proposal, Mapping) else None
        return {
            "preflight_pass": preflight_pass,
            "proposal_validated": proposal_validated,
            "identity_admitted": False,
            "decision": "DENY_ENDPOINT_IDENTITY",
            "identity_request_id": request_id,
            "request_status": proposal.get("request_status") if isinstance(proposal, Mapping) else None,
            "evaluation_mode": proposal.get("evaluation_mode") if isinstance(proposal, Mapping) else None,
            "identity_source": proposal.get("identity_source") if isinstance(proposal, Mapping) else None,
            "authority_scope": proposal.get("authority_scope") if isinstance(proposal, Mapping) else None,
            "endpoint_id": proposal.get("endpoint_id") if isinstance(proposal, Mapping) else None,
            "endpoint_class": proposal.get("endpoint_class") if isinstance(proposal, Mapping) else None,
            "next_lifecycle_state": proposal.get("next_lifecycle_state") if isinstance(proposal, Mapping) else None,
            "proposal_sha256": proposal_sha256,
            "identity_contract_sha256": self.contract_sha256,
            "parent_activation_contract_sha256": self.parent_contract_sha256,
            "parent_activation_proposal_sha256": self.parent_proposal_sha256,
            "parent_activation_receipt_sha256": self.parent_receipt_sha256,
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "parent_activation_bound": "parent_activation_proposal_hash_mismatch" not in reason_codes,
            "parent_activation_verified": not any(
                reason in reason_codes
                for reason in (
                    "parent_activation_receipt_status_mismatch",
                    "parent_activation_decision_mismatch",
                    "parent_activation_authority_not_closed",
                )
            ),
            "operator_endpoint_record_present": (
                proposal.get("operator_endpoint_record_present") is True
                if isinstance(proposal, Mapping)
                else False
            ),
            "real_endpoint_identity_supplied": (
                proposal.get("real_endpoint_identity_supplied") is True
                if isinstance(proposal, Mapping)
                else False
            ),
            "identity_complete": proposal.get("identity_complete") is True if isinstance(proposal, Mapping) else False,
            "dns_resolution_allowed": (
                proposal.get("dns_resolution_allowed") is True if isinstance(proposal, Mapping) else False
            ),
            "certificate_fetch_allowed": (
                proposal.get("certificate_fetch_allowed") is True if isinstance(proposal, Mapping) else False
            ),
            "socket_open_allowed": (
                proposal.get("socket_open_allowed") is True if isinstance(proposal, Mapping) else False
            ),
            "network_contacted": (
                proposal.get("network_contacted") is True if isinstance(proposal, Mapping) else False
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
        parent = contract.get("parent_activation_authority")
        requirements = contract.get("identity_requirements")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("endpoint_identity_contract_schema_mismatch")
        if not isinstance(parent, Mapping):
            format_reasons.append("endpoint_identity_parent_section_invalid")
            parent = {}
        if not isinstance(requirements, Mapping):
            format_reasons.append("endpoint_identity_requirements_section_invalid")
            requirements = {}
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("endpoint_identity_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("endpoint_identity_implementation_section_invalid")
            implementation = {}

        if parent.get("contract_sha256") != self.parent_contract_sha256:
            format_reasons.append("parent_activation_contract_hash_mismatch")
        if parent.get("proposal_sha256") != self.parent_proposal_sha256:
            format_reasons.append("parent_activation_proposal_hash_mismatch")
        if parent.get("preflight_receipt_sha256") != self.parent_receipt_sha256:
            format_reasons.append("parent_activation_receipt_hash_mismatch")
        if _resolve_repo_path(parent.get("contract_path")) != self.parent_contract_path:
            format_reasons.append("parent_activation_contract_path_mismatch")
        if _resolve_repo_path(parent.get("proposal_path")) != self.parent_proposal_path:
            format_reasons.append("parent_activation_proposal_path_mismatch")
        if _resolve_repo_path(parent.get("preflight_receipt_path")) != self.parent_receipt_path:
            format_reasons.append("parent_activation_receipt_path_mismatch")
        if self.parent_receipt.get("status") != "CLOSED_ACTIVATION_AUTHORITY_PREFLIGHT_PASS_NO_CONTACT":
            format_reasons.append("parent_activation_receipt_status_mismatch")
        if self.parent_receipt.get("preflight_result", {}).get("decision") != parent.get(
            "required_decision", EXPECTED_PARENT_DECISION
        ):
            format_reasons.append("parent_activation_decision_mismatch")
        authority = self.parent_receipt.get("authority")
        if not isinstance(authority, Mapping):
            format_reasons.append("parent_activation_authority_section_missing")
            authority = {}
        if any(authority.get(field) is not False for field in ("deployment_authorized", "external_endpoint_contacted", "external_network_write_authorized")):
            format_reasons.append("parent_activation_authority_not_closed")
        for field in (
            "network_sender",
            "dns_resolver",
            "certificate_fetcher",
            "filesystem_writer",
            "identity_admission_capability",
        ):
            if implementation.get(field) is not False:
                format_reasons.append(f"endpoint_identity_{field}_forbidden")

        if not isinstance(proposal, Mapping):
            format_reasons.append("endpoint_identity_proposal_must_be_object")
            return list(dict.fromkeys(format_reasons)), denial_reasons

        if proposal.get("schema_version") != IDENTITY_SCHEMA_VERSION:
            format_reasons.append("endpoint_identity_proposal_schema_mismatch")
        if proposal.get("request_status") != closed_fixture.get("request_status", EXPECTED_REQUEST_STATUS):
            format_reasons.append("endpoint_identity_request_status_invalid")
        if proposal.get("evaluation_mode") != closed_fixture.get("evaluation_mode", EXPECTED_EVALUATION_MODE):
            format_reasons.append("endpoint_identity_evaluation_mode_invalid")
        if proposal.get("identity_source") != closed_fixture.get("identity_source", "RESERVED_TEST_NET_FIXTURE"):
            format_reasons.append("endpoint_identity_source_invalid")
        if proposal.get("authority_scope") != EXPECTED_SCOPE:
            format_reasons.append("endpoint_identity_scope_invalid")
        if proposal.get("parent_activation_contract_sha256") != self.parent_contract_sha256:
            format_reasons.append("proposal_parent_activation_contract_hash_mismatch")
        if proposal.get("parent_activation_proposal_sha256") != self.parent_proposal_sha256:
            format_reasons.append("proposal_parent_activation_proposal_hash_mismatch")
        if proposal.get("parent_activation_receipt_sha256") != self.parent_receipt_sha256:
            format_reasons.append("proposal_parent_activation_receipt_hash_mismatch")
        if proposal.get("parent_activation_decision") != parent.get("required_decision", EXPECTED_PARENT_DECISION):
            format_reasons.append("proposal_parent_activation_decision_mismatch")
        for field in IDENTITY_FIELDS:
            if proposal.get(field) != self.parent_proposal.get(field):
                format_reasons.append(f"endpoint_identity_{field}_binding_mismatch")
        if proposal.get("endpoint_identity_fingerprint_sha256") != endpoint_identity_fingerprint(proposal):
            format_reasons.append("endpoint_identity_fingerprint_mismatch")
        if proposal.get("endpoint_class") != "EXTERNAL":
            format_reasons.append("endpoint_identity_endpoint_class_invalid")
        if proposal.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("endpoint_identity_next_lifecycle_state_invalid")
        for field in (
            "reserved_test_net_address",
            "operator_endpoint_record_present",
            "real_endpoint_identity_supplied",
            "identity_complete",
            "identity_admitted",
            "dns_resolution_allowed",
            "certificate_fetch_allowed",
            "socket_open_allowed",
            "network_contacted",
            "deployment_changed",
        ):
            expected = True if field == "reserved_test_net_address" else False
            if proposal.get(field) is not expected:
                format_reasons.append(f"endpoint_identity_{field}_fixture_value_invalid")

        if self.parent_proposal.get("real_endpoint_identity_supplied") is False:
            denial_reasons.append("parent_activation_has_no_real_endpoint_identity")
        if self.parent_proposal.get("operator_activation_authorization_present") is False:
            denial_reasons.append("parent_activation_authorization_missing")
        if proposal.get("identity_source") == "RESERVED_TEST_NET_FIXTURE":
            denial_reasons.append("endpoint_identity_is_reserved_test_fixture")
        if proposal.get("operator_endpoint_record_present") is False:
            denial_reasons.append("operator_endpoint_identity_record_missing")
        if proposal.get("real_endpoint_identity_supplied") is False:
            denial_reasons.append("real_endpoint_identity_missing")
        if proposal.get("identity_complete") is False:
            denial_reasons.append("endpoint_identity_incomplete")
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(denial_reasons))


__all__ = [
    "DEFAULT_IDENTITY_CONTRACT",
    "DEFAULT_IDENTITY_PROPOSAL",
    "EndpointIdentityError",
    "FederationEndpointIdentityValidator",
    "endpoint_identity_fingerprint",
]
