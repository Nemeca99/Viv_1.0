"""Read-only validation for one explicit Viv federation deployment record.

This module is a record and policy gate, not a deployment client.  It loads a
hash-pinned record, binds it to the existing offline endpoint policy, and
returns aggregate evidence.  It has no socket, DNS, subprocess, activation,
or filesystem-write capability.  The current fixture deliberately describes
an external TEST-NET endpoint so the lifecycle can be exercised while the
external authority remains closed.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from lib.node_federation_deployment_policy import (
    DEFAULT_ALLOWLIST,
    DEFAULT_POLICY_CONTRACT,
    EXTERNAL,
    FederationDeploymentPolicy,
    READ_ONLY_POLICY_REHEARSAL,
)


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
DEFAULT_RECORD = FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_DEPLOYMENT_RECORD.json"
DEFAULT_RECORD_CONTRACT = (
    FOUNDATION_ROOT / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_DEPLOYMENT_RECORD_CONTRACT.json"
)
RECORD_SCHEMA_VERSION = "viv_node_federation_deployment_record_v1"
RECORD_CONTRACT_SCHEMA_VERSION = "viv_node_federation_deployment_record_contract_v1"
EXPECTED_RECORD_STATUS = "PROPOSED_EXTERNAL_DENIED_TEST_FIXTURE"
EXPECTED_FIXTURE_SCOPE = "RESERVED_TEST_NET_NO_CONTACT"
EXPECTED_TEST_NET_HOST = "203.0.113.10"
EXPECTED_TEST_NET_SERVER_NAME = "master.viv.test"
EXPECTED_ENDPOINT_CLASS = EXTERNAL
EXPECTED_EVALUATION_MODE = READ_ONLY_POLICY_REHEARSAL
EXPECTED_PORT = 54443
EXPECTED_NEXT_LIFECYCLE_STATE = "POLICY_REVIEW"
EXPECTED_EXTERNAL_DENIAL = "external_endpoint_policy_closed"
FORBIDDEN_IMPORTS = frozenset({"socket", "ssl", "subprocess", "requests", "urllib", "httpx"})


class DeploymentRecordError(ValueError):
    """Raised when a deployment record or its contract cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise DeploymentRecordError(f"deployment_record_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeploymentRecordError(f"deployment_record_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise DeploymentRecordError(f"deployment_record_{label}_must_be_object:{path}")
    return value


def _resolve_declared_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


class FederationDeploymentRecordValidator:
    """Validate one proposed record against the closed deployment policy."""

    def __init__(
        self,
        *,
        record_path: Path = DEFAULT_RECORD,
        contract_path: Path = DEFAULT_RECORD_CONTRACT,
        policy: FederationDeploymentPolicy | None = None,
    ) -> None:
        self.record_path = Path(record_path)
        self.contract_path = Path(contract_path)
        self.record = _load_json(self.record_path, "record")
        self.contract = _load_json(self.contract_path, "record_contract")
        self.record_sha256 = _hash_file(self.record_path)
        self.contract_sha256 = _hash_file(self.contract_path)
        self.policy = policy or FederationDeploymentPolicy(
            contract_path=DEFAULT_POLICY_CONTRACT,
            allowlist_path=DEFAULT_ALLOWLIST,
        )

    def validate(self) -> dict[str, Any]:
        """Return a content-minimized preflight receipt for the file-backed record."""
        return self.evaluate_record(self.record, record_sha256=self.record_sha256)

    def evaluate_record(
        self,
        record: Mapping[str, Any] | Any,
        *,
        record_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate an in-memory candidate without persisting or contacting it."""
        structural_reasons = self._validate_contract_and_record(record)
        if record_sha256 is None:
            record_sha256 = _hash_bytes(_canonical(dict(record))) if isinstance(record, Mapping) else None

        policy_result = self.policy.evaluate(record)
        reason_codes = list(structural_reasons)
        reason_codes.extend(str(item) for item in policy_result.get("reason_codes", []))
        reason_codes = list(dict.fromkeys(reason_codes))

        policy_denied = policy_result.get("accepted") is False
        expected_external_denial = EXPECTED_EXTERNAL_DENIAL in reason_codes
        contact_closed = policy_result.get("network_contacted") is False
        writes_closed = policy_result.get("network_write_authorized") is False
        deployment_unchanged = policy_result.get("deployment_changed") is False
        raw_record_not_persisted = policy_result.get("raw_proposal_persisted") is False
        record_validated = not structural_reasons
        preflight_pass = all(
            (
                record_validated,
                policy_denied,
                expected_external_denial,
                contact_closed,
                writes_closed,
                deployment_unchanged,
                raw_record_not_persisted,
            )
        )
        if not policy_denied:
            reason_codes.append("external_policy_unexpectedly_allowed")
            preflight_pass = False
        if not expected_external_denial:
            reason_codes.append("expected_external_policy_denial_missing")
            preflight_pass = False
        if not contact_closed:
            reason_codes.append("external_endpoint_contact_not_closed")
            preflight_pass = False
        if not writes_closed:
            reason_codes.append("network_write_authority_not_closed")
            preflight_pass = False

        record_id = record.get("record_id") if isinstance(record, Mapping) else None
        record_status = record.get("record_status") if isinstance(record, Mapping) else None
        endpoint_id = record.get("endpoint_id") if isinstance(record, Mapping) else None
        endpoint_class = record.get("endpoint_class") if isinstance(record, Mapping) else None
        return {
            "preflight_pass": preflight_pass,
            "record_validated": record_validated,
            "record_id": record_id,
            "record_status": record_status,
            "next_lifecycle_state": (
                record.get("next_lifecycle_state") if isinstance(record, Mapping) else None
            ),
            "endpoint_id": endpoint_id,
            "endpoint_class": endpoint_class,
            "evaluation_mode": record.get("evaluation_mode") if isinstance(record, Mapping) else None,
            "fixture_scope": record.get("fixture_scope") if isinstance(record, Mapping) else None,
            "record_sha256": record_sha256,
            "record_contract_sha256": self.contract_sha256,
            "parent_policy_contract_sha256": self.policy.contract_sha256,
            "parent_policy_allowlist_sha256": self.policy.allowlist_sha256,
            "policy_decision": policy_result.get("decision"),
            "policy_proposal_sha256": policy_result.get("proposal_sha256"),
            "reason_codes": reason_codes,
            "expected_external_denial": expected_external_denial,
            "external_endpoint_contacted": policy_result.get("network_contacted") is True,
            "activation_allowed": (
                record.get("activation_allowed") is True if isinstance(record, Mapping) else False
            ),
            "deployment_authorized": (
                record.get("deployment_authorized") is True if isinstance(record, Mapping) else False
            ),
            "network_write_authorized": policy_result.get("network_write_authorized") is True,
            "deployment_changed": policy_result.get("deployment_changed") is True,
            "raw_record_persisted": policy_result.get("raw_proposal_persisted") is True,
            "raw_record_retained": False,
        }

    def _validate_contract_and_record(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        contract = self.contract
        if contract.get("schema_version") != RECORD_CONTRACT_SCHEMA_VERSION:
            reasons.append("record_contract_schema_mismatch")
        record_spec = contract.get("record")
        endpoint_spec = contract.get("endpoint")
        parent_policy = contract.get("parent_policy")
        implementation = contract.get("implementation")
        if not isinstance(record_spec, Mapping):
            reasons.append("record_contract_record_section_invalid")
            record_spec = {}
        if not isinstance(endpoint_spec, Mapping):
            reasons.append("record_contract_endpoint_section_invalid")
            endpoint_spec = {}
        if not isinstance(parent_policy, Mapping):
            reasons.append("record_contract_parent_policy_section_invalid")
            parent_policy = {}
        if not isinstance(implementation, Mapping):
            reasons.append("record_contract_implementation_section_invalid")
            implementation = {}

        if parent_policy.get("contract_sha256") != self.policy.contract_sha256:
            reasons.append("parent_policy_contract_hash_mismatch")
        if parent_policy.get("allowlist_sha256") != self.policy.allowlist_sha256:
            reasons.append("parent_policy_allowlist_hash_mismatch")
        declared_policy_contract = _resolve_declared_path(parent_policy.get("contract_path"))
        declared_allowlist = _resolve_declared_path(parent_policy.get("allowlist_path"))
        if declared_policy_contract is None or declared_policy_contract != Path(self.policy.contract_path).resolve():
            reasons.append("parent_policy_contract_path_mismatch")
        if declared_allowlist is None or declared_allowlist != Path(self.policy.allowlist_path).resolve():
            reasons.append("parent_policy_allowlist_path_mismatch")
        if implementation.get("network_sender") is not False:
            reasons.append("record_contract_network_sender_forbidden")
        if implementation.get("filesystem_writer") is not False:
            reasons.append("record_contract_filesystem_writer_forbidden")
        if implementation.get("activation_capability") is not False:
            reasons.append("record_contract_activation_capability_forbidden")

        if not isinstance(record, Mapping):
            reasons.append("deployment_record_must_be_object")
            return reasons
        if record.get("schema_version") != RECORD_SCHEMA_VERSION:
            reasons.append("deployment_record_schema_mismatch")
        if record.get("record_status") != record_spec.get("record_status_required", EXPECTED_RECORD_STATUS):
            reasons.append("deployment_record_status_not_proposed")
        if record.get("evaluation_mode") != EXPECTED_EVALUATION_MODE:
            reasons.append("deployment_record_evaluation_mode_invalid")
        if record.get("fixture_scope") != EXPECTED_FIXTURE_SCOPE:
            reasons.append("deployment_record_fixture_scope_invalid")
        if record.get("reserved_test_net_address") is not True:
            reasons.append("deployment_record_reserved_test_net_required")
        if record.get("endpoint_class") != endpoint_spec.get("endpoint_class", EXPECTED_ENDPOINT_CLASS):
            reasons.append("deployment_record_endpoint_class_mismatch")
        if record.get("host") != endpoint_spec.get("host", EXPECTED_TEST_NET_HOST):
            reasons.append("deployment_record_host_not_reserved_test_net")
        if record.get("tls_server_name") != endpoint_spec.get("tls_server_name", EXPECTED_TEST_NET_SERVER_NAME):
            reasons.append("deployment_record_tls_server_name_mismatch")
        if record.get("port") != endpoint_spec.get("port", EXPECTED_PORT):
            reasons.append("deployment_record_port_mismatch")
        if not isinstance(record.get("port"), int) or isinstance(record.get("port"), bool):
            reasons.append("deployment_record_port_invalid")
        if record.get("next_lifecycle_state") != EXPECTED_NEXT_LIFECYCLE_STATE:
            reasons.append("deployment_record_next_lifecycle_state_invalid")
        if record.get("endpoint_contact_allowed") != record_spec.get("endpoint_contact_allowed_required", False):
            reasons.append("deployment_record_endpoint_contact_must_be_closed")
        if record.get("activation_allowed") != record_spec.get("activation_allowed_required", False):
            reasons.append("deployment_record_activation_must_be_closed")
        if record.get("reserved_test_net_address") != record_spec.get("reserved_test_net_required", True):
            reasons.append("deployment_record_reserved_test_net_flag_mismatch")
        for field in (
            "training_authorized",
            "run_authorized",
            "promotion_authorized",
            "deployment_authorized",
            "network_write_authorized",
        ):
            if record.get(field) is not False:
                reasons.append(f"deployment_record_{field}_must_be_closed")
        return list(dict.fromkeys(reasons))


__all__ = [
    "DEFAULT_RECORD",
    "DEFAULT_RECORD_CONTRACT",
    "DeploymentRecordError",
    "FederationDeploymentRecordValidator",
]
