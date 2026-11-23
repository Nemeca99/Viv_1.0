"""Bounded local Master admission and lifecycle health reporting.

The reporter composes the offline authenticated telemetry prototype with an
explicit one-session lifecycle.  It admits only aggregate health samples to
an in-process receiver, holds cleanly closed/offline states, requires an
explicit fresh loopback snapshot to resume, and returns aggregate receipts
without returning or persisting the telemetry payload.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .node_telemetry_transport import (
    DEFAULT_TELEMETRY_CONTRACT,
    DEFAULT_TRANSPORT_CONTRACT,
    MasterTelemetryReceiver,
    NodeRegistration,
    build_signed_envelope,
)


LOOPBACK_HOST = "127.0.0.1"
FIXED_LOOPBACK_PORT = 54443
FIXED_ENDPOINT_ID = "viv-fixed-loopback-master-rehearsal-001"
EXPECTED_PARENT_RECEIPT_SHA256 = "C09D376EEF8B592F8DD0C3CA2DB431BF82633ED00879D4BFAF3C53503BD63CBF"
ADMISSIBLE_NODE_STATES = frozenset({"available", "degraded"})
LOCAL_HOLD_NODE_STATES = frozenset({"offline", "revoked"})
MAX_ADMISSION_SAMPLES = 3
HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SNAPSHOT_FIELDS = frozenset(
    {
        "state",
        "endpoint_id",
        "host",
        "port",
        "tls_version",
        "tls_handshake_verified",
        "client_certificate_verified",
        "peer_node_id",
        "listener_active",
        "local_loopback_only",
        "local_loopback_socket_enabled",
        "socket_closed",
        "external_network_contacted",
        "network_write_authorized",
        "application_frame_received",
        "application_frame_accepted",
        "one_session_only",
        "persistent_listener_started",
        "automatic_retry",
        "automatic_reauthorization",
        "raw_payload_persisted",
        "last_failure",
        "last_failure_sha256",
    }
)


class LocalMasterTelemetryError(ValueError):
    """Raised for invalid local lifecycle configuration or snapshot data."""


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest().upper()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _aggregate(
    *,
    accepted: bool,
    reason_code: str,
    lifecycle_state: str,
    node_state: str | None,
    sequence: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "accepted": accepted,
        "reason_code": reason_code,
        "lifecycle_state": lifecycle_state,
        "node_state": node_state,
        "sequence": sequence,
        "raw_payload_returned": False,
        "raw_payload_persisted": False,
        "private_payload_persisted": False,
        "automatic_retry": False,
        "automatic_resume": False,
        "network_socket_used": False,
        "network_write_authorized": False,
        "external_network_contacted": False,
        "knowledge_shared_with_master": False,
        "scratchpad_emitted": False,
        "expert_content_emitted": False,
    }
    result.update(extra)
    return result


class LocalMasterTelemetryLifecycle:
    """Manage one in-process telemetry admission session."""

    def __init__(
        self,
        *,
        node_id: str,
        key_id: str,
        secret: bytes,
        node_identity_hash: str,
        parent_listener_receipt_sha256: str = EXPECTED_PARENT_RECEIPT_SHA256,
        receiver: MasterTelemetryReceiver | None = None,
        telemetry_contract_path: Path = DEFAULT_TELEMETRY_CONTRACT,
        transport_contract_path: Path = DEFAULT_TRANSPORT_CONTRACT,
        max_admission_samples: int = MAX_ADMISSION_SAMPLES,
    ) -> None:
        if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
            raise LocalMasterTelemetryError("local_master_node_id_invalid")
        if not isinstance(key_id, str) or not key_id or len(key_id) > 256:
            raise LocalMasterTelemetryError("local_master_key_id_invalid")
        if not isinstance(secret, bytes) or len(secret) < 32:
            raise LocalMasterTelemetryError("local_master_secret_must_be_at_least_32_bytes")
        if not _is_hash(node_identity_hash):
            raise LocalMasterTelemetryError("local_master_node_identity_hash_invalid")
        if not _is_hash(parent_listener_receipt_sha256):
            raise LocalMasterTelemetryError("local_master_parent_receipt_hash_invalid")
        if isinstance(max_admission_samples, bool) or not isinstance(max_admission_samples, int) or max_admission_samples <= 0:
            raise LocalMasterTelemetryError("local_master_sample_budget_invalid")
        self.node_id = node_id
        self.key_id = key_id
        self.node_identity_hash = node_identity_hash.upper()
        self.parent_listener_receipt_sha256 = parent_listener_receipt_sha256.upper()
        self._secret = secret
        self.telemetry_contract_path = Path(telemetry_contract_path)
        self.transport_contract_path = Path(transport_contract_path)
        self.max_admission_samples = max_admission_samples
        self.receiver = receiver or MasterTelemetryReceiver(
            transport_contract_path=self.transport_contract_path,
            telemetry_contract_path=self.telemetry_contract_path,
        )
        self.receiver.register_node(
            NodeRegistration(
                node_id=self.node_id,
                key_id=self.key_id,
                secret=secret,
                node_identity_hash=self.node_identity_hash,
            )
        )
        self._lifecycle_state = "READY"
        self._attempts = 0
        self._accepted_samples = 0
        self._last_sequence: int | None = None

    def admit_health_sample(
        self,
        snapshot: Mapping[str, Any] | Any,
        *,
        sequence: int,
        listener_receipt_sha256: str,
        emitted_utc: str | None = None,
        nonce: str | None = None,
    ) -> dict[str, Any]:
        """Admit one aggregate health sample, or return a safe hold receipt."""
        if self._attempts >= self.max_admission_samples:
            return _aggregate(
                accepted=False,
                reason_code="telemetry_sample_budget_exceeded",
                lifecycle_state=self._lifecycle_state,
                node_state=None,
                sequence=sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None,
                attempts=self._attempts,
                max_admission_samples=self.max_admission_samples,
            )
        self._attempts += 1
        if self._lifecycle_state in {"OFFLINE_HOLD", "REVOKED_HOLD", "CLOSED"}:
            return _aggregate(
                accepted=False,
                reason_code="lifecycle_resume_required",
                lifecycle_state=self._lifecycle_state,
                node_state=None,
                sequence=sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None,
                attempts=self._attempts,
                resume_required=True,
            )
        try:
            self._validate_receipt_binding(listener_receipt_sha256)
            self._validate_sequence(sequence)
            selected_time = emitted_utc or _utc_now()
            if not isinstance(selected_time, str) or UTC_RE.fullmatch(selected_time) is None:
                raise LocalMasterTelemetryError("telemetry_emitted_utc_invalid")
            normalized = self._validate_snapshot(snapshot)
            node_state = self._node_state(normalized)
            if node_state in LOCAL_HOLD_NODE_STATES:
                self._lifecycle_state = "REVOKED_HOLD" if node_state == "revoked" else "OFFLINE_HOLD"
                return _aggregate(
                    accepted=False,
                    reason_code="node_state_not_admissible",
                    lifecycle_state=self._lifecycle_state,
                    node_state=node_state,
                    sequence=sequence,
                    attempts=self._attempts,
                    resume_required=True,
                    decision="HOLD_REVOKED_LOCAL_STATE" if node_state == "revoked" else "HOLD_OFFLINE_LOCAL_STATE",
                )
            payload = self._build_health_payload(normalized, node_state=node_state, sequence=sequence, emitted_utc=selected_time)
            selected_nonce = nonce or _hash_text(f"{self.node_id}:{sequence}:{self._attempts}")
            envelope = build_signed_envelope(
                payload,
                node_id=self.node_id,
                key_id=self.key_id,
                secret=self._secret,
                sequence=sequence,
                nonce=selected_nonce,
                transport_contract_path=self.transport_contract_path,
                telemetry_contract_path=self.telemetry_contract_path,
            )
            receipt = self.receiver.admit(envelope)
            accepted = receipt.get("accepted") is True
            if accepted:
                self._accepted_samples += 1
                self._last_sequence = sequence
                self._lifecycle_state = "AVAILABLE" if node_state == "available" else "DEGRADED"
            elif receipt.get("reason_code") in {"transport_sequence_replay", "transport_nonce_replay"}:
                self._lifecycle_state = "DEGRADED"
            return _aggregate(
                accepted=accepted,
                reason_code=str(receipt.get("reason_code", "telemetry_admission_rejected")),
                lifecycle_state=self._lifecycle_state,
                node_state=node_state,
                sequence=sequence,
                attempts=self._attempts,
                accepted_samples=self._accepted_samples,
                max_admission_samples=self.max_admission_samples,
                **{key: value for key, value in receipt.items() if key not in {"accepted", "reason_code", "node_state", "sequence"}},
            )
        except (LocalMasterTelemetryError, ValueError) as exc:
            return _aggregate(
                accepted=False,
                reason_code=str(exc),
                lifecycle_state=self._lifecycle_state,
                node_state=None,
                sequence=sequence if isinstance(sequence, int) and not isinstance(sequence, bool) else None,
                attempts=self._attempts,
                accepted_samples=self._accepted_samples,
            )

    def resume(
        self,
        snapshot: Mapping[str, Any] | Any,
        *,
        listener_receipt_sha256: str,
    ) -> dict[str, Any]:
        """Explicitly leave an offline hold only after a fresh valid snapshot."""
        if self._lifecycle_state not in {"OFFLINE_HOLD", "REVOKED_HOLD"}:
            return _aggregate(
                accepted=False,
                reason_code="explicit_resume_not_required",
                lifecycle_state=self._lifecycle_state,
                node_state=None,
                resume_required=False,
            )
        try:
            self._validate_receipt_binding(listener_receipt_sha256)
            normalized = self._validate_snapshot(snapshot)
            if not normalized["listener_active"] or normalized["state"] not in {"LISTENING", "SERVING"}:
                raise LocalMasterTelemetryError("fresh_active_loopback_snapshot_required")
            if normalized["last_failure"] is not None:
                raise LocalMasterTelemetryError("fresh_failure_free_loopback_snapshot_required")
            self._lifecycle_state = "READY"
            return _aggregate(
                accepted=True,
                reason_code="explicit_resume_accepted",
                lifecycle_state=self._lifecycle_state,
                node_state="available",
                resume_required=False,
            )
        except (LocalMasterTelemetryError, ValueError) as exc:
            return _aggregate(
                accepted=False,
                reason_code=str(exc),
                lifecycle_state=self._lifecycle_state,
                node_state=None,
                resume_required=True,
            )

    def close(self) -> dict[str, Any]:
        """Close the local session without retry or persistence."""
        self._lifecycle_state = "CLOSED"
        return _aggregate(
            accepted=True,
            reason_code="local_master_telemetry_session_closed",
            lifecycle_state=self._lifecycle_state,
            node_state="offline",
            resume_required=True,
            attempts=self._attempts,
            accepted_samples=self._accepted_samples,
        )

    def snapshot(self) -> dict[str, Any]:
        """Return lifecycle counters only; never return the telemetry payload."""
        return {
            "lifecycle_state": self._lifecycle_state,
            "node_id": self.node_id,
            "key_id": self.key_id,
            "attempts": self._attempts,
            "accepted_samples": self._accepted_samples,
            "last_sequence": self._last_sequence,
            "max_admission_samples": self.max_admission_samples,
            "raw_payload_returned": False,
            "raw_payload_persisted": False,
            "private_payload_persisted": False,
            "runtime_state_persisted": False,
            "network_socket_used": False,
            "external_network_contacted": False,
            "automatic_retry": False,
            "automatic_resume": False,
        }

    def _validate_receipt_binding(self, value: str) -> None:
        if not isinstance(value, str) or value.upper() != self.parent_listener_receipt_sha256:
            raise LocalMasterTelemetryError("parent_listener_receipt_hash_mismatch")

    @staticmethod
    def _validate_sequence(sequence: int) -> None:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise LocalMasterTelemetryError("telemetry_sequence_invalid")

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, Any] | Any) -> dict[str, Any]:
        if not isinstance(snapshot, Mapping):
            raise LocalMasterTelemetryError("loopback_snapshot_must_be_object")
        unknown = sorted(set(snapshot) - SNAPSHOT_FIELDS)
        if unknown:
            raise LocalMasterTelemetryError("loopback_snapshot_unknown_fields:" + ",".join(str(value) for value in unknown))
        required = SNAPSHOT_FIELDS
        if not required.issubset(snapshot):
            missing = sorted(required - set(snapshot))
            raise LocalMasterTelemetryError("loopback_snapshot_required_fields_missing:" + ",".join(missing))
        if snapshot.get("endpoint_id") != FIXED_ENDPOINT_ID:
            raise LocalMasterTelemetryError("loopback_snapshot_endpoint_id_invalid")
        if snapshot.get("host") != LOOPBACK_HOST:
            raise LocalMasterTelemetryError("loopback_snapshot_host_not_loopback")
        if snapshot.get("port") != FIXED_LOOPBACK_PORT:
            raise LocalMasterTelemetryError("loopback_snapshot_port_invalid")
        if snapshot.get("state") not in {"LISTENING", "SERVING", "CLOSED"}:
            raise LocalMasterTelemetryError("loopback_snapshot_state_invalid")
        for field in (
            "tls_handshake_verified",
            "client_certificate_verified",
            "listener_active",
            "local_loopback_only",
            "local_loopback_socket_enabled",
            "socket_closed",
            "external_network_contacted",
            "network_write_authorized",
            "application_frame_received",
            "application_frame_accepted",
            "one_session_only",
            "persistent_listener_started",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_payload_persisted",
        ):
            if not isinstance(snapshot.get(field), bool):
                raise LocalMasterTelemetryError(f"loopback_snapshot_boolean_invalid:{field}")
        if snapshot["local_loopback_only"] is not True:
            raise LocalMasterTelemetryError("loopback_snapshot_local_only_required")
        for field in (
            "external_network_contacted",
            "network_write_authorized",
            "persistent_listener_started",
            "automatic_retry",
            "automatic_reauthorization",
            "raw_payload_persisted",
            "one_session_only",
        ):
            if snapshot[field] is not False and field != "one_session_only":
                raise LocalMasterTelemetryError(f"loopback_snapshot_{field}_must_be_false")
        if snapshot["one_session_only"] is not True:
            raise LocalMasterTelemetryError("loopback_snapshot_one_session_required")
        if snapshot["local_loopback_socket_enabled"] is not snapshot["listener_active"]:
            raise LocalMasterTelemetryError("loopback_snapshot_socket_state_mismatch")
        if snapshot["socket_closed"] is not (not snapshot["listener_active"]):
            raise LocalMasterTelemetryError("loopback_snapshot_closed_state_mismatch")
        if snapshot["state"] in {"LISTENING", "SERVING"} and not snapshot["listener_active"]:
            raise LocalMasterTelemetryError("loopback_snapshot_active_state_mismatch")
        if snapshot["state"] == "CLOSED" and snapshot["listener_active"]:
            raise LocalMasterTelemetryError("loopback_snapshot_closed_active_mismatch")
        tls_version = snapshot.get("tls_version")
        if tls_version not in {None, "TLSv1.3"}:
            raise LocalMasterTelemetryError("loopback_snapshot_tls_version_invalid")
        if snapshot["tls_handshake_verified"] and tls_version != "TLSv1.3":
            raise LocalMasterTelemetryError("loopback_snapshot_tls_verification_mismatch")
        if snapshot["application_frame_accepted"] and not snapshot["application_frame_received"]:
            raise LocalMasterTelemetryError("loopback_snapshot_frame_state_mismatch")
        for field in ("last_failure", "peer_node_id", "last_failure_sha256"):
            value = snapshot.get(field)
            if value is not None and (not isinstance(value, str) or len(value) > 256):
                raise LocalMasterTelemetryError(f"loopback_snapshot_optional_field_invalid:{field}")
        if snapshot["last_failure"] is not None:
            if not _is_hash(snapshot["last_failure_sha256"]):
                raise LocalMasterTelemetryError("loopback_snapshot_failure_hash_invalid")
        elif snapshot["last_failure_sha256"] is not None:
            raise LocalMasterTelemetryError("loopback_snapshot_orphan_failure_hash")
        return dict(snapshot)

    @staticmethod
    def _node_state(snapshot: Mapping[str, Any]) -> str:
        if snapshot["last_failure"] is not None:
            return "degraded"
        if snapshot["state"] in {"LISTENING", "SERVING"} and snapshot["listener_active"]:
            return "available"
        return "offline"

    def _build_health_payload(
        self,
        snapshot: Mapping[str, Any],
        *,
        node_state: str,
        sequence: int,
        emitted_utc: str,
    ) -> dict[str, Any]:
        failure_count = 1 if snapshot["last_failure"] is not None else 0
        identity_prefix = self.node_id
        return {
            "schema_version": str(self.receiver.telemetry_contract["schema_version"]),
            "contract_id": str(self.receiver.telemetry_contract["contract_id"]),
            "message_type": "health_sample",
            "node_id": self.node_id,
            "sequence": sequence,
            "emitted_utc": emitted_utc,
            "node_state": node_state,
            "identity_attestation": {
                "node_identity_hash": self.node_identity_hash,
                "identity_contract_hash": _hash_text(f"{identity_prefix}:identity-contract"),
                "runtime_hash": _hash_text(f"{identity_prefix}:runtime"),
                "cpu_authority_contract_hash": _hash_text(f"{identity_prefix}:cpu-authority"),
            },
            "health": {
                "heartbeat_latency_ms": 0.0,
                "last_successful_probe_utc": emitted_utc,
                "probe_pass_rate": 1.0 if failure_count == 0 else 0.0,
                "failure_count": failure_count,
                "drift_score": 0.0,
                "queue_depth": 0.0,
            },
            "resource": {
                "cpu_load_pct": 0.0,
                "gpu_load_pct": 0.0,
                "memory_used_pct": 0.0,
                "gpu_memory_used_pct": 0.0,
                "cpu_temperature_c": 0.0,
                "gpu_temperature_c": 0.0,
                "power_w": 0.0,
            },
            "security": {
                "telemetry_leak_count": 0,
                "private_identity_leak_count": 0,
                "boundary_violation_count": 0,
                "quarantine_reason_code": "",
                "revocation_epoch": 0,
            },
            "lineage": {
                "checkpoint_hash": _hash_text(f"{identity_prefix}:checkpoint"),
                "router_state_hash": _hash_text(f"{identity_prefix}:router"),
                "moe_spec_hash": _hash_text(f"{identity_prefix}:moe"),
                "training_knobs_hash": _hash_text(f"{identity_prefix}:training-knobs"),
                "telemetry_contract_hash": _hash_text(f"{identity_prefix}:telemetry-contract"),
            },
            "capabilities": {
                "local_moe_enabled": True,
                "scratchpad_ephemeral": True,
                "cpu_authority_enabled": True,
                "knowledge_shared_with_master": False,
            },
            "boundary_attestation": {
                "content_plane_closed": True,
                "raw_payloads_emitted": False,
                "scratchpad_emitted": False,
                "expert_content_emitted": False,
            },
        }


__all__ = [
    "ADMISSIBLE_NODE_STATES",
    "FIXED_ENDPOINT_ID",
    "FIXED_LOOPBACK_PORT",
    "LOOPBACK_HOST",
    "LocalMasterTelemetryError",
    "LocalMasterTelemetryLifecycle",
]
