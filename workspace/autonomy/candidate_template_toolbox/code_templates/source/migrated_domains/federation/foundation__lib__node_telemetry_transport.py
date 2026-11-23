"""Offline authenticated transport prototype for node telemetry.

The module signs only an already-validated, content-minimized telemetry
envelope. It provides no socket, queue, persistence, key-file, or network
integration. HMAC-SHA256 is deliberately described as shared-secret
authentication, not as an asymmetric node signature.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
from pathlib import Path
import secrets
from typing import Any, Mapping

from lib.node_telemetry_contract import TelemetryContractError, load_contract, validate_telemetry


HERE = Path(__file__).resolve().parent
DEFAULT_TRANSPORT_CONTRACT = HERE.parent / "artifacts" / "auto" / "agentic" / "NODE_TELEMETRY_TRANSPORT_CONTRACT.json"
DEFAULT_TELEMETRY_CONTRACT = HERE.parent / "artifacts" / "auto" / "agentic" / "NODE_TELEMETRY_CONTRACT.json"
TRANSPORT_SCHEMA_VERSION = "viv_node_telemetry_transport_contract_v1"
MAX_ENVELOPE_BYTES = 65536


class TelemetryTransportError(ValueError):
    """Raised when an authenticated telemetry envelope cannot be admitted."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_transport_contract(path: Path = DEFAULT_TRANSPORT_CONTRACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TelemetryTransportError("transport_contract_must_be_object")
    return value


def _signature(body: Mapping[str, Any], secret: bytes) -> str:
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise TelemetryTransportError("node_shared_secret_must_be_at_least_32_bytes")
    return hmac.new(secret, _canonical(body), sha256).hexdigest()


