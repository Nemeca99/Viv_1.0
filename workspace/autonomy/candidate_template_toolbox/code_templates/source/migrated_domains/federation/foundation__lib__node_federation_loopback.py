"""Offline policy harness for the selected TLS 1.3 mutual-auth mode.

This module models the transport state machine without importing ``socket``
or ``ssl`` and without performing a TLS handshake.  It exercises the
application envelope and the resource/failure controls that must surround the
eventual secure transport.  The receipt explicitly distinguishes policy
simulation from cryptographic TLS verification.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Mapping

from lib.node_federation import FederationError, MasterFederationRegistry, _require_asymmetric_backend
from lib.node_federation_transport import CHANNEL_MODE, ChannelReceipt


NETWORK_MODE = "TLS_1_3_MUTUAL_AUTH"
TLS_VERSION = "TLS1.3"
MAX_DEFAULT_FRAME_BYTES = 65536
MAX_DEFAULT_FRAMES_PER_SESSION = 256
MAX_DEFAULT_IN_FLIGHT = 2


class LoopbackTransportError(ValueError):
    """Raised when the offline transport policy harness is misconfigured."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest().upper()


class OfflineTlsLoopbackHarness:
    """A closed, deterministic policy harness around the Master registry."""

    def __init__(
        self,
        registry: MasterFederationRegistry,
        verifier: Any,
        *,
        max_frame_bytes: int = MAX_DEFAULT_FRAME_BYTES,
        max_frames_per_session: int = MAX_DEFAULT_FRAMES_PER_SESSION,
        max_in_flight_frames: int = MAX_DEFAULT_IN_FLIGHT,
    ) -> None:
        if not isinstance(registry, MasterFederationRegistry):
            raise LoopbackTransportError("loopback_requires_master_registry")
        try:
            _require_asymmetric_backend(verifier, "verifier")
        except FederationError as exc:
            raise LoopbackTransportError(str(exc)) from exc
        if max_frame_bytes <= 0 or max_frame_bytes > MAX_DEFAULT_FRAME_BYTES:
            raise LoopbackTransportError("loopback_frame_budget_invalid")
        if max_frames_per_session <= 0 or max_frames_per_session > MAX_DEFAULT_FRAMES_PER_SESSION:
            raise LoopbackTransportError("loopback_session_frame_budget_invalid")
        if max_in_flight_frames <= 0 or max_in_flight_frames > MAX_DEFAULT_IN_FLIGHT:
            raise LoopbackTransportError("loopback_in_flight_budget_invalid")
        self._registry = registry
        self._verifier = verifier
        self._max_frame_bytes = max_frame_bytes
        self._max_frames_per_session = max_frames_per_session
        self._max_in_flight_frames = max_in_flight_frames
        self._state = "CLOSED"
        self._session_id: str | None = None
        self._node_id: str | None = None
        self._key_id: str | None = None
        self._frames_attempted = 0
        self._frames_accepted = 0
        self._last_failure: str | None = None

    def open_session(
        self,
        *,
        node_id: str,
        key_id: str,
        session_id: str,
        tls_version: str = TLS_VERSION,
        mutual_auth_verified: bool = True,
        client_identity_verified: bool = True,
    ) -> dict[str, Any]:
        """Open a simulated authenticated session; no TLS/socket is created."""
        if self._state == "ACTIVE":
            return self._failure("loopback_session_already_active")
        if self._state in {"DEGRADED", "QUARANTINED"}:
            return self._failure("loopback_operator_resume_required")
        if not isinstance(node_id, str) or not node_id or not isinstance(key_id, str) or not key_id:
            return self._failure("loopback_identity_fields_invalid")
        if not isinstance(session_id, str) or len(session_id) < 32 or len(session_id) > 256:
            return self._failure("loopback_session_id_invalid")
        if tls_version != TLS_VERSION:
            return self._failure("loopback_tls_version_not_allowlisted")
        if mutual_auth_verified is not True or client_identity_verified is not True:
            return self._failure("loopback_mutual_authentication_failed")
        self._state = "ACTIVE"
        self._session_id = session_id
        self._node_id = node_id
        self._key_id = key_id
        self._frames_attempted = 0
        self._frames_accepted = 0
        self._last_failure = None
        return {
            "accepted": True,
            "reason_code": "loopback_tls_policy_session_opened",
            "network_mode": NETWORK_MODE,
            "tls_version": TLS_VERSION,
            "mutual_auth_verified": True,
            "client_identity_verified": True,
            "simulated_handshake": True,
            "tls_confidentiality_runtime_verified": False,
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "raw_payload_persisted": False,
        }

    def transmit(self, envelope: Mapping[str, Any], *, in_flight_frames: int = 1) -> dict[str, Any]:
        """Apply frame/session/budget policy, then dispatch to Master admission."""
        if self._state != "ACTIVE":
            return self._failure(self._send_block_reason())
        if not isinstance(envelope, Mapping):
            return self._failure("loopback_frame_must_be_object")
        if isinstance(in_flight_frames, bool) or not isinstance(in_flight_frames, int) or in_flight_frames < 1:
            return self._failure("loopback_in_flight_count_invalid")
        if in_flight_frames > self._max_in_flight_frames:
            return self._failure("loopback_in_flight_budget_exceeded")
        frame_bytes = _canonical(envelope)
        if len(frame_bytes) > self._max_frame_bytes:
            return self._failure("loopback_frame_too_large")
        self._frames_attempted += 1
        if self._frames_attempted > self._max_frames_per_session:
            return self._failure("loopback_session_frame_budget_exceeded")
        receipt = self._registry.admit(envelope, self._verifier)
        if receipt.get("accepted") is True:
            self._frames_accepted += 1
        output = dict(receipt)
        output.update(
            {
                "network_mode": NETWORK_MODE,
                "tls_version": TLS_VERSION,
                "session_bound": True,
                "simulated_handshake": True,
                "tls_confidentiality_runtime_verified": False,
                "network_socket_enabled": False,
                "network_write_authorized": False,
                "raw_payload_persisted": False,
            }
        )
        output.pop("payload", None)
        return output

    def transmit_with_session(
        self,
        envelope: Mapping[str, Any],
        *,
        session_id: str,
        in_flight_frames: int = 1,
    ) -> dict[str, Any]:
        if self._state != "ACTIVE":
            return self._failure(self._send_block_reason())
        if session_id != self._session_id:
            return self._failure("loopback_session_binding_failed")
        return self.transmit(envelope, in_flight_frames=in_flight_frames)

    def mark_degraded(self, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason or len(reason) > 256:
            return self._failure("loopback_degraded_reason_invalid")
        self._state = "DEGRADED"
        self._last_failure = _hash_text(reason)
        return {
            "accepted": False,
            "reason_code": "loopback_degraded",
            "reason_sha256": self._last_failure,
            "operator_resume_required": True,
            "raw_reason_persisted": False,
        }

    def quarantine(self, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason or len(reason) > 256:
            return self._failure("loopback_quarantine_reason_invalid")
        self._state = "QUARANTINED"
        self._last_failure = _hash_text(reason)
        return {
            "accepted": False,
            "reason_code": "loopback_quarantined",
            "reason_sha256": self._last_failure,
            "operator_resume_required": True,
            "raw_reason_persisted": False,
        }

    def operator_resume(self, *, explicitly_authorized: bool) -> dict[str, Any]:
        if explicitly_authorized is not True:
            return self._failure("loopback_operator_resume_not_authorized")
        if self._state not in {"DEGRADED", "QUARANTINED"}:
            return self._failure("loopback_operator_resume_not_required")
        self._state = "CLOSED"
        self._session_id = None
        self._node_id = None
        self._key_id = None
        return {
            "accepted": True,
            "reason_code": "loopback_operator_resume_recorded_new_session_required",
            "automatic_reauthorization": False,
            "new_session_required": True,
            "network_socket_enabled": False,
            "network_write_authorized": False,
        }

    def close(self) -> None:
        self._state = "CLOSED"
        self._session_id = None
        self._node_id = None
        self._key_id = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "network_mode": NETWORK_MODE,
            "tls_version": TLS_VERSION,
            "session_bound": self._session_id is not None,
            "session_id_sha256": _hash_text(self._session_id) if self._session_id is not None else None,
            "node_id": self._node_id,
            "key_id": self._key_id,
            "frames_attempted": self._frames_attempted,
            "frames_accepted": self._frames_accepted,
            "max_frame_bytes": self._max_frame_bytes,
            "max_frames_per_session": self._max_frames_per_session,
            "max_in_flight_frames": self._max_in_flight_frames,
            "simulated_handshake": self._state == "ACTIVE",
            "tls_confidentiality_runtime_verified": False,
            "payload_retained": False,
            "raw_payload_persisted": False,
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "send_block_reason": self._send_block_reason(),
        }

    def _send_block_reason(self) -> str:
        return {
            "CLOSED": "loopback_session_closed",
            "DEGRADED": "loopback_degraded_operator_resume_required",
            "QUARANTINED": "loopback_quarantined_operator_resume_required",
        }.get(self._state, "loopback_transport_not_active")

    def _failure(self, reason_code: str) -> dict[str, Any]:
        self._last_failure = reason_code
        return ChannelReceipt(False, reason_code).as_dict()


__all__ = ["LoopbackTransportError", "NETWORK_MODE", "OfflineTlsLoopbackHarness", "TLS_VERSION"]
