"""Read-only policy gate for the dedicated fixed-loopback Master rehearsal.

The validator never opens a socket or starts a listener.  It binds the fixed
port, host, parent receipt, and lifecycle flags before the separate bounded
test invokes the listener implementation.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .node_federation_loopback_endpoint_activation import (
    FederationLoopbackEndpointActivationValidator,
)


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
DEFAULT_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_FIXED_LOOPBACK_MASTER_LISTENER_CONTRACT.json"
)
DEFAULT_PROPOSAL = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_FIXED_LOOPBACK_MASTER_LISTENER_PROPOSAL.json"
)
DEFAULT_RECORD = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_FIXED_LOOPBACK_MASTER_LISTENER_RECORD.json"
)
DEFAULT_PARENT_RECEIPT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_LOOPBACK_ENDPOINT_ACTIVATION_STAGE_RECEIPT.json"
)

CONTRACT_SCHEMA_VERSION = "viv_node_federation_fixed_loopback_master_listener_contract_v1"
PROPOSAL_SCHEMA_VERSION = "viv_node_federation_fixed_loopback_master_listener_proposal_v1"
RECORD_SCHEMA_VERSION = "viv_node_federation_fixed_loopback_master_listener_record_v1"
EXPECTED_CONTRACT_STATUS = "CLOSED_FIXED_LOOPBACK_MASTER_LISTENER_REHEARSAL"
EXPECTED_PROPOSAL_STATUS = "AUTHORIZED_FIXED_LOOPBACK_MASTER_REHEARSAL"
EXPECTED_RECORD_STATUS = "AUTHORIZED_FIXED_LOOPBACK_MASTER_REHEARSAL"
EXPECTED_RECORD_SCOPE = "BOUNDED_LOCAL_ONLY"
EXPECTED_DECISION = "ALLOW_BOUNDED_FIXED_LOOPBACK_LISTENER_REHEARSAL"
EXPECTED_ENDPOINT_ID = "viv-fixed-loopback-master-rehearsal-001"
EXPECTED_ENDPOINT_CLASS = "FIXED_LOOPBACK_ONLY_TEST"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_PORT = 54443
EXPECTED_PORT_SELECTION = "fixed_allowlisted_loopback_port"
EXPECTED_TLS_SERVER_NAME = "localhost"
EXPECTED_TLS_VERSION = "TLSv1.3"
EXPECTED_AUTHORIZATION_SCOPE = "ONE_FIXED_127.0.0.1_54443_TLS13_MUTUAL_AUTH_SESSION"


class FixedLoopbackMasterListenerError(ValueError):
    """Raised when a fixed-loopback listener gate input cannot be loaded."""


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise FixedLoopbackMasterListenerError(f"fixed_loopback_file_unreadable:{path}") from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FixedLoopbackMasterListenerError(f"fixed_loopback_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise FixedLoopbackMasterListenerError(f"fixed_loopback_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _same_mapping(actual: Any, expected: Any) -> bool:
    return isinstance(actual, Mapping) and isinstance(expected, Mapping) and dict(actual) == dict(expected)


class FixedLoopbackMasterListenerValidator:
    """Validate one fixed 127.0.0.1:54443 listener rehearsal proposal."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_CONTRACT,
        proposal_path: Path = DEFAULT_PROPOSAL,
        record_path: Path = DEFAULT_RECORD,
        parent_receipt_path: Path = DEFAULT_PARENT_RECEIPT,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.record_path = Path(record_path)
        self.parent_receipt_path = Path(parent_receipt_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.record = _load_json(self.record_path, "record")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        self.record_sha256 = _hash_file(self.record_path)
        self.parent_receipt_sha256 = _hash_file(self.parent_receipt_path)
        self.parent_validator = FederationLoopbackEndpointActivationValidator()

    def validate(self) -> dict[str, Any]:
        return self.evaluate_proposal(self.proposal, record=self.record)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        record: Mapping[str, Any] | Any | None = None,
    ) -> dict[str, Any]:
        if record is None:
            record = self.record
        reasons: list[str] = []
        reasons.extend(self._validate_parent())
        reasons.extend(self._validate_contract(record))
        reasons.extend(self._validate_record(record))
        reasons.extend(self._validate_proposal(proposal, record))
        safe_to_run = self._safe_to_run(proposal, record, reasons)
        reason_codes = list(dict.fromkeys(reasons))
        if safe_to_run:
            reason_codes.append("bounded_fixed_loopback_listener_rehearsal_authorized")
        else:
            reason_codes.append("fixed_loopback_listener_safe_run_rejected")
        return {
            "preflight_pass": safe_to_run and not reasons,
            "fixed_loopback_listener_preflight_pass": safe_to_run and not reasons,
            "decision": EXPECTED_DECISION,
            "safe_to_run": safe_to_run,
            "local_loopback_only": self._local_loopback_shape(proposal, record),
            "endpoint_id": self._endpoint_value(record, "endpoint_id"),
            "endpoint_class": self._endpoint_value(record, "endpoint_class"),
            "host": self._endpoint_value(record, "host"),
            "port": self._endpoint_value(record, "port"),
            "port_selection": self._endpoint_value(record, "port_selection"),
            "tls_server_name": self._endpoint_value(record, "tls_server_name"),
            "tls_version": self._endpoint_value(record, "tls_version_minimum"),
            "contract_sha256": self.contract_sha256,
            "proposal_sha256": self.proposal_sha256,
            "record_sha256": self.record_sha256,
            "parent_receipt_sha256": self.parent_receipt_sha256,
            "parent_loopback_rehearsal_validated": self._parent_result.get("preflight_pass") is True,
            "parent_loopback_rehearsal_safe": self._parent_result.get("safe_to_run") is True,
            "parent_loopback_rehearsal_status": self._parent_receipt.get("status"),
            "socket_opened": self._bool_nested(proposal, "preflight_state", "socket_opened"),
            "listener_started": self._bool_nested(proposal, "preflight_state", "listener_started"),
            "external_network_contacted": False,
            "dns_resolved": False,
            "certificate_fetched": False,
            "session_completed": False,
            "listener_closed": False,
            "persistent_listener_started": False,
            "deployment_changed": False,
            "network_write_authorized": False,
            "production_endpoint_admitted": False,
            "automatic_retry": False,
            "automatic_reauthorization": False,
            "raw_payload_persisted": False,
            "private_key_persisted": False,
            "reason_codes": reason_codes,
        }

    @property
    def _parent_result(self) -> dict[str, Any]:
        return self.parent_validator.validate()

    @property
    def _parent_receipt(self) -> dict[str, Any]:
        return _load_json(self.parent_receipt_path, "parent_receipt")

    @staticmethod
    def _endpoint_value(record: Mapping[str, Any] | Any, field: str) -> Any:
        endpoint = record.get("endpoint") if isinstance(record, Mapping) else None
        return endpoint.get(field) if isinstance(endpoint, Mapping) else None

    @staticmethod
    def _bool_nested(value: Mapping[str, Any] | Any, section: str, field: str) -> bool | None:
        if not isinstance(value, Mapping):
            return None
        child = value.get(section)
        result = child.get(field) if isinstance(child, Mapping) else None
        return result if isinstance(result, bool) else None

    def _validate_parent(self) -> list[str]:
        reasons: list[str] = []
        result = self._parent_result
        receipt = self._parent_receipt
        if result.get("preflight_pass") is not True:
            reasons.append("parent_loopback_rehearsal_preflight_invalid")
        if result.get("safe_to_run") is not True:
            reasons.append("parent_loopback_rehearsal_safe_run_invalid")
        if receipt.get("status") != "LOOPBACK_ENDPOINT_ACTIVATION_REHEARSAL_PASS_EXTERNAL_CLOSED":
            reasons.append("parent_loopback_receipt_status_mismatch")
        authority = receipt.get("authority_after_receipt")
        if not isinstance(authority, Mapping) or authority.get("local_loopback_test_authorized") is not True:
            reasons.append("parent_loopback_receipt_local_loopback_authorization_mismatch")
        if isinstance(authority, Mapping) and authority.get("endpoint_contact_authorized") is not False:
            reasons.append("parent_loopback_receipt_endpoint_contact_authorization_mismatch")
        endpoint_rehearsal = receipt.get("endpoint_rehearsal")
        if not isinstance(endpoint_rehearsal, Mapping):
            reasons.append("parent_loopback_receipt_endpoint_section_invalid")
        else:
            if endpoint_rehearsal.get("external_network_contacted") is not False:
                reasons.append("parent_loopback_receipt_external_network_contacted_mismatch")
            if endpoint_rehearsal.get("persistent_listener_started") is not False:
                reasons.append("parent_loopback_receipt_persistent_listener_must_be_false")
        parent = self.contract.get("parent_loopback_rehearsal")
        if not isinstance(parent, Mapping):
            return reasons + ["fixed_loopback_contract_parent_invalid"]
        if _resolve_repo_path(parent.get("receipt_path")) != self.parent_receipt_path:
            reasons.append("fixed_loopback_parent_receipt_path_mismatch")
        if parent.get("receipt_sha256") != self.parent_receipt_sha256:
            reasons.append("fixed_loopback_parent_receipt_hash_mismatch")
        for field, expected in (
            ("required_status", "LOOPBACK_ENDPOINT_ACTIVATION_REHEARSAL_PASS_EXTERNAL_CLOSED"),
            ("required_local_loopback_test_authorized", True),
            ("required_external_network_contacted", False),
            ("required_persistent_listener_started", False),
        ):
            if parent.get(field) != expected:
                reasons.append(f"fixed_loopback_parent_{field}_mismatch")
        return reasons

    def _validate_contract(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        contract = self.contract
        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            reasons.append("fixed_loopback_contract_schema_mismatch")
        if contract.get("status") != EXPECTED_CONTRACT_STATUS:
            reasons.append("fixed_loopback_contract_status_invalid")
        section = contract.get("listener_record")
        if not isinstance(section, Mapping):
            reasons.append("fixed_loopback_contract_record_section_invalid")
        else:
            if _resolve_repo_path(section.get("path")) != self.record_path:
                reasons.append("fixed_loopback_contract_record_path_mismatch")
            if section.get("sha256") != self.record_sha256:
                reasons.append("fixed_loopback_contract_record_hash_mismatch")
            if section.get("required_status") != EXPECTED_RECORD_STATUS:
                reasons.append("fixed_loopback_contract_record_status_mismatch")
            if section.get("required_scope") != EXPECTED_RECORD_SCOPE:
                reasons.append("fixed_loopback_contract_record_scope_mismatch")
        proposal = contract.get("proposal")
        if not isinstance(proposal, Mapping):
            reasons.append("fixed_loopback_contract_proposal_section_invalid")
        elif _resolve_repo_path(proposal.get("path")) != self.proposal_path:
            reasons.append("fixed_loopback_contract_proposal_path_mismatch")
        endpoint = contract.get("endpoint_boundary")
        if not isinstance(endpoint, Mapping):
            reasons.append("fixed_loopback_contract_endpoint_invalid")
            endpoint = {}
        reasons.extend(self._validate_endpoint(endpoint, "contract_endpoint"))
        lifecycle = contract.get("lifecycle_scope")
        if not isinstance(lifecycle, Mapping):
            reasons.append("fixed_loopback_contract_lifecycle_invalid")
            lifecycle = {}
        for field in (
            "fixed_loopback_listener_rehearsal_authorized",
            "listener_may_bind_only_during_rehearsal",
            "one_session_only",
            "listener_closes_after_session",
            "socket_closed_before_receipt",
        ):
            if lifecycle.get(field) is not True:
                reasons.append(f"fixed_loopback_contract_{field}_must_be_true")
        for field in (
            "external_network_contacted",
            "endpoint_contact_authorized",
            "network_write_authorized",
            "production_endpoint_admitted",
            "deployment_changed",
            "live_runtime_module_installed",
            "persistent_daemon_installation",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_payload_persistence",
            "private_key_persistence",
        ):
            if lifecycle.get(field) is not False:
                reasons.append(f"fixed_loopback_contract_{field}_must_be_false")
        authority = contract.get("authority")
        if not isinstance(authority, Mapping):
            reasons.append("fixed_loopback_contract_authority_invalid")
        else:
            if authority.get("fixed_loopback_listener_rehearsal_authorized") is not True:
                reasons.append("fixed_loopback_contract_listener_authority_missing")
            for field in (
                "external_discovery_authorized",
                "endpoint_contact_authorized",
                "activation_authorized",
                "network_write_authorized",
                "deployment_authorized",
                "training_authorized",
                "run_authorized",
                "promotion_authorized",
                "live_runtime_module_installed",
                "global_aifl_writes",
                "master_s_n_mutation",
                "knowledge_admission",
            ):
                if authority.get(field) is not False:
                    reasons.append(f"fixed_loopback_contract_authority_{field}_must_be_false")
        return reasons

    def _validate_record(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        if not isinstance(record, Mapping):
            return ["fixed_loopback_record_must_be_object"]
        if record.get("schema_version") != RECORD_SCHEMA_VERSION:
            reasons.append("fixed_loopback_record_schema_mismatch")
        if record.get("status") != EXPECTED_RECORD_STATUS:
            reasons.append("fixed_loopback_record_status_invalid")
        if record.get("record_scope") != EXPECTED_RECORD_SCOPE:
            reasons.append("fixed_loopback_record_scope_invalid")
        endpoint = record.get("endpoint")
        if not isinstance(endpoint, Mapping):
            reasons.append("fixed_loopback_record_endpoint_invalid")
            endpoint = {}
        reasons.extend(self._validate_endpoint(endpoint, "record_endpoint"))
        parent = record.get("parent_loopback_rehearsal")
        if not isinstance(parent, Mapping):
            reasons.append("fixed_loopback_record_parent_invalid")
        elif parent.get("receipt_sha256") != self.parent_receipt_sha256:
            reasons.append("fixed_loopback_record_parent_receipt_hash_mismatch")
        authorization = record.get("operator_authorization")
        if not isinstance(authorization, Mapping):
            reasons.append("fixed_loopback_record_authorization_invalid")
        else:
            if authorization.get("fixed_loopback_listener_rehearsal_authorized") is not True:
                reasons.append("fixed_loopback_record_listener_authorization_missing")
            for field in (
                "external_network_authorized",
                "lan_network_authorized",
                "persistent_daemon_installation_authorized",
                "production_endpoint_admission_authorized",
                "automatic_retry_authorized",
                "automatic_reauthorization_authorized",
            ):
                if authorization.get(field) is not False:
                    reasons.append(f"fixed_loopback_record_authorization_{field}_must_be_false")
        lifecycle = record.get("lifecycle_boundary")
        if not isinstance(lifecycle, Mapping):
            reasons.append("fixed_loopback_record_lifecycle_invalid")
        else:
            for field in (
                "listener_may_bind_only_during_rehearsal",
                "one_session_only",
                "listener_closes_after_session",
                "socket_closed_before_receipt",
            ):
                if lifecycle.get(field) is not True:
                    reasons.append(f"fixed_loopback_record_{field}_must_be_true")
            for field in (
                "external_network_contacted",
                "network_write_authorized",
                "production_endpoint_admitted",
                "deployment_changed",
                "live_runtime_module_installed",
                "raw_payload_persisted",
                "private_key_persisted",
                "automatic_retry",
                "automatic_reauthorization",
            ):
                if lifecycle.get(field) is not False:
                    reasons.append(f"fixed_loopback_record_lifecycle_{field}_must_be_false")
        return reasons

    def _validate_endpoint(self, endpoint: Mapping[str, Any], prefix: str) -> list[str]:
        reasons: list[str] = []
        if endpoint.get("endpoint_id") != EXPECTED_ENDPOINT_ID:
            reasons.append(f"{prefix}_endpoint_id_invalid")
        if endpoint.get("endpoint_class") != EXPECTED_ENDPOINT_CLASS:
            reasons.append(f"{prefix}_endpoint_class_invalid")
        if endpoint.get("host") != EXPECTED_HOST:
            reasons.append(f"{prefix}_host_must_be_127_0_0_1")
        if endpoint.get("allowed_bind_addresses") != [EXPECTED_HOST]:
            reasons.append(f"{prefix}_allowed_bind_addresses_invalid")
        if endpoint.get("port") != EXPECTED_PORT:
            reasons.append(f"{prefix}_port_must_be_54443")
        if endpoint.get("port_selection") != EXPECTED_PORT_SELECTION:
            reasons.append(f"{prefix}_port_selection_invalid")
        if endpoint.get("allowed_fixed_port") != EXPECTED_PORT:
            reasons.append(f"{prefix}_allowed_fixed_port_invalid")
        if endpoint.get("tls_server_name") != EXPECTED_TLS_SERVER_NAME:
            reasons.append(f"{prefix}_tls_server_name_invalid")
        if endpoint.get("tls_version_minimum") != EXPECTED_TLS_VERSION:
            reasons.append(f"{prefix}_tls_version_minimum_invalid")
        if endpoint.get("tls_version_maximum") != EXPECTED_TLS_VERSION:
            reasons.append(f"{prefix}_tls_version_maximum_invalid")
        if endpoint.get("mutual_tls_required") is not True:
            reasons.append(f"{prefix}_mutual_tls_required_missing")
        if endpoint.get("application_signature_required") is not True:
            reasons.append(f"{prefix}_application_signature_required_missing")
        if endpoint.get("external_endpoint_allowlist") != []:
            reasons.append(f"{prefix}_external_allowlist_must_be_empty")
        for field in (
            "persistent_listener",
            "daemon_start",
            "lan_bind_allowed",
            "public_bind_allowed",
            "unrelated_listener_reuse_allowed",
        ):
            if endpoint.get(field) is not False:
                reasons.append(f"{prefix}_{field}_must_be_false")
        return reasons

    def _validate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        record: Mapping[str, Any] | Any,
    ) -> list[str]:
        reasons: list[str] = []
        if not isinstance(proposal, Mapping):
            return ["fixed_loopback_proposal_must_be_object"]
        if proposal.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
            reasons.append("fixed_loopback_proposal_schema_mismatch")
        if proposal.get("proposal_status") != EXPECTED_PROPOSAL_STATUS:
            reasons.append("fixed_loopback_proposal_status_invalid")
        if proposal.get("proposal_decision") != EXPECTED_DECISION:
            reasons.append("fixed_loopback_proposal_decision_invalid")
        if proposal.get("authorization_scope") != EXPECTED_AUTHORIZATION_SCOPE:
            reasons.append("fixed_loopback_proposal_authorization_scope_invalid")
        if proposal.get("fixed_loopback_listener_rehearsal_authorized") is not True:
            reasons.append("fixed_loopback_proposal_listener_authorization_missing")
        if _resolve_repo_path(proposal.get("contract_path")) != self.contract_path:
            reasons.append("fixed_loopback_proposal_contract_path_mismatch")
        if proposal.get("contract_sha256") != self.contract_sha256:
            reasons.append("fixed_loopback_proposal_contract_hash_mismatch")
        if _resolve_repo_path(proposal.get("record_path")) != self.record_path:
            reasons.append("fixed_loopback_proposal_record_path_mismatch")
        if proposal.get("record_sha256") != self.record_sha256:
            reasons.append("fixed_loopback_proposal_record_hash_mismatch")
        if proposal.get("parent_loopback_receipt_sha256") != self.parent_receipt_sha256:
            reasons.append("fixed_loopback_proposal_parent_receipt_hash_mismatch")
        endpoint = proposal.get("endpoint")
        if not isinstance(endpoint, Mapping):
            reasons.append("fixed_loopback_proposal_endpoint_invalid")
            endpoint = {}
        reasons.extend(self._validate_endpoint(endpoint, "proposal_endpoint"))
        record_endpoint = record.get("endpoint") if isinstance(record, Mapping) else None
        contract_endpoint = self.contract.get("endpoint_boundary")
        if not _same_mapping(endpoint, record_endpoint):
            reasons.append("fixed_loopback_proposal_endpoint_record_mismatch")
        if not _same_mapping(endpoint, contract_endpoint):
            reasons.append("fixed_loopback_proposal_endpoint_contract_mismatch")
        state = proposal.get("preflight_state")
        if not isinstance(state, Mapping):
            reasons.append("fixed_loopback_proposal_preflight_state_invalid")
            state = {}
        for field in (
            "socket_opened",
            "listener_started",
            "local_loopback_socket_used",
            "external_network_contacted",
            "dns_resolved",
            "certificate_fetched",
            "session_completed",
            "listener_closed",
            "persistent_listener_started",
            "deployment_changed",
            "network_write_authorized",
            "production_endpoint_admitted",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_payload_persisted",
            "private_key_persisted",
            "raw_proposal_persisted",
        ):
            if state.get(field) is not False:
                reasons.append(f"fixed_loopback_proposal_preflight_{field}_must_be_false")
        parent = proposal.get("parent_loopback_rehearsal")
        if not isinstance(parent, Mapping):
            reasons.append("fixed_loopback_proposal_parent_invalid")
        else:
            for field, expected in (
                ("status", "LOOPBACK_ENDPOINT_ACTIVATION_REHEARSAL_PASS_EXTERNAL_CLOSED"),
                ("local_loopback_test_authorized", True),
                ("external_network_contacted", False),
                ("persistent_listener_started", False),
            ):
                if parent.get(field) != expected:
                    reasons.append(f"fixed_loopback_proposal_parent_{field}_mismatch")
        if proposal.get("safe_to_run") is not True:
            reasons.append("fixed_loopback_proposal_safe_to_run_missing")
        return reasons

    def _local_loopback_shape(
        self,
        proposal: Mapping[str, Any] | Any,
        record: Mapping[str, Any] | Any,
    ) -> bool:
        endpoint = proposal.get("endpoint") if isinstance(proposal, Mapping) else None
        record_endpoint = record.get("endpoint") if isinstance(record, Mapping) else None
        return (
            isinstance(endpoint, Mapping)
            and isinstance(record_endpoint, Mapping)
            and endpoint.get("host") == EXPECTED_HOST
            and endpoint.get("allowed_bind_addresses") == [EXPECTED_HOST]
            and endpoint.get("port") == EXPECTED_PORT
            and endpoint.get("port_selection") == EXPECTED_PORT_SELECTION
            and endpoint.get("external_endpoint_allowlist") == []
            and _same_mapping(endpoint, record_endpoint)
        )

    def _safe_to_run(
        self,
        proposal: Mapping[str, Any] | Any,
        record: Mapping[str, Any] | Any,
        reasons: list[str],
    ) -> bool:
        if not isinstance(proposal, Mapping) or not isinstance(record, Mapping):
            return False
        endpoint = proposal.get("endpoint")
        state = proposal.get("preflight_state")
        return (
            not reasons
            and proposal.get("proposal_status") == EXPECTED_PROPOSAL_STATUS
            and proposal.get("proposal_decision") == EXPECTED_DECISION
            and proposal.get("safe_to_run") is True
            and proposal.get("fixed_loopback_listener_rehearsal_authorized") is True
            and isinstance(endpoint, Mapping)
            and endpoint.get("host") == EXPECTED_HOST
            and endpoint.get("port") == EXPECTED_PORT
            and endpoint.get("port_selection") == EXPECTED_PORT_SELECTION
            and endpoint.get("external_endpoint_allowlist") == []
            and isinstance(state, Mapping)
            and all(state.get(field) is False for field in (
                "socket_opened",
                "listener_started",
                "local_loopback_socket_used",
                "external_network_contacted",
                "dns_resolved",
                "certificate_fetched",
                "session_completed",
                "listener_closed",
                "persistent_listener_started",
                "deployment_changed",
                "network_write_authorized",
                "production_endpoint_admitted",
                "automatic_retry",
                "automatic_reauthorization",
                "raw_payload_persisted",
                "private_key_persisted",
                "raw_proposal_persisted",
            ))
        )


__all__ = [
    "DEFAULT_CONTRACT",
    "DEFAULT_PROPOSAL",
    "DEFAULT_RECORD",
    "FixedLoopbackMasterListenerError",
    "FixedLoopbackMasterListenerValidator",
]
