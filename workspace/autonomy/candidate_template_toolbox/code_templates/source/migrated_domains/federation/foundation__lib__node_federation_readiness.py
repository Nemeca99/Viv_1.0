"""Hash-bound, read-only federation readiness reducer for Viv.

The reducer consumes the sealed deployment, activation-authority, and
endpoint-identity receipts and emits one deterministic readiness state.  It
does not create missing identity or authorization, and it has no DNS, socket,
certificate-fetch, activation, deployment, subprocess, or write capability.
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
DEFAULT_READINESS_CONTRACT = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_READINESS_CONTRACT.json"
)
DEFAULT_READINESS_PROPOSAL = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_READINESS_PROPOSAL.json"
)
READINESS_SCHEMA_VERSION = "viv_node_federation_readiness_proposal_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_readiness_contract_v1"
EXPECTED_REQUEST_STATUS = "HOLD_MISSING_OPERATOR_ENDPOINT_IDENTITY"
EXPECTED_EVALUATION_MODE = "READ_ONLY_FEDERATION_READINESS_PREFLIGHT"
EXPECTED_SCOPE = "NO_CONTACT_NO_MUTATION"
EXPECTED_DECISION = "HOLD"
EXPECTED_NEXT_STATE = "HOLD_MISSING_OPERATOR_ENDPOINT_IDENTITY"
EXPECTED_MISSING = (
    "operator_endpoint_identity_record",
    "real_endpoint_identity",
    "separate_activation_authorization",
    "external_endpoint_allowlist_admission",
)


class FederationReadinessError(ValueError):
    """Raised when readiness inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise FederationReadinessError(f"federation_readiness_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederationReadinessError(f"federation_readiness_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise FederationReadinessError(f"federation_readiness_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationReadinessValidator:
    """Reduce sealed child receipts to a fail-closed readiness decision."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_READINESS_CONTRACT,
        proposal_path: Path = DEFAULT_READINESS_PROPOSAL,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        inputs = self.contract.get("inputs")
        if not isinstance(inputs, Mapping):
            raise FederationReadinessError("federation_readiness_inputs_section_missing")
        self.child_paths = {
            "deployment_record": _resolve_repo_path(inputs.get("deployment_record_receipt_path")),
            "activation_authority": _resolve_repo_path(inputs.get("activation_authority_receipt_path")),
            "endpoint_identity": _resolve_repo_path(inputs.get("endpoint_identity_receipt_path")),
        }
        if any(path is None for path in self.child_paths.values()):
            raise FederationReadinessError("federation_readiness_child_paths_invalid")
        self.child_receipts = {
            key: _load_json(path, f"{key}_receipt")
            for key, path in self.child_paths.items()
            if path is not None
        }
        self.child_hashes = {
            key: _hash_file(path)
            for key, path in self.child_paths.items()
            if path is not None
        }

    def validate(self) -> dict[str, Any]:
        """Return aggregate readiness evidence without retaining child bodies."""
        return self.evaluate_proposal(self.proposal, proposal_sha256=self.proposal_sha256)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        proposal_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory readiness proposal without side effects."""
        format_reasons, hold_reasons = self._validate_inputs(proposal)
        if proposal_sha256 is None:
            proposal_sha256 = _hash_bytes(_canonical(dict(proposal))) if isinstance(proposal, Mapping) else None
        reason_codes = list(dict.fromkeys(format_reasons + hold_reasons))
        if not hold_reasons:
            hold_reasons.append("readiness_hold_reason_missing")
            reason_codes.append("readiness_hold_reason_missing")

        proposal_validated = not format_reasons
        safe_hold = (
            isinstance(proposal, Mapping)
            and proposal.get("readiness_decision") == EXPECTED_DECISION
            and proposal.get("safe_hold") is True
            and proposal.get("all_prerequisites_satisfied") is False
            and proposal.get("automatic_activation") is False
            and proposal.get("automatic_retry") is False
            and proposal.get("automatic_reauthorization") is False
            and proposal.get("network_contacted") is False
            and proposal.get("network_write_authorized") is False
            and proposal.get("deployment_changed") is False
        )
        preflight_pass = proposal_validated and bool(hold_reasons) and safe_hold
        if not safe_hold:
            reason_codes.append("readiness_safe_hold_violated")
            preflight_pass = False
        if not proposal_validated:
            preflight_pass = False

        return {
            "preflight_pass": preflight_pass,
            "proposal_validated": proposal_validated,
            "readiness_decision": EXPECTED_DECISION,
            "safe_hold": safe_hold,
            "all_prerequisites_satisfied": False,
            "readiness_request_id": proposal.get("readiness_request_id") if isinstance(proposal, Mapping) else None,
            "request_status": proposal.get("request_status") if isinstance(proposal, Mapping) else None,
            "evaluation_mode": proposal.get("evaluation_mode") if isinstance(proposal, Mapping) else None,
            "authority_scope": proposal.get("authority_scope") if isinstance(proposal, Mapping) else None,
            "next_lifecycle_state": proposal.get("next_lifecycle_state") if isinstance(proposal, Mapping) else None,
            "proposal_sha256": proposal_sha256,
            "readiness_contract_sha256": self.contract_sha256,
            "deployment_record_receipt_sha256": self.child_hashes["deployment_record"],
            "activation_authority_receipt_sha256": self.child_hashes["activation_authority"],
            "endpoint_identity_receipt_sha256": self.child_hashes["endpoint_identity"],
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "missing_prerequisites": list(EXPECTED_MISSING),
            "child_receipts_bound": not any("receipt_hash_mismatch" in reason for reason in reason_codes),
            "child_receipts_verified": not any(
                reason in reason_codes
                for reason in (
                    "deployment_record_child_state_mismatch",
                    "activation_authority_child_state_mismatch",
                    "endpoint_identity_child_state_mismatch",
                )
            ),
            "network_contacted": False,
            "network_write_authorized": False,
            "deployment_changed": False,
            "raw_child_receipts_retained": False,
            "raw_proposal_persisted": False,
        }

    def _validate_inputs(self, proposal: Mapping[str, Any] | Any) -> tuple[list[str], list[str]]:
        format_reasons: list[str] = []
        hold_reasons: list[str] = []
        contract = self.contract
        inputs = contract.get("inputs")
        child_states = contract.get("required_child_states")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("federation_readiness_contract_schema_mismatch")
        if not isinstance(inputs, Mapping):
            format_reasons.append("federation_readiness_inputs_section_invalid")
            inputs = {}
        if not isinstance(child_states, Mapping):
            format_reasons.append("federation_readiness_child_states_section_invalid")
            child_states = {}
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("federation_readiness_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("federation_readiness_implementation_section_invalid")
            implementation = {}

        expected_input_paths = {
            "deployment_record": inputs.get("deployment_record_receipt_path"),
            "activation_authority": inputs.get("activation_authority_receipt_path"),
            "endpoint_identity": inputs.get("endpoint_identity_receipt_path"),
        }
        expected_input_hashes = {
            "deployment_record": inputs.get("deployment_record_receipt_sha256"),
            "activation_authority": inputs.get("activation_authority_receipt_sha256"),
            "endpoint_identity": inputs.get("endpoint_identity_receipt_sha256"),
        }
        for key in self.child_paths:
            if _resolve_repo_path(expected_input_paths[key]) != self.child_paths[key]:
                format_reasons.append(f"{key}_child_path_mismatch")
            if expected_input_hashes[key] != self.child_hashes[key]:
                format_reasons.append(f"{key}_child_receipt_hash_mismatch")

        deployment = self.child_receipts["deployment_record"]
        activation = self.child_receipts["activation_authority"]
        endpoint = self.child_receipts["endpoint_identity"]
        if deployment.get("status") != child_states.get("deployment_record_status"):
            format_reasons.append("deployment_record_child_state_mismatch")
        if deployment.get("policy_result", {}).get("policy_decision") != child_states.get(
            "deployment_record_policy_decision"
        ):
            format_reasons.append("deployment_record_child_state_mismatch")
        if activation.get("status") != child_states.get("activation_authority_status"):
            format_reasons.append("activation_authority_child_state_mismatch")
        if activation.get("preflight_result", {}).get("decision") != child_states.get(
            "activation_authority_decision"
        ):
            format_reasons.append("activation_authority_child_state_mismatch")
        if endpoint.get("status") != child_states.get("endpoint_identity_status"):
            format_reasons.append("endpoint_identity_child_state_mismatch")
        if endpoint.get("preflight_result", {}).get("decision") != child_states.get("endpoint_identity_decision"):
            format_reasons.append("endpoint_identity_child_state_mismatch")

        for field in (
            "network_sender",
            "dns_resolver",
            "certificate_fetcher",
            "filesystem_writer",
            "activation_capability",
            "deployment_capability",
        ):
            if implementation.get(field) is not False:
                format_reasons.append(f"federation_readiness_{field}_forbidden")
        if not isinstance(proposal, Mapping):
            format_reasons.append("federation_readiness_proposal_must_be_object")
            return list(dict.fromkeys(format_reasons)), hold_reasons

        if proposal.get("schema_version") != READINESS_SCHEMA_VERSION:
            format_reasons.append("federation_readiness_proposal_schema_mismatch")
        if proposal.get("request_status") != closed_fixture.get("request_status", EXPECTED_REQUEST_STATUS):
            format_reasons.append("federation_readiness_request_status_invalid")
        if proposal.get("evaluation_mode") != closed_fixture.get("evaluation_mode", EXPECTED_EVALUATION_MODE):
            format_reasons.append("federation_readiness_evaluation_mode_invalid")
        if proposal.get("authority_scope") != EXPECTED_SCOPE:
            format_reasons.append("federation_readiness_scope_invalid")
        for key, field in (
            ("deployment_record", "deployment_record_receipt_sha256"),
            ("activation_authority", "activation_authority_receipt_sha256"),
            ("endpoint_identity", "endpoint_identity_receipt_sha256"),
        ):
            if proposal.get(field) != self.child_hashes[key]:
                format_reasons.append(f"proposal_{key}_receipt_hash_mismatch")
        if proposal.get("deployment_record_policy_decision") != child_states.get("deployment_record_policy_decision"):
            format_reasons.append("proposal_deployment_record_decision_mismatch")
        if proposal.get("activation_authority_decision") != child_states.get("activation_authority_decision"):
            format_reasons.append("proposal_activation_authority_decision_mismatch")
        if proposal.get("endpoint_identity_decision") != child_states.get("endpoint_identity_decision"):
            format_reasons.append("proposal_endpoint_identity_decision_mismatch")
        if proposal.get("readiness_decision") != closed_fixture.get("readiness_decision", EXPECTED_DECISION):
            format_reasons.append("federation_readiness_decision_invalid")
        if proposal.get("all_prerequisites_satisfied") is not False:
            format_reasons.append("federation_readiness_all_prerequisites_satisfied_must_be_false_in_fixture")
        if proposal.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("federation_readiness_next_lifecycle_state_invalid")
        if tuple(proposal.get("missing_prerequisites", [])) != EXPECTED_MISSING:
            format_reasons.append("federation_readiness_missing_prerequisites_invalid")
        for field in (
            "endpoint_identity_admitted",
            "real_endpoint_identity_supplied",
            "operator_endpoint_record_present",
            "activation_authority_eligible",
            "separate_activation_authorization_present",
            "deployment_policy_external_allowed",
        ):
            if proposal.get(field) is not False:
                format_reasons.append(f"federation_readiness_{field}_must_be_false_in_fixture")
        if endpoint.get("preflight_result", {}).get("identity_admitted") is False:
            hold_reasons.extend(("operator_endpoint_identity_record", "real_endpoint_identity"))
        if activation.get("preflight_result", {}).get("activation_eligible") is False:
            hold_reasons.append("separate_activation_authorization")
        if deployment.get("policy_result", {}).get("policy_decision") != "ALLOW_LOOPBACK_POLICY_ONLY":
            hold_reasons.append("external_endpoint_allowlist_admission")
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(hold_reasons))


__all__ = [
    "DEFAULT_READINESS_CONTRACT",
    "DEFAULT_READINESS_PROPOSAL",
    "FederationReadinessError",
    "FederationReadinessValidator",
]
