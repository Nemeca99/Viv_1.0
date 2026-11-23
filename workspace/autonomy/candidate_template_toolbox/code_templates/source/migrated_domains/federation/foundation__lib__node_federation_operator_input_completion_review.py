"""Read-only completion review for the federation operator-input bundle.

This gate does not create the missing endpoint identity or activation
authorization.  It verifies that the existing bundle hold, completion
contract, and operator request are mutually consistent, then reports the
exact missing inputs.  It cannot discover, contact, sign, admit, activate,
deploy, retry, reauthorize, or write anything.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .node_federation_operator_input_bundle import FederationOperatorInputBundleValidator


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
DEFAULT_REVIEW_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_OPERATOR_INPUT_COMPLETION_REVIEW_CONTRACT.json"
)
DEFAULT_COMPLETION_REQUEST = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_OPERATOR_INPUT_COMPLETION_REQUEST.json"
)
CONTRACT_SCHEMA_VERSION = "viv_node_federation_operator_input_completion_review_contract_v1"
REQUEST_SCHEMA_VERSION = "viv_node_federation_operator_input_completion_request_v1"
EXPECTED_CONTRACT_STATUS = "CLOSED_OPERATOR_INPUT_COMPLETION_REVIEW"
EXPECTED_REQUEST_STATUS = "OPERATOR_INPUT_REQUIRED"
EXPECTED_SOURCE = "OPERATOR_SUPPLIED_REQUIRED"
EXPECTED_NEXT_STATE = "OPERATOR_INPUT_REQUIRED"
EXPECTED_DECISION = "HOLD_OPERATOR_INPUT_REQUIRED"
REQUIRED_ENDPOINT_FIELDS = (
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
EXPECTED_MISSING_COMPONENTS = (
    "operator_endpoint_identity_record",
    "real_endpoint_identity",
    "separate_activation_authorization",
)
CLOSED_FALSE_FIELDS = (
    "bundle_complete",
    "bundle_valid",
    "bundle_admitted",
    "safe_hold",
    "automatic_completion",
    "network_contacted",
    "activation_performed",
    "deployment_changed",
    "raw_child_records_persisted",
)


class OperatorInputCompletionReviewError(ValueError):
    """Raised when completion-review inputs cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise OperatorInputCompletionReviewError(f"operator_input_completion_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorInputCompletionReviewError(f"operator_input_completion_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise OperatorInputCompletionReviewError(f"operator_input_completion_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationOperatorInputCompletionReviewValidator:
    """Review the exact operator inputs required to leave the bundle hold."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_REVIEW_CONTRACT,
        request_path: Path = DEFAULT_COMPLETION_REQUEST,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.request_path = Path(request_path)
        self.contract = _load_json(self.contract_path, "review_contract")
        self.request = _load_json(self.request_path, "completion_request")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.request_sha256 = _hash_file(self.request_path)
        parent = self.contract.get("parent_bundle_gate")
        if not isinstance(parent, Mapping):
            raise OperatorInputCompletionReviewError("operator_input_completion_parent_bundle_section_missing")
        self.parent_paths: dict[str, Path] = {}
        for field in ("contract_path", "bundle_path", "receipt_path"):
            path = _resolve_repo_path(parent.get(field))
            if path is None:
                raise OperatorInputCompletionReviewError(f"operator_input_completion_parent_{field}_invalid")
            self.parent_paths[field] = path
        self.parent_payloads = {
            field.removesuffix("_path"): _load_json(path, f"parent_{field.removesuffix('_path')}")
            for field, path in self.parent_paths.items()
        }
        self.parent_hashes = {
            field.removesuffix("_path"): _hash_file(path) for field, path in self.parent_paths.items()
        }
        self.bundle_validator = FederationOperatorInputBundleValidator()

    def validate(self) -> dict[str, Any]:
        """Return aggregate completion evidence without persistence or external effects."""
        return self.evaluate_request(self.request, request_sha256=self.request_sha256)

    def evaluate_request(
        self,
        request: Mapping[str, Any] | Any,
        *,
        request_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory request without persistence or external effects."""
        format_reasons = self._validate_contract()
        hold_reasons: list[str] = []
        if request_sha256 is None:
            request_sha256 = _hash_bytes(_canonical(dict(request))) if isinstance(request, Mapping) else None

        bundle_result = self.bundle_validator.validate()
        if not bundle_result.get("preflight_pass"):
            format_reasons.append("parent_bundle_gate_preflight_invalid")
        if bundle_result.get("decision") != "HOLD_MISSING_OPERATOR_INPUT_BUNDLE":
            format_reasons.append("parent_bundle_gate_decision_mismatch")
        if bundle_result.get("safe_hold") is not True:
            format_reasons.append("parent_bundle_gate_safe_hold_mismatch")
        if bundle_result.get("bundle_present") is not False or bundle_result.get("bundle_admitted") is not False:
            format_reasons.append("parent_bundle_gate_state_not_closed")

        if not isinstance(request, Mapping):
            format_reasons.append("operator_input_completion_request_must_be_object")
        else:
            if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
                format_reasons.append("operator_input_completion_request_schema_mismatch")
            if request.get("request_status") != EXPECTED_REQUEST_STATUS:
                format_reasons.append("operator_input_completion_request_status_invalid")
            if request.get("request_source") != EXPECTED_SOURCE:
                format_reasons.append("operator_input_completion_request_source_invalid")
            if request.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
                format_reasons.append("operator_input_completion_request_next_state_invalid")
            if request.get("contract_path") != self.contract.get("contract_path", self._relative(self.contract_path)):
                format_reasons.append("operator_input_completion_request_contract_path_mismatch")
            if request.get("contract_sha256") != self.contract_sha256:
                format_reasons.append("operator_input_completion_request_contract_sha256_mismatch")
            if request.get("parent_bundle_receipt_sha256") != self.parent_hashes["receipt"]:
                format_reasons.append("operator_input_completion_request_parent_receipt_sha256_mismatch")
            if request.get("missing_components") != list(EXPECTED_MISSING_COMPONENTS):
                format_reasons.append("operator_input_completion_request_missing_components_invalid")
            self._validate_request_section(
                request,
                "endpoint_identity",
                REQUIRED_ENDPOINT_FIELDS,
                "MISSING_OPERATOR_ENDPOINT_IDENTITY",
                format_reasons,
            )
            self._validate_request_section(
                request,
                "activation_authorization",
                REQUIRED_AUTHORIZATION_FIELDS,
                "MISSING_SEPARATE_ACTIVATION_AUTHORIZATION",
                format_reasons,
            )
            for field in CLOSED_FALSE_FIELDS:
                expected = self.contract.get("closed_fixture", {}).get(field)
                if request.get(field) is not expected:
                    format_reasons.append(f"operator_input_completion_request_{field}_invalid")
            if request.get("operator_input_required") is not True:
                format_reasons.append("operator_input_completion_request_operator_input_required_invalid")

        hold_reasons.extend(EXPECTED_MISSING_COMPONENTS)
        hold_reasons.append("operator_input_completion_required")
        reason_codes = list(dict.fromkeys(format_reasons + hold_reasons))
        safe_hold = (
            isinstance(request, Mapping)
            and request.get("request_status") == EXPECTED_REQUEST_STATUS
            and request.get("operator_input_required") is True
            and all(request.get(field) is False for field in CLOSED_FALSE_FIELDS if field != "safe_hold")
            and request.get("safe_hold") is True
        )
        review_validated = not format_reasons
        preflight_pass = review_validated and bool(hold_reasons) and safe_hold
        if not safe_hold:
            reason_codes.append("operator_input_completion_safe_hold_violated")
            preflight_pass = False

        return {
            "preflight_pass": preflight_pass,
            "completion_review_preflight_pass": preflight_pass,
            "review_validated": review_validated,
            "decision": EXPECTED_DECISION,
            "safe_hold": safe_hold,
            "request_id": request.get("request_id") if isinstance(request, Mapping) else None,
            "request_status": request.get("request_status") if isinstance(request, Mapping) else None,
            "request_source": request.get("request_source") if isinstance(request, Mapping) else None,
            "contract_sha256": self.contract_sha256,
            "request_sha256": request_sha256,
            "parent_bundle_contract_sha256": self.parent_hashes["contract"],
            "parent_bundle_sha256": self.parent_hashes["bundle"],
            "parent_bundle_receipt_sha256": self.parent_hashes["receipt"],
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "operator_input_required": True,
            "bundle_complete": False,
            "bundle_valid": False,
            "bundle_admitted": False,
            "missing_components": list(EXPECTED_MISSING_COMPONENTS),
            "missing_endpoint_identity_fields": list(REQUIRED_ENDPOINT_FIELDS),
            "missing_authorization_fields": list(REQUIRED_AUTHORIZATION_FIELDS),
            "endpoint_identity_values_supplied": False,
            "activation_authorization_values_supplied": False,
            "network_contacted": False,
            "activation_performed": False,
            "deployment_changed": False,
            "automatic_completion": False,
            "raw_child_records_persisted": False,
            "parent_bundle_gate_validated": bundle_result.get("preflight_pass") is True,
            "parent_bundle_gate_safe_hold": bundle_result.get("safe_hold") is True,
        }

    def _validate_contract(self) -> list[str]:
        reasons: list[str] = []
        contract = self.contract
        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            reasons.append("operator_input_completion_contract_schema_mismatch")
        if contract.get("status") != EXPECTED_CONTRACT_STATUS:
            reasons.append("operator_input_completion_contract_status_invalid")
        parent = contract.get("parent_bundle_gate")
        if not isinstance(parent, Mapping):
            reasons.append("operator_input_completion_parent_bundle_section_invalid")
            parent = {}
        for field, hash_field in (
            ("contract_path", "contract_sha256"),
            ("bundle_path", "bundle_sha256"),
            ("receipt_path", "receipt_sha256"),
        ):
            if _resolve_repo_path(parent.get(field)) != self.parent_paths.get(field):
                reasons.append(f"operator_input_completion_parent_{field}_mismatch")
            if parent.get(hash_field) != self.parent_hashes.get(field.removesuffix("_path")):
                reasons.append(f"operator_input_completion_parent_{hash_field}_mismatch")
        receipt = self.parent_payloads["receipt"]
        if receipt.get("status") != parent.get("required_receipt_status"):
            reasons.append("operator_input_completion_parent_receipt_status_mismatch")
        result = receipt.get("preflight_result", {})
        if result.get("decision") != parent.get("required_decision"):
            reasons.append("operator_input_completion_parent_receipt_decision_mismatch")
        if result.get("safe_hold") is not parent.get("required_safe_hold"):
            reasons.append("operator_input_completion_parent_receipt_safe_hold_mismatch")

        inputs = contract.get("required_operator_inputs")
        if not isinstance(inputs, Mapping):
            reasons.append("operator_input_completion_required_inputs_invalid")
            inputs = {}
        self._validate_contract_input_section(
            inputs.get("endpoint_identity"),
            "endpoint_identity",
            REQUIRED_ENDPOINT_FIELDS,
            reasons,
        )
        self._validate_contract_input_section(
            inputs.get("activation_authorization"),
            "activation_authorization",
            REQUIRED_AUTHORIZATION_FIELDS,
            reasons,
        )

        rules = contract.get("review_rules")
        if not isinstance(rules, Mapping):
            reasons.append("operator_input_completion_review_rules_invalid")
            rules = {}
        for field in (
            "automatic_completion",
            "automatic_discovery",
            "automatic_signing",
            "automatic_admission",
            "network_contact",
            "activation",
            "deployment",
            "raw_child_record_persistence",
        ):
            if rules.get(field) is not False:
                reasons.append(f"operator_input_completion_review_rule_{field}_forbidden")

        implementation = contract.get("implementation")
        if not isinstance(implementation, Mapping):
            reasons.append("operator_input_completion_implementation_invalid")
            implementation = {}
        for field in (
            "network_sender",
            "dns_resolver",
            "certificate_fetcher",
            "socket_opener",
            "subprocess_runner",
            "filesystem_writer",
            "automatic_completion_capability",
            "authorization_signer",
            "bundle_admission_capability",
            "activation_capability",
            "deployment_capability",
            "reauthorization_capability",
        ):
            if implementation.get(field) is not False:
                reasons.append(f"operator_input_completion_implementation_{field}_forbidden")
        return list(dict.fromkeys(reasons))

    def _validate_contract_input_section(
        self,
        section: Any,
        name: str,
        required_fields: tuple[str, ...],
        reasons: list[str],
    ) -> None:
        if not isinstance(section, Mapping):
            reasons.append(f"operator_input_completion_{name}_contract_section_invalid")
            return
        if section.get("source") != EXPECTED_SOURCE:
            reasons.append(f"operator_input_completion_{name}_source_invalid")
        if not isinstance(section.get("required_fields"), list) or tuple(section["required_fields"]) != required_fields:
            reasons.append(f"operator_input_completion_{name}_required_fields_invalid")

    def _validate_request_section(
        self,
        request: Mapping[str, Any],
        name: str,
        required_fields: tuple[str, ...],
        expected_state: str,
        reasons: list[str],
    ) -> None:
        section = request.get(name)
        contract_section = self.contract.get("required_operator_inputs", {}).get(name, {})
        if not isinstance(section, Mapping):
            reasons.append(f"operator_input_completion_request_{name}_section_invalid")
            return
        if section.get("record_path") != contract_section.get("record_path"):
            reasons.append(f"operator_input_completion_request_{name}_record_path_mismatch")
        if section.get("current_state") != expected_state:
            reasons.append(f"operator_input_completion_request_{name}_state_invalid")
        if section.get("required_fields") != list(required_fields):
            reasons.append(f"operator_input_completion_request_{name}_required_fields_invalid")
        if section.get("values_supplied") is not False:
            reasons.append(f"operator_input_completion_request_{name}_values_supplied_invalid")

    @staticmethod
    def _relative(path: Path) -> str:
        try:
            return path.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError:
            return path.as_posix()


__all__ = [
    "DEFAULT_COMPLETION_REQUEST",
    "DEFAULT_REVIEW_CONTRACT",
    "FederationOperatorInputCompletionReviewValidator",
    "OperatorInputCompletionReviewError",
]
