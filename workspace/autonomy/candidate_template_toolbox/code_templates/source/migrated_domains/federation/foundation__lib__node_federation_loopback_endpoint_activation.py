"""Validate one explicitly authorized Viv-only loopback endpoint rehearsal.

This module is deliberately a policy reducer.  It never opens a socket, resolves
DNS, fetches certificates, starts a process, signs data, admits an endpoint, or
writes an artifact.  The separate bounded test invokes the already-verified TLS
1.3 mutual-auth loopback harness after this reducer returns a safe-to-run result.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .node_federation_endpoint_candidate_review import (
    DEFAULT_CANDIDATE_CONTRACT,
    DEFAULT_CANDIDATE_PROPOSAL,
    DEFAULT_CANDIDATE_INVENTORY,
    DEFAULT_COMPLETION_REVIEW_RECEIPT,
    FederationEndpointCandidateReviewValidator,
)


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
DEFAULT_CONTRACT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_LOOPBACK_ENDPOINT_ACTIVATION_CONTRACT.json"
)
DEFAULT_PROPOSAL = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_LOOPBACK_ENDPOINT_ACTIVATION_PROPOSAL.json"
)
DEFAULT_RECORD = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_LOOPBACK_ENDPOINT_ACTIVATION_RECORD.json"
)
DEFAULT_CANDIDATE_RECEIPT = (
    FOUNDATION_ROOT
    / "artifacts"
    / "auto"
    / "agentic"
    / "NODE_FEDERATION_ENDPOINT_CANDIDATE_REVIEW_STAGE_RECEIPT.json"
)

CONTRACT_SCHEMA_VERSION = "viv_node_federation_loopback_endpoint_activation_contract_v1"
PROPOSAL_SCHEMA_VERSION = "viv_node_federation_loopback_endpoint_activation_proposal_v1"
RECORD_SCHEMA_VERSION = "viv_node_federation_loopback_endpoint_activation_record_v1"
EXPECTED_CONTRACT_STATUS = "CLOSED_LOOPBACK_ENDPOINT_ACTIVATION_REHEARSAL"
EXPECTED_PROPOSAL_STATUS = "AUTHORIZED_LOCAL_LOOPBACK_REHEARSAL"
EXPECTED_RECORD_STATUS = "AUTHORIZED_LOCAL_LOOPBACK_REHEARSAL"
EXPECTED_RECORD_SCOPE = "EPHEMERAL_LOCAL_TEST_ONLY"
EXPECTED_DECISION = "ALLOW_BOUNDED_LOCAL_LOOPBACK_REHEARSAL"
EXPECTED_ENDPOINT_CLASS = "LOOPBACK_ONLY_TEST"
EXPECTED_ENDPOINT_ID = "viv-loopback-rehearsal-master-001"
EXPECTED_HOST = "127.0.0.1"
EXPECTED_TLS_SERVER_NAME = "localhost"
EXPECTED_TLS_VERSION = "TLSv1.3"
EXPECTED_AUTHORIZATION_SCOPE = "ONE_EPHEMERAL_127.0.0.1_TLS13_MUTUAL_AUTH_SESSION"


class FederationLoopbackEndpointActivationError(ValueError):
    """Raised when a loopback rehearsal input cannot be loaded."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def _hash_file(path: Path) -> str:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError as exc:
        raise FederationLoopbackEndpointActivationError(
            f"loopback_endpoint_activation_file_unreadable:{path}"
        ) from exc


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FederationLoopbackEndpointActivationError(
            f"loopback_endpoint_activation_{label}_unreadable:{path}"
        ) from exc
    if not isinstance(value, dict):
        raise FederationLoopbackEndpointActivationError(
            f"loopback_endpoint_activation_{label}_must_be_object:{path}"
        )
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


def _same_mapping(actual: Any, expected: Any) -> bool:
    return isinstance(actual, Mapping) and dict(actual) == dict(expected)


