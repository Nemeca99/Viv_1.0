"""Offline/in-process federation channel for the Viv node boundary.

This is deliberately a channel adapter, not a network implementation.  It
connects the local node client to the in-process Master registry so the full
sign -> transport -> admission path can be tested with real CNG keys.  It has
no socket, queue, subprocess, or persistence behavior and cannot be switched
into a live network mode through this API.
"""
from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Any, Mapping

from lib.node_federation import (
    DEFAULT_FEDERATION_CONTRACT,
    DEFAULT_TELEMETRY_CONTRACT,
    FederationError,
    MasterFederationRegistry,
    SIGNATURE_ALGORITHM,
    _require_asymmetric_backend,
    build_signed_attestation,
)


CHANNEL_MODE = "IN_PROCESS_ONLY"


class FederationChannelError(ValueError):
    """Raised when the closed in-process channel cannot transmit an envelope."""


@dataclass(frozen=True)
class ChannelReceipt:
    """Aggregate channel metadata; it intentionally has no payload field."""

    accepted: bool
    reason_code: str
    channel_mode: str = CHANNEL_MODE
    network_socket_enabled: bool = False
    network_write_authorized: bool = False
    raw_payload_persisted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "channel_mode": self.channel_mode,
            "network_socket_enabled": self.network_socket_enabled,
            "network_write_authorized": self.network_write_authorized,
            "raw_payload_persisted": self.raw_payload_persisted,
        }


class InProcessFederationChannel:
    """Closed channel that dispatches only to a local Master registry."""

    def __init__(self, registry: MasterFederationRegistry, verifier: Any) -> None:
        if not isinstance(registry, MasterFederationRegistry):
            raise FederationChannelError("federation_channel_requires_master_registry")
        try:
            _require_asymmetric_backend(verifier, "verifier")
        except FederationError as exc:
            raise FederationChannelError(str(exc)) from exc
        self._registry = registry
        self._verifier = verifier
        self._closed = False

    def transmit(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """Dispatch one transient envelope and return aggregate admission only."""
        if self._closed:
            return ChannelReceipt(False, "federation_channel_closed").as_dict()
        receipt = self._registry.admit(envelope, self._verifier)
        output = dict(receipt)
        output.update(
            {
                "channel_mode": CHANNEL_MODE,
                "network_socket_enabled": False,
                "network_write_authorized": False,
                "raw_payload_persisted": False,
            }
        )
        output.pop("payload", None)
        return output

    def close(self) -> None:
        self._closed = True

    def snapshot(self) -> dict[str, Any]:
        return {
            "channel_mode": CHANNEL_MODE,
            "closed": self._closed,
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "raw_payload_persisted": False,
        }


class NodeFederationClient:
    """Node-side automatic attestation client with process-scoped counters."""

    def __init__(
        self,
        *,
        node_id: str,
        key_id: str,
        public_key_sha256: str,
        signer: Any,
        channel: Any,
        federation_contract_path=DEFAULT_FEDERATION_CONTRACT,
        telemetry_contract_path=DEFAULT_TELEMETRY_CONTRACT,
    ) -> None:
        try:
            _require_asymmetric_backend(signer, "signer")
        except FederationError as exc:
            raise FederationChannelError(str(exc)) from exc
        if not callable(getattr(channel, "transmit", None)) or not callable(getattr(channel, "snapshot", None)):
            raise FederationChannelError("federation_client_requires_closed_channel_interface")
        channel_snapshot = channel.snapshot()
        if channel_snapshot.get("network_socket_enabled", False) is not False:
            raise FederationChannelError("federation_client_network_socket_must_be_closed")
        if channel_snapshot.get("network_write_authorized", False) is not False:
            raise FederationChannelError("federation_client_network_write_must_be_closed")
        self.node_id = node_id
        self.key_id = key_id
        self.public_key_sha256 = public_key_sha256
        self.signer = signer
        self.channel = channel
        self.federation_contract_path = federation_contract_path
        self.telemetry_contract_path = telemetry_contract_path
        self._next_sequence = 0
        self._sent_count = 0

    def send(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Sign and dispatch one telemetry message without retaining its body."""
        channel_snapshot = self.channel.snapshot()
        if channel_snapshot.get("closed", False) or channel_snapshot.get("state") not in {None, "ACTIVE"}:
            return ChannelReceipt(
                False,
                str(channel_snapshot.get("send_block_reason", "federation_channel_closed")),
            ).as_dict()
        sequence = self._next_sequence
        self._next_sequence += 1
        envelope = build_signed_attestation(
            payload,
            node_id=self.node_id,
            key_id=self.key_id,
            public_key_sha256=self.public_key_sha256,
            signer=self.signer,
            sequence=sequence,
            nonce=secrets.token_hex(16),
            federation_contract_path=self.federation_contract_path,
            telemetry_contract_path=self.telemetry_contract_path,
        )
        try:
            receipt = self.channel.transmit(envelope)
        finally:
            del envelope
        self._sent_count += 1
        return receipt

    def snapshot(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "key_id": self.key_id,
            "signature_algorithm": SIGNATURE_ALGORITHM,
            "next_sequence": self._next_sequence,
            "sent_count": self._sent_count,
            "payload_retained": False,
            "persistent_state_written": False,
            "network_socket_enabled": False,
            "network_write_authorized": False,
        }


__all__ = [
    "CHANNEL_MODE",
    "FederationChannelError",
    "InProcessFederationChannel",
    "NodeFederationClient",
]
