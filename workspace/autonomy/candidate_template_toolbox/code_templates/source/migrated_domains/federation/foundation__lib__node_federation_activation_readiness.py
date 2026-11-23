"""Hash-bound, read-only federation activation-readiness reducer.

This reducer joins the existing readiness receipt with the operator endpoint
record intake and separate activation-authorization intake.  It returns one
deterministic hold until both real operator inputs exist.  It cannot discover,
contact, sign, activate, deploy, retry, reauthorize, or write anything.
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
DEFAULT_ACTIVATION_READINESS_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ACTIVATION_READINESS_CONTRACT.json"
)
DEFAULT_ACTIVATION_READINESS_PROPOSAL = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ACTIVATION_READINESS_PROPOSAL.json"
)
READINESS_SCHEMA_VERSION = "viv_node_federation_activation_readiness_proposal_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_activation_readiness_contract_v1"
EXPECTED_REQUEST_STATUS = "HOLD_MISSING_OPERATOR_ENDPOINT_IDENTITY_AND_ACTIVATION_AUTHORIZATION"
EXPECTED_EVALUATION_MODE = "READ_ONLY_FEDERATION_ACTIVATION_READINESS_PREFLIGHT"
EXPECTED_SCOPE = "NO_CONTACT_NO_MUTATION"
EXPECTED_DECISION = "HOLD"
EXPECTED_NEXT_STATE = "HOLD_MISSING_OPERATOR_ENDPOINT_IDENTITY_AND_ACTIVATION_AUTHORIZATION"
EXPECTED_MISSING = (
    "operator_endpoint_identity_record",
    "real_endpoint_identity",
    "separate_activation_authorization",
    "external_endpoint_allowlist_admission",
)


class FederationActivationReadinessError(ValueError):
    """Raised when activation-readiness inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise FederationActivationReadinessError(f"federation_activation_readiness_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederationActivationReadinessError(
            f"federation_activation_readiness_{label}_unreadable:{path}"
        ) from exc
    if not isinstance(value, dict):
        raise FederationActivationReadinessError(
            f"federation_activation_readiness_{label}_must_be_object:{path}"
        )
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationActivationReadinessValidator:
    """Reduce sealed readiness and intake receipts to one safe hold."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_ACTIVATION_READINESS_CONTRACT,
        proposal_path: Path = DEFAULT_ACTIVATION_READINESS_PROPOSAL,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        parent_inputs = self.contract.get("parent_inputs")
        if not isinstance(parent_inputs, Mapping):
            raise FederationActivationReadinessError("federation_activation_readiness_parent_section_missing")

        self.parent_paths: dict[str, dict[str, Path]] = {}
        for name, fields in (
            (
                "baseline_readiness",
                ("contract_path", "proposal_path", "preflight_receipt_path"),
            ),
            (
                "operator_endpoint_record",
                ("contract_path", "record_path", "preflight_receipt_path"),
            ),
            (
                "activation_authorization_record",
                ("contract_path", "record_path", "preflight_receipt_path"),
            ),
        ):
            section = parent_inputs.get(name)
            if not isinstance(section, Mapping):
                raise FederationActivationReadinessError(f"federation_activation_readiness_{name}_section_invalid")
            paths: dict[str, Path] = {}
            for field in fields:
                path = _resolve_repo_path(section.get(field))
                if path is None:
                    raise FederationActivationReadinessError(
                        f"federation_activation_readiness_{name}_{field}_invalid"
                    )
                paths[field] = path
            self.parent_paths[name] = paths

        self.parent_payloads: dict[str, dict[str, dict[str, Any]]] = {}
        self.parent_hashes: dict[str, dict[str, str]] = {}
        for name, paths in self.parent_paths.items():
            payloads: dict[str, dict[str, Any]] = {}
            hashes: dict[str, str] = {}
            for field, path in paths.items():
                kind = field.removesuffix("_path")
                payloads[kind] = _load_json(path, f"{name}_{kind}")
                hashes[kind] = _hash_file(path)
            self.parent_payloads[name] = payloads
            self.parent_hashes[name] = hashes

    def validate(self) -> dict[str, Any]:
        """Return aggregate activation-readiness evidence without side effects."""
        return self.evaluate_proposal(self.proposal, proposal_sha256=self.proposal_sha256)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        proposal_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory proposal without persistence or external effects."""
        format_reasons, hold_reasons = self._validate_inputs(proposal)
        if proposal_sha256 is None:
            proposal_sha256 = _hash_bytes(_canonical(dict(proposal))) if isinstance(proposal, Mapping) else None
        reason_codes = list(dict.fromkeys(format_reasons + hold_reasons))
        if not hold_reasons:
            hold_reasons.append("federation_activation_readiness_hold_reason_missing")
            reason_codes.append("federation_activation_readiness_hold_reason_missing")

        proposal_validated = not format_reasons
        safe_hold = (
            isinstance(proposal, Mapping)
            and proposal.get("readiness_decision") == EXPECTED_DECISION
            and proposal.get("activation_ready") is False
            and proposal.get("all_prerequisites_satisfied") is False
            and proposal.get("endpoint_identity_record_admitted") is False
            and proposal.get("real_endpoint_identity_supplied") is False
            and proposal.get("separate_activation_authorization_admitted") is False
            and proposal.get("external_endpoint_allowlist_admitted") is False
            and proposal.get("network_contacted") is False
            and proposal.get("network_write_authorized") is False
            and proposal.get("activation_performed") is False
            and proposal.get("deployment_changed") is False
            and proposal.get("automatic_activation") is False
            and proposal.get("automatic_retry") is False
            and proposal.get("automatic_reauthorization") is False
            and proposal.get("raw_child_receipts_retained") is False
            and proposal.get("raw_proposal_persisted") is False
        )
        preflight_pass = proposal_validated and bool(hold_reasons) and safe_hold
        if not safe_hold:
            reason_codes.append("federation_activation_readiness_safe_hold_violated")
            preflight_pass = False
        if not proposal_validated:
            preflight_pass = False

        return {
            "preflight_pass": preflight_pass,
            "proposal_validated": proposal_validated,
            "activation_readiness_preflight_pass": preflight_pass,
            "readiness_decision": EXPECTED_DECISION,
            "activation_ready": False,
            "safe_hold": safe_hold,
            "all_prerequisites_satisfied": False,
            "readiness_request_id": proposal.get("readiness_request_id") if isinstance(proposal, Mapping) else None,
            "request_status": proposal.get("request_status") if isinstance(proposal, Mapping) else None,
            "evaluation_mode": proposal.get("evaluation_mode") if isinstance(proposal, Mapping) else None,
            "authority_scope": proposal.get("authority_scope") if isinstance(proposal, Mapping) else None,
            "next_lifecycle_state": proposal.get("next_lifecycle_state") if isinstance(proposal, Mapping) else None,
            "proposal_sha256": proposal_sha256,
            "activation_readiness_contract_sha256": self.contract_sha256,
            "baseline_readiness_receipt_sha256": self.parent_hashes["baseline_readiness"]["preflight_receipt"],
            "operator_endpoint_record_receipt_sha256": self.parent_hashes["operator_endpoint_record"]["preflight_receipt"],
            "activation_authorization_record_receipt_sha256": self.parent_hashes["activation_authorization_record"]["preflight_receipt"],
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "missing_prerequisites": list(EXPECTED_MISSING),
            "parent_inputs_bound": not any(
                reason.endswith("_hash_mismatch") or reason.endswith("_path_mismatch") for reason in reason_codes
            ),
            "parent_inputs_verified": not any(
                reason.endswith("_status_mismatch") or reason.endswith("_decision_mismatch") for reason in reason_codes
            ),
            "endpoint_identity_record_admitted": False,
            "real_endpoint_identity_supplied": False,
            "separate_activation_authorization_admitted": False,
            "external_endpoint_allowlist_admitted": False,
            "network_contacted": False,
            "network_write_authorized": False,
            "activation_performed": False,
            "deployment_changed": False,
            "automatic_activation": False,
            "automatic_retry": False,
            "automatic_reauthorization": False,
            "raw_child_receipts_retained": False,
            "raw_proposal_persisted": False,
        }

    def _validate_inputs(self, proposal: Mapping[str, Any] | Any) -> tuple[list[str], list[str]]:
        format_reasons: list[str] = []
        hold_reasons: list[str] = []
        contract = self.contract
        parent_inputs = contract.get("parent_inputs")
        required_missing = contract.get("required_missing_prerequisites")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("federation_activation_readiness_contract_schema_mismatch")
        if not isinstance(parent_inputs, Mapping):
            format_reasons.append("federation_activation_readiness_parent_section_invalid")
            parent_inputs = {}
        if not isinstance(required_missing, list) or tuple(required_missing) != EXPECTED_MISSING:
            format_reasons.append("federation_activation_readiness_required_missing_invalid")
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("federation_activation_readiness_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("federation_activation_readiness_implementation_invalid")
            implementation = {}

        field_maps = {
            "baseline_readiness": {
                "contract_path": "contract_path",
                "contract_sha256": "contract",
                "proposal_path": "proposal_path",
                "proposal_sha256": "proposal",
                "preflight_receipt_path": "preflight_receipt_path",
                "preflight_receipt_sha256": "preflight_receipt",
            },
            "operator_endpoint_record": {
                "contract_path": "contract_path",
                "contract_sha256": "contract",
                "record_path": "record_path",
                "record_sha256": "record",
                "preflight_receipt_path": "preflight_receipt_path",
                "preflight_receipt_sha256": "preflight_receipt",
            },
            "activation_authorization_record": {
                "contract_path": "contract_path",
                "contract_sha256": "contract",
                "record_path": "record_path",
                "record_sha256": "record",
                "preflight_receipt_path": "preflight_receipt_path",
                "preflight_receipt_sha256": "preflight_receipt",
            },
        }
        for name, mapping in field_maps.items():
            section = parent_inputs.get(name)
            if not isinstance(section, Mapping):
                format_reasons.append(f"{name}_parent_section_invalid")
                continue
            for expected_field, actual_field in mapping.items():
                if expected_field.endswith("_path"):
                    actual_path = self.parent_paths[name][expected_field]
                    if _resolve_repo_path(section.get(expected_field)) != actual_path:
                        format_reasons.append(f"{name}_{expected_field}_mismatch")
                else:
                    actual_hash = self.parent_hashes[name][actual_field]
                    if section.get(expected_field) != actual_hash:
                        format_reasons.append(f"{name}_{expected_field}_mismatch")

        expected_parent_states = {
            "baseline_readiness": (
                "FEDERATION_READINESS_PREFLIGHT_PASS_SAFE_HOLD",
                "HOLD",
                "readiness_decision",
            ),
            "operator_endpoint_record": (
                "OPERATOR_ENDPOINT_RECORD_INTAKE_PREFLIGHT_PASS_MISSING",
                "HOLD_MISSING_OPERATOR_ENDPOINT_IDENTITY",
                "decision",
            ),
            "activation_authorization_record": (
                "ACTIVATION_AUTHORIZATION_RECORD_INTAKE_PREFLIGHT_PASS_MISSING",
                "HOLD_MISSING_SEPARATE_ACTIVATION_AUTHORIZATION",
                "decision",
            ),
        }
        for name, (expected_status, expected_decision, decision_key) in expected_parent_states.items():
            receipt = self.parent_payloads[name]["preflight_receipt"]
            if receipt.get("status") != expected_status:
                format_reasons.append(f"{name}_preflight_status_mismatch")
            if receipt.get("preflight_result", {}).get(decision_key) != expected_decision:
                format_reasons.append(f"{name}_preflight_decision_mismatch")

        baseline_result = self.parent_payloads["baseline_readiness"]["preflight_receipt"].get("preflight_result", {})
        endpoint_result = self.parent_payloads["operator_endpoint_record"]["preflight_receipt"].get("preflight_result", {})
        authorization_result = self.parent_payloads["activation_authorization_record"]["preflight_receipt"].get(
            "preflight_result", {}
        )
        if baseline_result.get("safe_hold") is not True or baseline_result.get("all_prerequisites_satisfied") is not False:
            format_reasons.append("baseline_readiness_state_not_closed")
        if endpoint_result.get("record_admitted") is not False or endpoint_result.get("identity_complete") is not False:
            format_reasons.append("operator_endpoint_record_state_not_closed")
        if authorization_result.get("authorization_admitted") is not False or authorization_result.get("authorization_valid") is not False:
            format_reasons.append("activation_authorization_record_state_not_closed")

        for field in (
            "network_sender",
            "dns_resolver",
            "certificate_fetcher",
            "filesystem_writer",
            "authorization_signer",
            "activation_capability",
            "deployment_capability",
            "reauthorization_capability",
        ):
            if implementation.get(field) is not False:
                format_reasons.append(f"federation_activation_readiness_{field}_forbidden")

        if not isinstance(proposal, Mapping):
            format_reasons.append("federation_activation_readiness_proposal_must_be_object")
            return list(dict.fromkeys(format_reasons)), hold_reasons

        if proposal.get("schema_version") != READINESS_SCHEMA_VERSION:
            format_reasons.append("federation_activation_readiness_proposal_schema_mismatch")
        if proposal.get("request_status") != closed_fixture.get("request_status", EXPECTED_REQUEST_STATUS):
            format_reasons.append("federation_activation_readiness_request_status_invalid")
        if proposal.get("evaluation_mode") != closed_fixture.get("evaluation_mode", EXPECTED_EVALUATION_MODE):
            format_reasons.append("federation_activation_readiness_evaluation_mode_invalid")
        if proposal.get("authority_scope") != closed_fixture.get("authority_scope", EXPECTED_SCOPE):
            format_reasons.append("federation_activation_readiness_scope_invalid")
        for field, parent_name in (
            ("baseline_readiness_receipt_sha256", "baseline_readiness"),
            ("operator_endpoint_record_receipt_sha256", "operator_endpoint_record"),
            ("activation_authorization_record_receipt_sha256", "activation_authorization_record"),
        ):
            if proposal.get(field) != self.parent_hashes[parent_name]["preflight_receipt"]:
                format_reasons.append(f"proposal_{field}_mismatch")
        if proposal.get("readiness_decision") != closed_fixture.get("readiness_decision", EXPECTED_DECISION):
            format_reasons.append("federation_activation_readiness_decision_invalid")
        if proposal.get("activation_ready") is not False:
            format_reasons.append("federation_activation_readiness_activation_ready_must_be_false_in_fixture")
        if proposal.get("all_prerequisites_satisfied") is not False:
            format_reasons.append("federation_activation_readiness_all_prerequisites_satisfied_must_be_false_in_fixture")
        if proposal.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("federation_activation_readiness_next_lifecycle_state_invalid")
        if tuple(proposal.get("missing_prerequisites", [])) != EXPECTED_MISSING:
            format_reasons.append("federation_activation_readiness_missing_prerequisites_invalid")
        for field in (
            "endpoint_identity_record_admitted",
            "real_endpoint_identity_supplied",
            "separate_activation_authorization_admitted",
            "external_endpoint_allowlist_admitted",
            "network_contacted",
            "network_write_authorized",
            "activation_performed",
            "deployment_changed",
            "automatic_activation",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_child_receipts_retained",
            "raw_proposal_persisted",
        ):
            if proposal.get(field) is not False:
                format_reasons.append(f"federation_activation_readiness_{field}_must_be_false_in_fixture")

        hold_reasons.extend(EXPECTED_MISSING)
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(hold_reasons))


__all__ = [
    "DEFAULT_ACTIVATION_READINESS_CONTRACT",
    "DEFAULT_ACTIVATION_READINESS_PROPOSAL",
    "FederationActivationReadinessError",
    "FederationActivationReadinessValidator",
]
