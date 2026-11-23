"""Strict, read-only intake gate for Viv's combined operator input bundle.

The bundle is a hash-bound manifest for two independently governed records:
the endpoint identity and the separate activation authorization.  An absent
bundle is an explicit safe hold.  This module cannot discover, contact, sign,
admit, activate, deploy, retry, reauthorize, or write anything.
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
DEFAULT_BUNDLE_CONTRACT = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_OPERATOR_INPUT_BUNDLE_CONTRACT.json"
)
DEFAULT_BUNDLE = FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_OPERATOR_INPUT_BUNDLE.json"
BUNDLE_SCHEMA_VERSION = "viv_node_federation_operator_input_bundle_v1"
CONTRACT_SCHEMA_VERSION = "viv_node_federation_operator_input_bundle_contract_v1"
EXPECTED_STATUS = "MISSING_OPERATOR_INPUT_BUNDLE"
EXPECTED_SOURCE = "OPERATOR_SUPPLIED_REQUIRED"
EXPECTED_NEXT_STATE = "MISSING_OPERATOR_INPUT_BUNDLE"
EXPECTED_DECISION = "HOLD_MISSING_OPERATOR_INPUT_BUNDLE"
REQUIRED_ENDPOINT_IDENTITY_FIELDS = (
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
    "bundle_present",
    "bundle_valid",
    "bundle_admitted",
    "endpoint_identity_record_present",
    "activation_authorization_record_present",
    "endpoint_identity_complete",
    "activation_authorization_complete",
    "components_consistent",
    "activation_readiness_satisfied",
    "network_contacted",
    "network_write_authorized",
    "activation_performed",
    "deployment_changed",
    "automatic_discovery",
    "automatic_activation",
    "automatic_retry",
    "automatic_reauthorization",
    "raw_child_records_persisted",
)


class OperatorInputBundleError(ValueError):
    """Raised when operator-input bundle files cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise OperatorInputBundleError(f"operator_input_bundle_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorInputBundleError(f"operator_input_bundle_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise OperatorInputBundleError(f"operator_input_bundle_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationOperatorInputBundleValidator:
    """Validate the explicit missing bundle without side effects."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_BUNDLE_CONTRACT,
        bundle_path: Path = DEFAULT_BUNDLE,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.bundle_path = Path(bundle_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.bundle = _load_json(self.bundle_path, "bundle")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.bundle_sha256 = _hash_file(self.bundle_path)
        parent_inputs = self.contract.get("parent_inputs")
        if not isinstance(parent_inputs, Mapping):
            raise OperatorInputBundleError("operator_input_bundle_parent_section_missing")

        self.parent_paths: dict[str, dict[str, Path]] = {}
        for name in ("activation_readiness", "operator_endpoint_record", "activation_authorization_record"):
            section = parent_inputs.get(name)
            if not isinstance(section, Mapping):
                raise OperatorInputBundleError(f"operator_input_bundle_{name}_section_invalid")
            paths: dict[str, Path] = {}
            fields = ("contract_path", "proposal_path", "preflight_receipt_path") if name == "activation_readiness" else (
                "contract_path",
                "record_path",
                "preflight_receipt_path",
            )
            for field in fields:
                path = _resolve_repo_path(section.get(field))
                if path is None:
                    raise OperatorInputBundleError(f"operator_input_bundle_{name}_{field}_invalid")
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
        """Return aggregate evidence for the missing or supplied bundle."""
        return self.evaluate_bundle(self.bundle, bundle_sha256=self.bundle_sha256)

    def evaluate_bundle(
        self,
        bundle: Mapping[str, Any] | Any,
        *,
        bundle_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory bundle without persistence or external effects."""
        format_reasons, hold_reasons = self._validate_inputs(bundle)
        if bundle_sha256 is None:
            bundle_sha256 = _hash_bytes(_canonical(dict(bundle))) if isinstance(bundle, Mapping) else None
        reason_codes = list(dict.fromkeys(format_reasons + hold_reasons))
        if not hold_reasons:
            hold_reasons.append("operator_input_bundle_hold_reason_missing")
            reason_codes.append("operator_input_bundle_hold_reason_missing")

        bundle_validated = not format_reasons
        safe_hold = (
            isinstance(bundle, Mapping)
            and bundle.get("bundle_status") == EXPECTED_STATUS
            and all(bundle.get(field) is False for field in CLOSED_FALSE_FIELDS)
        )
        preflight_pass = bundle_validated and bool(hold_reasons) and safe_hold
        if not safe_hold:
            reason_codes.append("operator_input_bundle_safe_hold_violated")
            preflight_pass = False
        if not bundle_validated:
            preflight_pass = False

        return {
            "preflight_pass": preflight_pass,
            "bundle_validated": bundle_validated,
            "bundle_intake_preflight_pass": preflight_pass,
            "decision": EXPECTED_DECISION,
            "safe_hold": safe_hold,
            "bundle_id": bundle.get("bundle_id") if isinstance(bundle, Mapping) else None,
            "bundle_status": bundle.get("bundle_status") if isinstance(bundle, Mapping) else None,
            "bundle_source": bundle.get("bundle_source") if isinstance(bundle, Mapping) else None,
            "bundle_sha256": bundle_sha256,
            "operator_input_bundle_contract_sha256": self.contract_sha256,
            "activation_readiness_receipt_sha256": self.parent_hashes["activation_readiness"]["preflight_receipt"],
            "endpoint_record_receipt_sha256": self.parent_hashes["operator_endpoint_record"]["preflight_receipt"],
            "activation_authorization_record_receipt_sha256": self.parent_hashes["activation_authorization_record"]["preflight_receipt"],
            "reason_codes": list(dict.fromkeys(reason_codes)),
            "missing_components": list(EXPECTED_MISSING_COMPONENTS),
            "missing_endpoint_identity_fields": list(REQUIRED_ENDPOINT_IDENTITY_FIELDS),
            "missing_authorization_fields": list(REQUIRED_AUTHORIZATION_FIELDS),
            "parent_inputs_bound": not any(
                reason.endswith("_hash_mismatch") or reason.endswith("_path_mismatch") for reason in reason_codes
            ),
            "parent_inputs_verified": not any(
                reason.endswith("_status_mismatch") or reason.endswith("_decision_mismatch") for reason in reason_codes
            ),
            "bundle_present": False,
            "bundle_valid": False,
            "bundle_admitted": False,
            "endpoint_identity_record_present": False,
            "activation_authorization_record_present": False,
            "endpoint_identity_complete": False,
            "activation_authorization_complete": False,
            "components_consistent": False,
            "activation_readiness_satisfied": False,
            "network_contacted": False,
            "network_write_authorized": False,
            "activation_performed": False,
            "deployment_changed": False,
            "raw_child_records_persisted": False,
            "raw_child_records_retained": False,
        }

    def _validate_inputs(self, bundle: Mapping[str, Any] | Any) -> tuple[list[str], list[str]]:
        format_reasons: list[str] = []
        hold_reasons: list[str] = []
        contract = self.contract
        parent_inputs = contract.get("parent_inputs")
        endpoint_fields = contract.get("required_endpoint_identity_fields")
        authorization_fields = contract.get("required_authorization_fields")
        closed_fixture = contract.get("closed_fixture")
        implementation = contract.get("implementation")

        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            format_reasons.append("operator_input_bundle_contract_schema_mismatch")
        if not isinstance(parent_inputs, Mapping):
            format_reasons.append("operator_input_bundle_parent_section_invalid")
            parent_inputs = {}
        if not isinstance(endpoint_fields, list) or tuple(endpoint_fields) != REQUIRED_ENDPOINT_IDENTITY_FIELDS:
            format_reasons.append("operator_input_bundle_endpoint_fields_invalid")
        if not isinstance(authorization_fields, list) or tuple(authorization_fields) != REQUIRED_AUTHORIZATION_FIELDS:
            format_reasons.append("operator_input_bundle_authorization_fields_invalid")
        if not isinstance(closed_fixture, Mapping):
            format_reasons.append("operator_input_bundle_closed_fixture_invalid")
            closed_fixture = {}
        if not isinstance(implementation, Mapping):
            format_reasons.append("operator_input_bundle_implementation_invalid")
            implementation = {}

        field_maps = {
            "activation_readiness": {
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
            "activation_readiness": (
                "FEDERATION_ACTIVATION_READINESS_PREFLIGHT_PASS_SAFE_HOLD",
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

        readiness_result = self.parent_payloads["activation_readiness"]["preflight_receipt"].get("preflight_result", {})
        endpoint_result = self.parent_payloads["operator_endpoint_record"]["preflight_receipt"].get("preflight_result", {})
        authorization_result = self.parent_payloads["activation_authorization_record"]["preflight_receipt"].get(
            "preflight_result", {}
        )
        if readiness_result.get("activation_ready") is not False or readiness_result.get("safe_hold") is not True:
            format_reasons.append("activation_readiness_state_not_closed")
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
            "bundle_admission_capability",
            "activation_capability",
            "deployment_capability",
            "reauthorization_capability",
        ):
            if implementation.get(field) is not False:
                format_reasons.append(f"operator_input_bundle_{field}_forbidden")

        if not isinstance(bundle, Mapping):
            format_reasons.append("operator_input_bundle_must_be_object")
            return list(dict.fromkeys(format_reasons)), hold_reasons

        if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            format_reasons.append("operator_input_bundle_schema_mismatch")
        if bundle.get("bundle_status") != closed_fixture.get("bundle_status", EXPECTED_STATUS):
            format_reasons.append("operator_input_bundle_status_invalid")
        if bundle.get("bundle_source") != closed_fixture.get("bundle_source", EXPECTED_SOURCE):
            format_reasons.append("operator_input_bundle_source_invalid")
        if bundle.get("next_lifecycle_state") != EXPECTED_NEXT_STATE:
            format_reasons.append("operator_input_bundle_next_lifecycle_state_invalid")
        for field, parent_name in (
            ("parent_activation_readiness_receipt_sha256", "activation_readiness"),
            ("endpoint_record_receipt_sha256", "operator_endpoint_record"),
            ("activation_authorization_record_receipt_sha256", "activation_authorization_record"),
        ):
            if bundle.get(field) != self.parent_hashes[parent_name]["preflight_receipt"]:
                format_reasons.append(f"operator_input_bundle_{field}_mismatch")
        for field in CLOSED_FALSE_FIELDS:
            if bundle.get(field) is not False:
                format_reasons.append(f"operator_input_bundle_{field}_must_be_false_in_fixture")

        hold_reasons.extend(EXPECTED_MISSING_COMPONENTS)
        hold_reasons.append("operator_input_bundle_missing")
        return list(dict.fromkeys(format_reasons)), list(dict.fromkeys(hold_reasons))


__all__ = [
    "DEFAULT_BUNDLE",
    "DEFAULT_BUNDLE_CONTRACT",
    "FederationOperatorInputBundleValidator",
    "OperatorInputBundleError",
]
