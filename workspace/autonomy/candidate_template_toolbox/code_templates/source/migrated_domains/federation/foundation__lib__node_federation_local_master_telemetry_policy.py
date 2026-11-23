"""Read-only policy gate for local Master telemetry admission.

This gate binds the telemetry admission rehearsal to the completed fixed
loopback listener receipt and to the offline telemetry contracts.  It never
opens a socket, sends data, signs an authorization, or persists runtime
telemetry.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any


HERE = Path(__file__).resolve().parent
FOUNDATION_ROOT = HERE.parent
REPOSITORY_ROOT = FOUNDATION_ROOT.parent
ARTIFACT_ROOT = FOUNDATION_ROOT / "artifacts" / "auto" / "agentic"
DEFAULT_CONTRACT = ARTIFACT_ROOT / "NODE_FEDERATION_LOCAL_MASTER_TELEMETRY_CONTRACT.json"
DEFAULT_PROPOSAL = ARTIFACT_ROOT / "NODE_FEDERATION_LOCAL_MASTER_TELEMETRY_PROPOSAL.json"
DEFAULT_RECORD = ARTIFACT_ROOT / "NODE_FEDERATION_LOCAL_MASTER_TELEMETRY_RECORD.json"
DEFAULT_PARENT_RECEIPT = ARTIFACT_ROOT / "NODE_FEDERATION_FIXED_LOOPBACK_MASTER_LISTENER_STAGE_RECEIPT.json"
DEFAULT_TELEMETRY_CONTRACT = ARTIFACT_ROOT / "NODE_TELEMETRY_CONTRACT.json"
DEFAULT_TRANSPORT_CONTRACT = ARTIFACT_ROOT / "NODE_TELEMETRY_TRANSPORT_CONTRACT.json"

CONTRACT_SCHEMA_VERSION = "viv_node_federation_local_master_telemetry_contract_v1"
PROPOSAL_SCHEMA_VERSION = "viv_node_federation_local_master_telemetry_proposal_v1"
RECORD_SCHEMA_VERSION = "viv_node_federation_local_master_telemetry_record_v1"
EXPECTED_CONTRACT_STATUS = "CLOSED_LOCAL_MASTER_TELEMETRY_ADMISSION_REHEARSAL"
EXPECTED_PROPOSAL_STATUS = "AUTHORIZED_LOCAL_MASTER_TELEMETRY_REHEARSAL"
EXPECTED_RECORD_STATUS = "AUTHORIZED_LOCAL_MASTER_TELEMETRY_REHEARSAL"
EXPECTED_RECORD_SCOPE = "BOUNDED_LOCAL_IN_PROCESS_ONLY"
EXPECTED_DECISION = "ALLOW_BOUNDED_LOCAL_MASTER_TELEMETRY_ADMISSION"
EXPECTED_PARENT_STATUS = "FIXED_LOOPBACK_MASTER_LISTENER_REHEARSAL_PASS_EXTERNAL_CLOSED"
EXPECTED_PARENT_ENDPOINT_ID = "viv-fixed-loopback-master-rehearsal-001"
EXPECTED_PARENT_HOST = "127.0.0.1"
EXPECTED_PARENT_PORT = 54443
EXPECTED_NODE_ID = "viv-local-master-telemetry-rehearsal-001"
EXPECTED_KEY_ID = "key-local-master-telemetry-rehearsal-001"
HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


class LocalMasterTelemetryPolicyError(ValueError):
    """Raised when a local Master telemetry gate input cannot be loaded."""


def _hash_file(path: Path) -> str:
    try:
        digest = sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()
    except OSError as exc:
        raise LocalMasterTelemetryPolicyError(f"local_master_telemetry_file_unreadable:{path}") from exc


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocalMasterTelemetryPolicyError(f"local_master_telemetry_{label}_unreadable:{path}") from exc
    if not isinstance(value, dict):
        raise LocalMasterTelemetryPolicyError(f"local_master_telemetry_{label}_must_be_object:{path}")
    return value


def _resolve_repo_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _bools_match(section: Any, expected: Mapping[str, bool]) -> bool:
    return isinstance(section, Mapping) and all(section.get(key) is value for key, value in expected.items())


class LocalMasterTelemetryValidator:
    """Validate one bounded, in-process local Master telemetry rehearsal."""

    def __init__(
        self,
        *,
        contract_path: Path = DEFAULT_CONTRACT,
        proposal_path: Path = DEFAULT_PROPOSAL,
        record_path: Path = DEFAULT_RECORD,
        parent_receipt_path: Path = DEFAULT_PARENT_RECEIPT,
        telemetry_contract_path: Path = DEFAULT_TELEMETRY_CONTRACT,
        transport_contract_path: Path = DEFAULT_TRANSPORT_CONTRACT,
    ) -> None:
        self.contract_path = Path(contract_path)
        self.proposal_path = Path(proposal_path)
        self.record_path = Path(record_path)
        self.parent_receipt_path = Path(parent_receipt_path)
        self.telemetry_contract_path = Path(telemetry_contract_path)
        self.transport_contract_path = Path(transport_contract_path)
        self.contract = _load_object(self.contract_path, "contract")
        self.proposal = _load_object(self.proposal_path, "proposal")
        self.record = _load_object(self.record_path, "record")
        self.parent_receipt = _load_object(self.parent_receipt_path, "parent_receipt")
        self.telemetry_contract = _load_object(self.telemetry_contract_path, "telemetry_contract")
        self.transport_contract = _load_object(self.transport_contract_path, "transport_contract")
        self.contract_sha256 = _hash_file(self.contract_path)
        self.proposal_sha256 = _hash_file(self.proposal_path)
        self.record_sha256 = _hash_file(self.record_path)
        self.parent_receipt_sha256 = _hash_file(self.parent_receipt_path)
        self.telemetry_contract_sha256 = _hash_file(self.telemetry_contract_path)
        self.transport_contract_sha256 = _hash_file(self.transport_contract_path)

    def validate(self) -> dict[str, Any]:
        return self.evaluate_proposal(self.proposal, record=self.record)

    def evaluate_proposal(
        self,
        proposal: Mapping[str, Any] | Any,
        *,
        record: Mapping[str, Any] | Any | None = None,
    ) -> dict[str, Any]:
        active_record = self.record if record is None else record
        reasons: list[str] = []
        reasons.extend(self._validate_parent())
        reasons.extend(self._validate_contract(active_record))
        reasons.extend(self._validate_telemetry_contracts())
        reasons.extend(self._validate_record(active_record))
        reasons.extend(self._validate_proposal(proposal, active_record))
        reason_codes = list(dict.fromkeys(reasons))
        safe_to_run = isinstance(proposal, Mapping) and proposal.get("safe_to_run") is True and not reason_codes
        reason_codes.append(
            "bounded_local_master_telemetry_admission_authorized"
            if safe_to_run
            else "local_master_telemetry_safe_run_rejected"
        )
        parent_lifecycle = self.parent_receipt.get("listener_lifecycle")
        authority = self.parent_receipt.get("authority_after_receipt")
        return {
            "preflight_pass": safe_to_run,
            "local_master_telemetry_preflight_pass": safe_to_run,
            "decision": EXPECTED_DECISION,
            "safe_to_run": safe_to_run,
            "contract_sha256": self.contract_sha256,
            "proposal_sha256": self.proposal_sha256,
            "record_sha256": self.record_sha256,
            "parent_listener_receipt_sha256": self.parent_receipt_sha256,
            "telemetry_contract_sha256": self.telemetry_contract_sha256,
            "transport_contract_sha256": self.transport_contract_sha256,
            "parent_listener_validated": not any(code.startswith("parent_") for code in reason_codes),
            "parent_listener_status": self.parent_receipt.get("status"),
            "parent_endpoint_id": parent_lifecycle.get("endpoint_id") if isinstance(parent_lifecycle, Mapping) else None,
            "parent_host": parent_lifecycle.get("bind_address") if isinstance(parent_lifecycle, Mapping) else None,
            "parent_port": parent_lifecycle.get("port") if isinstance(parent_lifecycle, Mapping) else None,
            "local_master_telemetry_admission_authorized": self._bool_value(
                self.contract.get("authority"), "local_master_telemetry_admission_authorized"
            ),
            "in_process_receiver_only": self._bool_value(self.contract.get("scope"), "in_process_receiver_only"),
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "external_network_contacted": False,
            "persistent_listener_started": False,
            "raw_payload_persisted": False,
            "private_payload_persisted": False,
            "automatic_retry": False,
            "automatic_resume": False,
            "knowledge_shared_with_master": False,
            "scratchpad_emitted": False,
            "expert_content_emitted": False,
            "authority_after_stage": dict(authority) if isinstance(authority, Mapping) else {},
            "reason_codes": reason_codes,
        }

    @staticmethod
    def _bool_value(section: Any, field: str) -> bool | None:
        if not isinstance(section, Mapping):
            return None
        value = section.get(field)
        return value if isinstance(value, bool) else None

    def _validate_parent(self) -> list[str]:
        reasons: list[str] = []
        receipt = self.parent_receipt
        if receipt.get("status") != EXPECTED_PARENT_STATUS:
            reasons.append("parent_listener_receipt_status_mismatch")
        artifacts = receipt.get("artifacts")
        if not isinstance(artifacts, Mapping):
            reasons.append("parent_listener_receipt_artifacts_invalid")
        lifecycle = receipt.get("listener_lifecycle")
        if not isinstance(lifecycle, Mapping):
            reasons.append("parent_listener_receipt_lifecycle_invalid")
        else:
            for field, expected in (
                ("endpoint_id", EXPECTED_PARENT_ENDPOINT_ID),
                ("bind_address", EXPECTED_PARENT_HOST),
                ("port", EXPECTED_PARENT_PORT),
                ("tls_version_negotiated", "TLSv1.3"),
            ):
                if lifecycle.get(field) != expected:
                    reasons.append(f"parent_listener_{field}_mismatch")
            for field in (
                "mutual_tls_verified",
                "application_signature_verified",
                "one_session_only",
                "listener_started_during_rehearsal",
                "application_frame_received",
                "application_frame_accepted",
                "listener_closed_after_session",
                "socket_closed_before_receipt",
            ):
                if lifecycle.get(field) is not True:
                    reasons.append(f"parent_listener_{field}_must_be_true")
            for field in (
                "persistent_listener_started",
                "daemon_started",
                "external_network_contacted",
                "dns_resolved",
                "certificate_fetched",
                "network_socket_enabled_after_rehearsal",
                "network_write_authorized",
                "raw_payload_persisted",
                "private_key_persisted",
                "production_endpoint_admitted",
                "deployment_changed",
                "live_runtime_module_installed",
                "automatic_retry",
                "automatic_reauthorization",
            ):
                if lifecycle.get(field) is not False:
                    reasons.append(f"parent_listener_{field}_must_be_false")
        authority = receipt.get("authority_after_receipt")
        if not isinstance(authority, Mapping):
            reasons.append("parent_listener_authority_invalid")
        else:
            if authority.get("fixed_loopback_listener_rehearsal_authorized") is not True:
                reasons.append("parent_listener_rehearsal_authorization_missing")
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
                    reasons.append(f"parent_listener_authority_{field}_must_be_false")
        parent = self.contract.get("parent_listener_receipt")
        if not isinstance(parent, Mapping):
            reasons.append("local_master_contract_parent_section_invalid")
        else:
            if _resolve_repo_path(parent.get("path")) != self.parent_receipt_path:
                reasons.append("local_master_contract_parent_path_mismatch")
            if parent.get("sha256") != self.parent_receipt_sha256:
                reasons.append("local_master_contract_parent_hash_mismatch")
            for field, expected in (
                ("required_status", EXPECTED_PARENT_STATUS),
                ("required_endpoint_id", EXPECTED_PARENT_ENDPOINT_ID),
                ("required_bind_address", EXPECTED_PARENT_HOST),
                ("required_port", EXPECTED_PARENT_PORT),
                ("required_external_network_contacted", False),
                ("required_network_write_authorized", False),
                ("required_persistent_listener_started", False),
                ("required_raw_payload_persisted", False),
            ):
                if parent.get(field) != expected:
                    reasons.append(f"local_master_contract_parent_{field}_mismatch")
        return reasons

    def _validate_contract(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        contract = self.contract
        if contract.get("schema_version") != CONTRACT_SCHEMA_VERSION:
            reasons.append("local_master_contract_schema_mismatch")
        if contract.get("status") != EXPECTED_CONTRACT_STATUS:
            reasons.append("local_master_contract_status_invalid")
        for section_name, expected_path, expected_schema, expected_status in (
            ("proposal", self.proposal_path, PROPOSAL_SCHEMA_VERSION, EXPECTED_PROPOSAL_STATUS),
            ("record", self.record_path, RECORD_SCHEMA_VERSION, EXPECTED_RECORD_STATUS),
        ):
            section = contract.get(section_name)
            if not isinstance(section, Mapping):
                reasons.append(f"local_master_contract_{section_name}_section_invalid")
                continue
            if _resolve_repo_path(section.get("path")) != expected_path:
                reasons.append(f"local_master_contract_{section_name}_path_mismatch")
            if section.get("required_schema_version") != expected_schema:
                reasons.append(f"local_master_contract_{section_name}_schema_mismatch")
            if section.get("required_status") != expected_status:
                reasons.append(f"local_master_contract_{section_name}_status_mismatch")
            if section_name == "record" and section.get("required_scope") != EXPECTED_RECORD_SCOPE:
                reasons.append("local_master_contract_record_scope_mismatch")
        for section_name, expected_path, expected_hash, expected_schema, expected_id, expected_status in (
            (
                "telemetry_contract",
                self.telemetry_contract_path,
                self.telemetry_contract_sha256,
                "viv_node_to_master_telemetry_contract_v1",
                "viv_federated_node_telemetry_boundary_v1",
                "PREPARED_READ_ONLY_NO_NETWORK_WRITES",
            ),
            (
                "transport_contract",
                self.transport_contract_path,
                self.transport_contract_sha256,
                "viv_node_telemetry_transport_contract_v1",
                "viv_federated_node_telemetry_transport_v1",
                "OFFLINE_AUTHENTICATED_ENVELOPE_PROTOTYPE_NO_NETWORK",
            ),
        ):
            section = contract.get(section_name)
            if not isinstance(section, Mapping):
                reasons.append(f"local_master_contract_{section_name}_section_invalid")
                continue
            if _resolve_repo_path(section.get("path")) != expected_path:
                reasons.append(f"local_master_contract_{section_name}_path_mismatch")
            if section.get("sha256") != expected_hash:
                reasons.append(f"local_master_contract_{section_name}_hash_mismatch")
            if section.get("required_schema_version") != expected_schema:
                reasons.append(f"local_master_contract_{section_name}_schema_mismatch")
            if section.get("required_contract_id") != expected_id:
                reasons.append(f"local_master_contract_{section_name}_id_mismatch")
            if section.get("required_status") != expected_status:
                reasons.append(f"local_master_contract_{section_name}_status_mismatch")
        scope = contract.get("scope")
        expected_scope = {
            "local_master_telemetry_admission_authorized": True,
            "in_process_receiver_only": True,
            "one_runtime_session": True,
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "external_network_contacted": False,
            "persistent_listener_started": False,
            "raw_payload_persisted": False,
            "private_payload_persisted": False,
            "automatic_retry": False,
            "automatic_resume": False,
            "operator_resume_required_after_offline": True,
            "offline_state_admission": False,
            "knowledge_shared_with_master": False,
            "scratchpad_emitted": False,
            "expert_content_emitted": False,
            "private_identity_content_emitted": False,
        }
        if not _bools_match(scope, expected_scope) or not isinstance(scope, Mapping) or scope.get("max_admission_samples") != 3:
            reasons.append("local_master_contract_scope_mismatch")
        lifecycle = contract.get("lifecycle_policy")
        if not isinstance(lifecycle, Mapping):
            reasons.append("local_master_contract_lifecycle_policy_invalid")
        else:
            if lifecycle.get("admissible_node_states") != ["available", "degraded"]:
                reasons.append("local_master_contract_admissible_states_mismatch")
            if lifecycle.get("local_hold_node_states") != ["offline", "revoked"]:
                reasons.append("local_master_contract_hold_states_mismatch")
            if lifecycle.get("resume_policy") != "EXPLICIT_FRESH_LOOPBACK_SNAPSHOT_REQUIRED":
                reasons.append("local_master_contract_resume_policy_mismatch")
        authority = contract.get("authority")
        expected_authority = {
            "local_master_telemetry_admission_authorized": True,
            "telemetry_admission_authorized": True,
            "external_discovery_authorized": False,
            "endpoint_contact_authorized": False,
            "activation_authorized": False,
            "network_write_authorized": False,
            "deployment_authorized": False,
            "training_authorized": False,
            "run_authorized": False,
            "promotion_authorized": False,
            "live_runtime_module_installed": False,
            "global_aifl_writes": False,
            "master_s_n_mutation": False,
            "knowledge_admission": False,
            "automatic_retry_authorized": False,
            "automatic_resume_authorized": False,
        }
        if not _bools_match(authority, expected_authority):
            reasons.append("local_master_contract_authority_mismatch")
        return reasons

    def _validate_telemetry_contracts(self) -> list[str]:
        reasons: list[str] = []
        if self.telemetry_contract.get("schema_version") != "viv_node_to_master_telemetry_contract_v1":
            reasons.append("telemetry_contract_schema_mismatch")
        if self.telemetry_contract.get("contract_id") != "viv_federated_node_telemetry_boundary_v1":
            reasons.append("telemetry_contract_id_mismatch")
        if self.telemetry_contract.get("status") != "PREPARED_READ_ONLY_NO_NETWORK_WRITES":
            reasons.append("telemetry_contract_status_mismatch")
        if self.transport_contract.get("schema_version") != "viv_node_telemetry_transport_contract_v1":
            reasons.append("transport_contract_schema_mismatch")
        if self.transport_contract.get("contract_id") != "viv_federated_node_telemetry_transport_v1":
            reasons.append("transport_contract_id_mismatch")
        if self.transport_contract.get("status") != "OFFLINE_AUTHENTICATED_ENVELOPE_PROTOTYPE_NO_NETWORK":
            reasons.append("transport_contract_status_mismatch")
        return reasons

    def _validate_record(self, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        if not isinstance(record, Mapping):
            return ["local_master_record_must_be_object"]
        if record.get("schema_version") != RECORD_SCHEMA_VERSION:
            reasons.append("local_master_record_schema_mismatch")
        if record.get("status") != EXPECTED_RECORD_STATUS:
            reasons.append("local_master_record_status_invalid")
        if record.get("record_scope") != EXPECTED_RECORD_SCOPE:
            reasons.append("local_master_record_scope_invalid")
        if record.get("contract_sha256") != self.contract_sha256:
            reasons.append("local_master_record_contract_hash_mismatch")
        parent = record.get("parent_listener_receipt")
        if not isinstance(parent, Mapping):
            reasons.append("local_master_record_parent_section_invalid")
        else:
            if _resolve_repo_path(parent.get("path")) != self.parent_receipt_path:
                reasons.append("local_master_record_parent_path_mismatch")
            if parent.get("sha256") != self.parent_receipt_sha256:
                reasons.append("local_master_record_parent_hash_mismatch")
            if parent.get("required_status") != EXPECTED_PARENT_STATUS:
                reasons.append("local_master_record_parent_status_mismatch")
        node = record.get("node_fixture")
        if not isinstance(node, Mapping):
            reasons.append("local_master_record_node_fixture_invalid")
        else:
            if node.get("node_id") != EXPECTED_NODE_ID:
                reasons.append("local_master_record_node_id_mismatch")
            if node.get("key_id") != EXPECTED_KEY_ID:
                reasons.append("local_master_record_key_id_mismatch")
            if not _is_hash(node.get("node_identity_hash")):
                reasons.append("local_master_record_node_identity_hash_invalid")
            if node.get("secret_material") != "MEMORY_ONLY_TEST_SECRET_NOT_PERSISTED":
                reasons.append("local_master_record_secret_persistence_marker_invalid")
        authorization = record.get("operator_authorization")
        expected_authorization = {
            "local_master_telemetry_admission_authorized": True,
            "in_process_receiver_only": True,
            "network_socket_authorized": False,
            "network_write_authorized": False,
            "external_network_authorized": False,
            "persistent_listener_authorized": False,
            "automatic_retry_authorized": False,
            "automatic_resume_authorized": False,
            "production_telemetry_admission_authorized": False,
        }
        if not _bools_match(authorization, expected_authorization):
            reasons.append("local_master_record_authorization_mismatch")
        runtime = record.get("runtime_boundary")
        expected_runtime = {
            "one_runtime_session": True,
            "secret_memory_only": True,
            "raw_payload_persisted": False,
            "private_payload_persisted": False,
            "runtime_state_persisted": False,
            "knowledge_shared_with_master": False,
            "scratchpad_emitted": False,
            "expert_content_emitted": False,
            "content_plane_closed": True,
            "scratchpad_ephemeral": True,
            "cpu_authority_enabled": True,
        }
        if not _bools_match(runtime, expected_runtime) or not isinstance(runtime, Mapping) or runtime.get("max_admission_samples") != 3:
            reasons.append("local_master_record_runtime_boundary_mismatch")
        return reasons

    def _validate_proposal(self, proposal: Mapping[str, Any] | Any, record: Mapping[str, Any] | Any) -> list[str]:
        reasons: list[str] = []
        if not isinstance(proposal, Mapping):
            return ["local_master_proposal_must_be_object"]
        if proposal.get("schema_version") != PROPOSAL_SCHEMA_VERSION:
            reasons.append("local_master_proposal_schema_mismatch")
        if proposal.get("status") != EXPECTED_PROPOSAL_STATUS:
            reasons.append("local_master_proposal_status_invalid")
        if proposal.get("decision") != EXPECTED_DECISION:
            reasons.append("local_master_proposal_decision_mismatch")
        if proposal.get("safe_to_run") is not True:
            reasons.append("local_master_proposal_safe_to_run_missing")
        if proposal.get("contract_path") != self.contract_path.relative_to(REPOSITORY_ROOT).as_posix():
            reasons.append("local_master_proposal_contract_path_mismatch")
        if proposal.get("contract_sha256") != self.contract_sha256:
            reasons.append("local_master_proposal_contract_hash_mismatch")
        if proposal.get("record_path") != self.record_path.relative_to(REPOSITORY_ROOT).as_posix():
            reasons.append("local_master_proposal_record_path_mismatch")
        if proposal.get("record_sha256") != self.record_sha256:
            reasons.append("local_master_proposal_record_hash_mismatch")
        if proposal.get("parent_listener_receipt_path") != self.parent_receipt_path.relative_to(REPOSITORY_ROOT).as_posix():
            reasons.append("local_master_proposal_parent_path_mismatch")
        if proposal.get("parent_listener_receipt_sha256") != self.parent_receipt_sha256:
            reasons.append("local_master_proposal_parent_hash_mismatch")
        scope = proposal.get("admission_scope")
        if not isinstance(scope, Mapping):
            reasons.append("local_master_proposal_admission_scope_invalid")
        else:
            for field, expected in (
                ("node_id", EXPECTED_NODE_ID),
                ("key_id", EXPECTED_KEY_ID),
                ("message_type", "health_sample"),
                ("admissible_node_states", ["available", "degraded"]),
                ("offline_node_state_action", "HOLD_OFFLINE_LOCAL_STATE"),
                ("maximum_samples", 3),
                ("one_runtime_session", True),
            ):
                if scope.get(field) != expected:
                    reasons.append(f"local_master_proposal_scope_{field}_mismatch")
        preflight = proposal.get("preflight_state")
        expected_preflight = {
            "local_master_telemetry_admission_authorized": True,
            "in_process_receiver_only": True,
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "external_network_contacted": False,
            "persistent_listener_started": False,
            "raw_payload_persisted": False,
            "private_payload_persisted": False,
            "automatic_retry": False,
            "automatic_resume": False,
            "knowledge_shared_with_master": False,
            "scratchpad_emitted": False,
            "expert_content_emitted": False,
            "content_plane_closed": True,
            "scratchpad_ephemeral": True,
            "cpu_authority_enabled": True,
        }
        if not _bools_match(preflight, expected_preflight):
            reasons.append("local_master_proposal_preflight_state_mismatch")
        return reasons


__all__ = ["LocalMasterTelemetryPolicyError", "LocalMasterTelemetryValidator"]