class FederationLoopbackEndpointActivationValidator:
    """Validate a sealed, local-only endpoint rehearsal proposal."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_CONTRACT,
        proposal_path: Path = DEFAULT_PROPOSAL,
        record_path: Path = DEFAULT_RECORD,
        candidate_receipt_path: Path = DEFAULT_CANDIDATE_RECEIPT,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.record_path = Path(record_path)
        self.candidate_receipt_path = Path(candidate_receipt_path)
        self.contract = _load_json(self.contract_path, "contract")
        self.proposal = _load_json(self.proposal_path, "proposal")
        self.record = _load_json(self.record_path, "record")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        self.record_sha256 = _hash_file(self.record_path)
        self.candidate_receipt_sha256 = _hash_file(self.candidate_receipt_path)
        self.candidate_review = FederationEndpointCandidateReviewValidator(
            contract_path=DEFAULT_CANDIDATE_CONTRACT,
            proposal_path=DEFAULT_CANDIDATE_PROPOSAL,
            inventory_path=DEFAULT_CANDIDATE_INVENTORY,
        )

    def validate(self) -> dict[str, Any]:
        """Return aggregate policy evidence without external effects."""
        return self.evaluate_proposal(self.proposal, record=self.record)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        record: Mapping[str, Any] | Any | None = None,
    ) -> dict[str, Any]:
        """Evaluate in-memory values without persistence or external effects."""
        if record is None:
            record = self.record
        reasons: list[str] = []
        reasons.extend(self._validate_parent_candidate_review())
        reasons.extend(self._validate_contract(record))
        reasons.extend(self._validate_record(record))
        reasons.extend(self._validate_proposal(proposal, record))

        safe_to_run = self._safe_to_run(proposal, record, reasons)
        reason_codes = list(dict.fromkeys(reasons))
        if safe_to_run:
            reason_codes.append("bounded_local_loopback_rehearsal_authorized")
        else:
            reason_codes.append("loopback_endpoint_activation_safe_run_rejected")
        preflight_pass = safe_to_run and not reasons
        return {
            "preflight_pass": preflight_pass,
            "loopback_endpoint_activation_preflight_pass": preflight_pass,
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
            "proposal_sha256": self.proposal_sha256,
            "contract_sha256": self.contract_sha256,
            "record_sha256": self.record_sha256,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "candidate_review_validated": self._candidate_review_result.get("preflight_pass") is True,
            "candidate_review_decision": self._candidate_review_result.get("decision"),
            "candidate_review_safe_hold": self._candidate_review_result.get("safe_hold") is True,
            "eligible_federation_endpoint_count": self._candidate_review_result.get(
                "eligible_federation_endpoint_count"
            ),
            "local_loopback_test_authorized": self._bool_value(proposal, "local_loopback_test_authorized"),
            "socket_opened": self._bool_nested(proposal, "preflight_state", "socket_opened"),
            "local_loopback_socket_used": self._bool_nested(
                proposal, "preflight_state", "local_loopback_socket_used"
            ),
            "external_network_contacted": False,
            "dns_resolved": False,
            "certificate_fetched": False,
            "activation_performed": False,
            "persistent_listener_started": False,
            "deployment_changed": False,
            "network_write_authorized": False,
            "production_endpoint_admitted": False,
            "automatic_selection": False,
            "automatic_admission": False,
            "automatic_retry": False,
            "automatic_reauthorization": False,
            "raw_payload_persisted": False,
            "private_key_persisted": False,
            "reason_codes": list(dict.fromkeys(reason_codes)),
        }

    @property
    def _candidate_review_result(self) -> dict[str, Any]:
        return self.candidate_review.validate()

    @staticmethod
    def _endpoint_value(record: Mapping[str, Any] | Any, field: str) -> Any:
        endpoint = record.get("endpoint") if isinstance(record, Mapping) else None
        return endpoint.get(field) if isinstance(endpoint, Mapping) else None

    @staticmethod
    def _bool_value(value: Mapping[str, Any] | Any, field: str) -> bool | None:
        if not isinstance(value, Mapping):
            return None
        result = value.get(field)
        return result if isinstance(result, bool) else None

    @staticmethod
    def _bool_nested(value: Mapping[str, Any] | Any, section: str, field: str) -> bool | None:
        if not isinstance(value, Mapping):
            return None
        child = value.get(section)
        return child.get(field) if isinstance(child, Mapping) and isinstance(child.get(field), bool) else None

    def _validate_parent_candidate_review(self) -> list[str]:
        reasons: list[str] = []
        result = self._candidate_review_result
        if result.get("preflight_pass") is not True:
            reasons.append("parent_candidate_review_preflight_invalid")
        if result.get("decision") != "HOLD_NO_ELIGIBLE_FEDERATION_ENDPOINT":
            reasons.append("parent_candidate_review_decision_mismatch")
        if result.get("safe_hold") is not True:
            reasons.append("parent_candidate_review_safe_hold_mismatch")
        if result.get("eligible_federation_endpoint_count") != 0:
            reasons.append("parent_candidate_review_must_have_zero_eligible_endpoints")
        parent = self.contract.get("parent_candidate_review")
        if not isinstance(parent, Mapping):
            return reasons + ["loopback_contract_parent_candidate_review_invalid"]
        expected_paths = {
            "contract_path": self.candidate_review.contract_path,
            "proposal_path": self.candidate_review.proposal_path,
            "receipt_path": self.candidate_receipt_path,
        }
        expected_hashes = {
            "contract_sha256": self.candidate_review.contract_sha256,
            "proposal_sha256": self.candidate_review.proposal_sha256,
            "receipt_sha256": self.candidate_receipt_sha256,
        }
        for path_field, actual_path in expected_paths.items():
            declared = _resolve_repo_path(parent.get(path_field))
            if declared != actual_path:
                reasons.append(f"loopback_parent_{path_field}_mismatch")
        for hash_field, actual_hash in expected_hashes.items():
            if parent.get(hash_field) != actual_hash:
                reasons.append(f"loopback_parent_{hash_field}_mismatch")
        for field, expected in (
            ("required_status", "ENDPOINT_CANDIDATE_REVIEW_PREFLIGHT_PASS_HOLD"),
            ("required_decision", "HOLD_NO_ELIGIBLE_FEDERATION_ENDPOINT"),
            ("required_safe_hold", True),
        ):
            if parent.get(field) != expected:
                reasons.append(f"loopback_parent_{field}_mismatch")
        return reasons

    def _validate_contract(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        contract = self.contract
        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            reasons.append("loopback_contract_schema_mismatch")
        if contract.get("status") != EXPECTED_CONTRACT_STATUS:
            reasons.append("loopback_contract_status_invalid")
        loopback_record = contract.get("loopback_record")
        if not isinstance(loopback_record, Mapping):
            reasons.append("loopback_contract_record_section_invalid")
        else:
            if _resolve_repo_path(loopback_record.get("path")) != self.record_path:
                reasons.append("loopback_contract_record_path_mismatch")
            if loopback_record.get("sha256") != self.record_sha256:
                reasons.append("loopback_contract_record_hash_mismatch")
            if loopback_record.get("required_status") != EXPECTED_RECORD_STATUS:
                reasons.append("loopback_contract_record_status_mismatch")
            if loopback_record.get("required_scope") != EXPECTED_RECORD_SCOPE:
                reasons.append("loopback_contract_record_scope_mismatch")
        proposal = contract.get("proposal")
        if not isinstance(proposal, Mapping):
            reasons.append("loopback_contract_proposal_section_invalid")
        elif _resolve_repo_path(proposal.get("path")) != self.proposal_path:
            reasons.append("loopback_contract_proposal_path_mismatch")

        endpoint = contract.get("endpoint_boundary")
        if not isinstance(endpoint, Mapping):
            reasons.append("loopback_contract_endpoint_boundary_invalid")
            endpoint = {}
        reasons.extend(self._validate_endpoint(endpoint, "contract_endpoint"))
        activation = contract.get("activation_scope")
        if not isinstance(activation, Mapping):
            reasons.append("loopback_contract_activation_scope_invalid")
            activation = {}
        for field in (
            "local_loopback_test_authorized",
            "one_session_only",
            "socket_may_open_only_during_rehearsal",
            "socket_closed_before_receipt",
        ):
            if activation.get(field) is not True:
                reasons.append(f"loopback_contract_{field}_must_be_true")
        for field in (
            "external_network_contacted",
            "external_endpoint_contact_authorized",
            "network_write_authorized",
            "activation_performed",
            "deployment_changed",
            "live_runtime_module_installed",
            "automatic_selection",
            "automatic_admission",
            "automatic_retry",
            "automatic_reauthorization",
            "persistent_service_start",
            "raw_payload_persistence",
            "private_key_persistence",
            "production_endpoint_admission",
        ):
            if activation.get(field) is not False:
                reasons.append(f"loopback_contract_{field}_must_be_false")
        authority = contract.get("authority")
        if not isinstance(authority, Mapping):
            reasons.append("loopback_contract_authority_invalid")
        else:
            if authority.get("local_loopback_test_authorized") is not True:
                reasons.append("loopback_contract_local_loopback_authority_missing")
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
                    reasons.append(f"loopback_contract_authority_{field}_must_be_false")
        return reasons

    def _validate_record(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        if not isinstance(record, Mapping):
            return ["loopback_record_must_be_object"]
        if record.get("schema_version") != RECORD_SCHEMA_VERSION:
            reasons.append("loopback_record_schema_mismatch")
        if record.get("status") != EXPECTED_RECORD_STATUS:
            reasons.append("loopback_record_status_invalid")
        if record.get("record_scope") != EXPECTED_RECORD_SCOPE:
            reasons.append("loopback_record_scope_invalid")
        endpoint = record.get("endpoint")
        if not isinstance(endpoint, Mapping):
            reasons.append("loopback_record_endpoint_invalid")
            endpoint = {}
        reasons.extend(self._validate_endpoint(endpoint, "record_endpoint"))
        parent = record.get("parent_candidate_review")
        if not isinstance(parent, Mapping):
            reasons.append("loopback_record_parent_candidate_review_invalid")
        elif parent.get("receipt_sha256") != self.candidate_receipt_sha256:
            reasons.append("loopback_record_parent_receipt_hash_mismatch")
        identity = record.get("identity_boundary")
        if not isinstance(identity, Mapping):
            reasons.append("loopback_record_identity_boundary_invalid")
        else:
            for field in (
                "production_endpoint_identity_supplied",
                "production_endpoint_admitted",
                "certificate_pins_supplied",
                "private_key_persisted",
                "certificate_material_persisted",
                "unrelated_listener_reuse_allowed",
            ):
                if identity.get(field) is not False:
                    reasons.append(f"loopback_record_identity_{field}_must_be_false")
            if identity.get("test_identity_generated_ephemerally") is not True:
                reasons.append("loopback_record_test_identity_must_be_ephemeral")
        authorization = record.get("operator_authorization")
        if not isinstance(authorization, Mapping):
            reasons.append("loopback_record_operator_authorization_invalid")
        else:
            if authorization.get("local_loopback_test_authorized") is not True:
                reasons.append("loopback_record_local_loopback_authorization_missing")
            for field in (
                "external_network_authorized",
                "lan_network_authorized",
                "persistent_service_authorized",
                "deployment_authorized",
                "automatic_retry_authorized",
                "automatic_reauthorization_authorized",
            ):
                if authorization.get(field) is not False:
                    reasons.append(f"loopback_record_authorization_{field}_must_be_false")
        runtime = record.get("runtime_boundary")
        if not isinstance(runtime, Mapping):
            reasons.append("loopback_record_runtime_boundary_invalid")
        else:
            if runtime.get("local_loopback_socket_allowed_during_rehearsal") is not True:
                reasons.append("loopback_record_local_socket_scope_missing")
            if runtime.get("one_session_only") is not True:
                reasons.append("loopback_record_one_session_only_missing")
            for field in (
                "socket_closed_before_receipt",
                "external_network_contacted",
                "network_write_authorized",
                "endpoint_contact_authorized",
                "activation_performed",
                "deployment_changed",
                "live_runtime_module_installed",
                "raw_payload_persisted",
                "private_reasoning_or_knowledge_admitted",
            ):
                if runtime.get(field) is not False and field != "socket_closed_before_receipt":
                    reasons.append(f"loopback_record_runtime_{field}_must_be_false")
            if runtime.get("socket_closed_before_receipt") is not True:
                reasons.append("loopback_record_runtime_socket_closed_before_receipt_must_be_true")
        return reasons

    def _validate_endpoint(self, endpoint: Mapping[str, Any], prefix: str) -> list[str]:
        reasons: list[str] = []
        if endpoint.get("endpoint_id") not in (None, EXPECTED_ENDPOINT_ID):
            reasons.append(f"{prefix}_endpoint_id_invalid")
        if endpoint.get("endpoint_class") != EXPECTED_ENDPOINT_CLASS:
            reasons.append(f"{prefix}_endpoint_class_invalid")
        if endpoint.get("host") != EXPECTED_HOST:
            reasons.append(f"{prefix}_host_must_be_127_0_0_1")
        if endpoint.get("allowed_bind_addresses") != [EXPECTED_HOST]:
            reasons.append(f"{prefix}_allowed_bind_addresses_invalid")
        if endpoint.get("port") is not None:
            reasons.append(f"{prefix}_port_must_be_null_for_ephemeral")
        if endpoint.get("port_selection") != "ephemeral":
            reasons.append(f"{prefix}_port_selection_must_be_ephemeral")
        if endpoint.get("ephemeral_port_only") is not True:
            reasons.append(f"{prefix}_ephemeral_port_only_must_be_true")
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
            return ["loopback_proposal_must_be_object"]
        if proposal.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
            reasons.append("loopback_proposal_schema_mismatch")
        if proposal.get("proposal_status") != EXPECTED_PROPOSAL_STATUS:
            reasons.append("loopback_proposal_status_invalid")
        if proposal.get("proposal_decision") != EXPECTED_DECISION:
            reasons.append("loopback_proposal_decision_invalid")
        if proposal.get("authorization_scope") != EXPECTED_AUTHORIZATION_SCOPE:
            reasons.append("loopback_proposal_authorization_scope_invalid")
        if proposal.get("local_loopback_test_authorized") is not True:
            reasons.append("loopback_proposal_local_loopback_authorization_missing")
        if _resolve_repo_path(proposal.get("contract_path")) != self.contract_path:
            reasons.append("loopback_proposal_contract_path_mismatch")
        if proposal.get("contract_sha256") != self.contract_sha256:
            reasons.append("loopback_proposal_contract_hash_mismatch")
        if _resolve_repo_path(proposal.get("record_path")) != self.record_path:
            reasons.append("loopback_proposal_record_path_mismatch")
        if proposal.get("record_sha256") != self.record_sha256:
            reasons.append("loopback_proposal_record_hash_mismatch")
        if proposal.get("parent_candidate_review_receipt_sha256") != self.candidate_receipt_sha256:
            reasons.append("loopback_proposal_parent_receipt_hash_mismatch")
        endpoint = proposal.get("endpoint")
        if not isinstance(endpoint, Mapping):
            reasons.append("loopback_proposal_endpoint_invalid")
            endpoint = {}
        reasons.extend(self._validate_endpoint(endpoint, "proposal_endpoint"))
        record_endpoint = record.get("endpoint") if isinstance(record, Mapping) else None
        if not _same_mapping(endpoint, record_endpoint):
            reasons.append("loopback_proposal_endpoint_record_mismatch")
        contract_endpoint = self.contract.get("endpoint_boundary")
        if not _same_mapping(endpoint, contract_endpoint):
            reasons.append("loopback_proposal_endpoint_contract_mismatch")
        state = proposal.get("preflight_state")
        if not isinstance(state, Mapping):
            reasons.append("loopback_proposal_preflight_state_invalid")
            state = {}
        for field in (
            "socket_opened",
            "local_loopback_socket_used",
            "external_network_contacted",
            "dns_resolved",
            "certificate_fetched",
            "activation_performed",
            "persistent_listener_started",
            "deployment_changed",
            "network_write_authorized",
            "production_endpoint_admitted",
            "automatic_selection",
            "automatic_admission",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_payload_persisted",
            "private_key_persisted",
            "raw_proposal_persisted",
        ):
            if state.get(field) is not False:
                reasons.append(f"loopback_proposal_preflight_{field}_must_be_false")
        parent = proposal.get("parent_candidate_review")
        if not isinstance(parent, Mapping):
            reasons.append("loopback_proposal_parent_candidate_review_invalid")
        else:
            for field, expected in (
                ("decision", "HOLD_NO_ELIGIBLE_FEDERATION_ENDPOINT"),
                ("safe_hold", True),
                ("eligible_federation_endpoint_count", 0),
                ("unrelated_listener_reuse_allowed", False),
            ):
                if parent.get(field) != expected:
                    reasons.append(f"loopback_proposal_parent_{field}_mismatch")
        if proposal.get("safe_to_run") is not True:
            reasons.append("loopback_proposal_safe_to_run_missing")
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
            and endpoint.get("port") is None
            and endpoint.get("port_selection") == "ephemeral"
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
            and proposal.get("local_loopback_test_authorized") is True
            and isinstance(endpoint, Mapping)
            and endpoint.get("host") == EXPECTED_HOST
            and endpoint.get("port") is None
            and endpoint.get("port_selection") == "ephemeral"
            and endpoint.get("external_endpoint_allowlist") == []
            and isinstance(state, Mapping)
            and all(state.get(field) is False for field in (
                "socket_opened",
                "local_loopback_socket_used",
                "external_network_contacted",
                "dns_resolved",
                "certificate_fetched",
                "activation_performed",
                "persistent_listener_started",
                "deployment_changed",
                "network_write_authorized",
                "production_endpoint_admitted",
                "automatic_selection",
                "automatic_admission",
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
    "FederationLoopbackEndpointActivationError",
    "FederationLoopbackEndpointActivationValidator",
]