def _signed_body(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {key: envelope[key] for key in (
        "transport_schema_version",
        "transport_contract_id",
        "telemetry_contract_sha256",
        "node_id",
        "key_id",
        "sequence",
        "nonce",
        "payload_sha256",
        "payload",
    )}


def build_signed_envelope(
    payload: Mapping[str, Any],
    *,
    node_id: str,
    key_id: str,
    secret: bytes,
    sequence: int,
    nonce: str | None = None,
    transport_contract_path: Path = DEFAULT_TRANSPORT_CONTRACT,
    telemetry_contract_path: Path = DEFAULT_TELEMETRY_CONTRACT,
) -> dict[str, Any]:
    """Validate and authenticate one telemetry payload without sending it."""
    telemetry_contract = load_contract(telemetry_contract_path)
    validate_telemetry(payload, telemetry_contract)
    transport_contract = load_transport_contract(transport_contract_path)
    if transport_contract.get("status") != "OFFLINE_AUTHENTICATED_ENVELOPE_PROTOTYPE_NO_NETWORK":
        raise TelemetryTransportError("transport_contract_not_offline_prototype")
    if not isinstance(node_id, str) or not node_id or len(node_id) > 256:
        raise TelemetryTransportError("transport_node_id_invalid")
    if not isinstance(key_id, str) or not key_id or len(key_id) > 256:
        raise TelemetryTransportError("transport_key_id_invalid")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise TelemetryTransportError("transport_sequence_invalid")
    selected_nonce = nonce or secrets.token_hex(16)
    if not isinstance(selected_nonce, str) or len(selected_nonce) < 32 or len(selected_nonce) > 256:
        raise TelemetryTransportError("transport_nonce_invalid")
    if payload.get("node_id") != node_id:
        raise TelemetryTransportError("transport_node_id_payload_mismatch")
    payload_bytes = _canonical(payload)
    envelope = {
        "transport_schema_version": str(transport_contract["schema_version"]),
        "transport_contract_id": str(transport_contract["contract_id"]),
        "telemetry_contract_sha256": sha256_file(telemetry_contract_path),
        "node_id": node_id,
        "key_id": key_id,
        "sequence": sequence,
        "nonce": selected_nonce,
        "payload_sha256": sha256_bytes(payload_bytes),
        "payload": dict(payload),
    }
    envelope["signature"] = _signature(_signed_body(envelope), secret)
    encoded = _canonical(envelope)
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise TelemetryTransportError("transport_envelope_too_large")
    return envelope


@dataclass(frozen=True)
class NodeRegistration:
    node_id: str
    key_id: str
    secret: bytes
    node_identity_hash: str
    revoked: bool = False


class MasterTelemetryReceiver:
    """In-process Master admission gate with replay and registry binding."""

    def __init__(self, *, transport_contract_path: Path = DEFAULT_TRANSPORT_CONTRACT, telemetry_contract_path: Path = DEFAULT_TELEMETRY_CONTRACT):
        self.transport_contract_path = transport_contract_path
        self.telemetry_contract_path = telemetry_contract_path
        self.transport_contract = load_transport_contract(transport_contract_path)
        self.telemetry_contract = load_contract(telemetry_contract_path)
        self._registrations: dict[tuple[str, str], NodeRegistration] = {}
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._nonces: set[tuple[str, str, str]] = set()

    def register_node(self, registration: NodeRegistration) -> None:
        if len(registration.secret) < 32:
            raise TelemetryTransportError("registered_shared_secret_too_short")
        self._registrations[(registration.node_id, registration.key_id)] = registration

    def revoke_node(self, node_id: str, key_id: str) -> None:
        registration = self._registrations.get((node_id, key_id))
        if registration is None:
            raise TelemetryTransportError("node_registration_missing")
        self._registrations[(node_id, key_id)] = NodeRegistration(
            node_id=registration.node_id,
            key_id=registration.key_id,
            secret=registration.secret,
            node_identity_hash=registration.node_identity_hash,
            revoked=True,
        )

    def admit(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        """Return an aggregate receipt; never return or persist the payload."""
        try:
            return self._admit(envelope)
        except (TelemetryTransportError, TelemetryContractError) as exc:
            return {"accepted": False, "reason_code": str(exc)}

    def _admit(self, envelope: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(envelope, Mapping):
            raise TelemetryTransportError("transport_envelope_must_be_object")
        if len(_canonical(envelope)) > MAX_ENVELOPE_BYTES:
            raise TelemetryTransportError("transport_envelope_too_large")
        expected_keys = {
            "transport_schema_version", "transport_contract_id", "telemetry_contract_sha256", "node_id", "key_id",
            "sequence", "nonce", "payload_sha256", "payload", "signature",
        }
        if set(envelope) != expected_keys:
            raise TelemetryTransportError("transport_wrapper_fields_mismatch")
        if envelope["transport_schema_version"] != self.transport_contract["schema_version"] or envelope["transport_contract_id"] != self.transport_contract["contract_id"]:
            raise TelemetryTransportError("transport_contract_identity_mismatch")
        if envelope["telemetry_contract_sha256"] != sha256_file(self.telemetry_contract_path):
            raise TelemetryTransportError("telemetry_contract_hash_mismatch")
        node_id = envelope["node_id"]
        key_id = envelope["key_id"]
        registration = self._registrations.get((node_id, key_id))
        if registration is None:
            raise TelemetryTransportError("node_registration_missing")
        if registration.revoked:
            raise TelemetryTransportError("node_revoked")
        payload = envelope["payload"]
        if not isinstance(payload, Mapping) or payload.get("node_id") != node_id:
            raise TelemetryTransportError("transport_payload_node_mismatch")
        if sha256_bytes(_canonical(payload)) != envelope["payload_sha256"]:
            raise TelemetryTransportError("transport_payload_hash_mismatch")
        expected_signature = _signature(_signed_body(envelope), registration.secret)
        if not isinstance(envelope["signature"], str) or not hmac.compare_digest(envelope["signature"], expected_signature):
            raise TelemetryTransportError("transport_hmac_mismatch")
        validate_telemetry(payload, self.telemetry_contract)
        identity = payload["identity_attestation"]
        if identity["node_identity_hash"] != registration.node_identity_hash:
            raise TelemetryTransportError("node_identity_binding_mismatch")
        if payload["node_state"] in {"revoked", "offline"}:
            raise TelemetryTransportError("node_state_not_admissible")
        sequence = envelope["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise TelemetryTransportError("transport_sequence_invalid")
        key = (node_id, key_id)
        if sequence <= self._last_sequence.get(key, -1):
            raise TelemetryTransportError("transport_sequence_replay")
        nonce_key = (node_id, key_id, str(envelope["nonce"]))
        if nonce_key in self._nonces:
            raise TelemetryTransportError("transport_nonce_replay")
        self._last_sequence[key] = sequence
        self._nonces.add(nonce_key)
        return {
            "accepted": True,
            "reason_code": "telemetry_admitted",
            "node_id": node_id,
            "key_id": key_id,
            "sequence": sequence,
            "payload_sha256": envelope["payload_sha256"],
            "telemetry_contract_sha256": envelope["telemetry_contract_sha256"],
            "signature_verified": True,
            "raw_payload_persisted": False,
        }


__all__ = ["MasterTelemetryReceiver", "NodeRegistration", "TelemetryTransportError", "build_signed_envelope", "load_transport_contract"]
