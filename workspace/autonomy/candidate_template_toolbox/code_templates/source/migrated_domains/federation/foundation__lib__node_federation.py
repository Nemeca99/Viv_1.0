"""Offline Master federation admission for Viv node telemetry.

This module is the protocol/state-machine boundary for the distributed AIOS
stage.  It deliberately has no socket, queue, subprocess, or file-writing
side effect.  A local node supplies a callable asymmetric signer and the
Master supplies a callable asymmetric verifier.  HMAC is not accepted by
this boundary; the earlier HMAC envelope remains a historical transport
prototype only.

The Master registry receives only public-key identity metadata and the
content-minimized telemetry payload needed by the already-pinned telemetry
contract.  Admission receipts never contain or persist the raw payload.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from lib.node_telemetry_contract import (
    TelemetryContractError,
    load_contract as load_telemetry_contract,
    validate_telemetry,
)


HERE = Path(__file__).resolve().parent
DEFAULT_FEDERATION_CONTRACT = HERE.parent / "artifacts" / "auto" / "agentic" / "NODE_FEDERATION_CONTRACT.json"
DEFAULT_TELEMETRY_CONTRACT = HERE.parent / "artifacts" / "auto" / "agentic" / "NODE_TELEMETRY_CONTRACT.json"
FEDERATION_SCHEMA_VERSION = "viv_node_federation_contract_v1"
MAX_ENVELOPE_BYTES = 65536
HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")
SIGNATURE_HEX_LENGTH = 128  # 64-byte raw ECDSA P-256 r||s signature.
SIGNATURE_ALGORITHM = "ECDSA_P256_SHA256_CNG"


class FederationError(ValueError):
    """Raised when federation metadata or an attestation is not admissible."""


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


def load_federation_contract(path: Path = DEFAULT_FEDERATION_CONTRACT) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FederationError("federation_contract_must_be_object")
    return value


def _validate_identifier(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise FederationError(f"federation_{name}_invalid")


def _validate_hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise FederationError(f"federation_{name}_invalid")


def _validate_public_key_hex(value: Any) -> None:
    if not isinstance(value, str) or not value or len(value) % 2 or HEX_RE.fullmatch(value) is None:
        raise FederationError("federation_public_key_hex_invalid")
    if len(value) > 4096:
        raise FederationError("federation_public_key_too_large")


def _validate_signature(value: Any) -> None:
    if not isinstance(value, str) or len(value) != SIGNATURE_HEX_LENGTH or HEX_RE.fullmatch(value) is None:
        raise FederationError("federation_signature_invalid")


def _require_asymmetric_backend(backend: Any, role: str) -> None:
    if (
        not callable(backend)
        or getattr(backend, "asymmetric", False) is not True
        or getattr(backend, "algorithm", None) != SIGNATURE_ALGORITHM
    ):
        raise FederationError(f"federation_{role}_must_declare_asymmetric_cng_backend")


def _contract_hashes(
    federation_contract_path: Path,
    telemetry_contract_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    federation_contract = load_federation_contract(federation_contract_path)
    telemetry_contract = load_telemetry_contract(telemetry_contract_path)
    if federation_contract.get("status") != "OFFLINE_FEDERATION_STAGE_NO_NETWORK":
        raise FederationError("federation_contract_not_offline")
    return (
        federation_contract,
        telemetry_contract,
        sha256_file(federation_contract_path),
        sha256_file(telemetry_contract_path),
    )


def _attestation_body(envelope: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: envelope[key]
        for key in (
            "federation_schema_version",
            "federation_contract_id",
            "telemetry_contract_sha256",
            "node_id",
            "key_id",
            "public_key_sha256",
            "signature_algorithm",
            "sequence",
            "nonce",
            "payload_sha256",
            "payload",
        )
    }


@dataclass(frozen=True)
class NodeKeyRecord:
    """Public node-key metadata held by the Master registry."""

    node_id: str
    key_id: str
    public_key_hex: str
    public_key_sha256: str
    node_identity_hash: str
    algorithm: str = SIGNATURE_ALGORITHM
    status: str = "ACTIVE"

    def validate(self) -> None:
        _validate_identifier(self.node_id, "node_id")
        _validate_identifier(self.key_id, "key_id")
        _validate_public_key_hex(self.public_key_hex)
        _validate_hash(self.public_key_sha256, "public_key_sha256")
        _validate_hash(self.node_identity_hash, "node_identity_hash")
        if self.public_key_sha256 != sha256_bytes(bytes.fromhex(self.public_key_hex)):
            raise FederationError("federation_public_key_hash_mismatch")
        if self.node_identity_hash != self.public_key_sha256:
            raise FederationError("federation_identity_hash_not_bound_to_public_key")
        if self.algorithm != SIGNATURE_ALGORITHM:
            raise FederationError("federation_asymmetric_algorithm_not_allowlisted")
        if self.status not in {"ACTIVE", "RETIRED", "REVOKED"}:
            raise FederationError("federation_key_status_invalid")


@dataclass(frozen=True)
class RustCngSigner:
    """Adapter for the rebuilt Rust PyO3 CNG API; fails if the API is stale."""

    rust_module: Any
    node_id: str
    protected_private_key_hex: str
    algorithm: str = SIGNATURE_ALGORITHM
    asymmetric: bool = True

    def __call__(self, message: bytes) -> str:
        function = getattr(self.rust_module, "federation_sign_protected", None)
        if function is None:
            raise FederationError("federation_rust_module_missing_sign_api")
        return str(function(self.node_id, self.protected_private_key_hex, message))


@dataclass(frozen=True)
class RustCngVerifier:
    """Adapter for the rebuilt Rust PyO3 CNG verification API."""

    rust_module: Any
    algorithm: str = SIGNATURE_ALGORITHM
    asymmetric: bool = True

    def __call__(self, message: bytes, public_key_hex: str, signature_hex: str) -> bool:
        function = getattr(self.rust_module, "federation_verify", None)
        if function is None:
            raise FederationError("federation_rust_module_missing_verify_api")
        return bool(function(public_key_hex, message, signature_hex))


def build_signed_attestation(
    payload: Mapping[str, Any],
    *,
    node_id: str,
    key_id: str,
    public_key_sha256: str,
    signer: Callable[[bytes], str],
    sequence: int,
    nonce: str,
    federation_contract_path: Path = DEFAULT_FEDERATION_CONTRACT,
    telemetry_contract_path: Path = DEFAULT_TELEMETRY_CONTRACT,
) -> dict[str, Any]:
    """Build one signed, content-minimized attestation without sending it."""
    _require_asymmetric_backend(signer, "signer")
    federation_contract, telemetry_contract, _, telemetry_hash = _contract_hashes(
        federation_contract_path, telemetry_contract_path
    )
    validate_telemetry(payload, telemetry_contract)
    _validate_identifier(node_id, "node_id")
    _validate_identifier(key_id, "key_id")
    _validate_hash(public_key_sha256, "public_key_sha256")
    if payload.get("node_id") != node_id:
        raise FederationError("federation_payload_node_mismatch")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise FederationError("federation_sequence_invalid")
    if not isinstance(nonce, str) or len(nonce) < 32 or len(nonce) > 256 or HEX_RE.fullmatch(nonce) is None:
        raise FederationError("federation_nonce_invalid")
    payload_hash = sha256_bytes(_canonical(payload))
    envelope = {
        "federation_schema_version": str(federation_contract["schema_version"]),
        "federation_contract_id": str(federation_contract["contract_id"]),
        "telemetry_contract_sha256": telemetry_hash,
        "node_id": node_id,
        "key_id": key_id,
        "public_key_sha256": public_key_sha256,
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "sequence": sequence,
        "nonce": nonce,
        "payload_sha256": payload_hash,
        "payload": dict(payload),
    }
    signature = signer(_canonical(_attestation_body(envelope)))
    _validate_signature(signature)
    envelope["signature"] = signature.upper()
    if len(_canonical(envelope)) > MAX_ENVELOPE_BYTES:
        raise FederationError("federation_envelope_too_large")
    return envelope


class MasterFederationRegistry:
    """In-process Master trust registry and offline admission gate."""

    def __init__(
        self,
        *,
        federation_contract_path: Path = DEFAULT_FEDERATION_CONTRACT,
        telemetry_contract_path: Path = DEFAULT_TELEMETRY_CONTRACT,
    ) -> None:
        (
            self.federation_contract,
            self.telemetry_contract,
            self.federation_contract_sha256,
            self.telemetry_contract_sha256,
        ) = _contract_hashes(federation_contract_path, telemetry_contract_path)
        self.federation_contract_path = federation_contract_path
        self.telemetry_contract_path = telemetry_contract_path
        self._keys: dict[tuple[str, str], NodeKeyRecord] = {}
        self._active_key: dict[str, str] = {}
        self._node_revoked: set[str] = set()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._nonces: set[tuple[str, str, str]] = set()
        self._revocation_epoch = 0

    def register_node(self, record: NodeKeyRecord) -> None:
        record.validate()
        key = (record.node_id, record.key_id)
        if key in self._keys:
            raise FederationError("federation_key_already_registered")
        if record.node_id in self._node_revoked:
            raise FederationError("federation_node_revoked")
        if record.status != "ACTIVE":
            raise FederationError("federation_initial_key_must_be_active")
        if record.node_id in self._active_key:
            raise FederationError("federation_active_key_already_exists_use_rotation")
        self._keys[key] = record
        self._active_key[record.node_id] = record.key_id

    def revoke_node(self, node_id: str, reason: str) -> dict[str, Any]:
        _validate_identifier(node_id, "node_id")
        if not isinstance(reason, str) or not reason or len(reason) > 256:
            raise FederationError("federation_revocation_reason_invalid")
        if node_id not in self._active_key:
            raise FederationError("federation_node_registration_missing")
        for key, record in tuple(self._keys.items()):
            if key[0] == node_id:
                self._keys[key] = replace(record, status="REVOKED")
        self._node_revoked.add(node_id)
        self._active_key.pop(node_id, None)
        self._revocation_epoch += 1
        return {
            "revoked": True,
            "node_id": node_id,
            "reason_sha256": sha256_bytes(reason.encode("utf-8")),
            "revocation_epoch": self._revocation_epoch,
            "raw_reason_persisted": False,
        }

    def rotate_node_key(
        self,
        node_id: str,
        old_key_id: str,
        new_record: NodeKeyRecord,
        rotation_signature: str,
        verifier: Callable[[bytes, str, str], bool],
    ) -> dict[str, Any]:
        """Accept a key rotation only when the current key signs the change."""
        _require_asymmetric_backend(verifier, "verifier")
        _validate_identifier(node_id, "node_id")
        _validate_identifier(old_key_id, "old_key_id")
        new_record.validate()
        if new_record.node_id != node_id or new_record.key_id == old_key_id:
            raise FederationError("federation_rotation_identity_invalid")
        if self._active_key.get(node_id) != old_key_id:
            raise FederationError("federation_rotation_old_key_not_active")
        old_record = self._keys.get((node_id, old_key_id))
        if old_record is None or old_record.status != "ACTIVE":
            raise FederationError("federation_rotation_old_key_missing")
        _validate_signature(rotation_signature)
        body = {
            "federation_schema_version": str(self.federation_contract["schema_version"]),
            "federation_contract_id": str(self.federation_contract["contract_id"]),
            "node_id": node_id,
            "old_key_id": old_key_id,
            "new_key_id": new_record.key_id,
            "new_public_key_sha256": new_record.public_key_sha256,
            "new_node_identity_hash": new_record.node_identity_hash,
            "signature_algorithm": SIGNATURE_ALGORITHM,
        }
        try:
            valid = bool(verifier(_canonical(body), old_record.public_key_hex, rotation_signature))
        except Exception as exc:  # pragma: no cover - defensive backend boundary
            raise FederationError("federation_rotation_verifier_error") from exc
        if not valid:
            raise FederationError("federation_rotation_signature_invalid")
        key = (new_record.node_id, new_record.key_id)
        if key in self._keys:
            raise FederationError("federation_rotation_new_key_already_registered")
        self._keys[(node_id, old_key_id)] = replace(old_record, status="RETIRED")
        self._keys[key] = new_record
        self._active_key[node_id] = new_record.key_id
        return {
            "rotated": True,
            "node_id": node_id,
            "old_key_id": old_key_id,
            "new_key_id": new_record.key_id,
            "signature_verified": True,
            "raw_rotation_payload_persisted": False,
        }

    def admit(
        self,
        envelope: Mapping[str, Any],
        verifier: Callable[[bytes, str, str], bool],
    ) -> dict[str, Any]:
        """Return an aggregate receipt only; never return or persist payload."""
        try:
            _require_asymmetric_backend(verifier, "verifier")
        except FederationError as exc:
            return {"accepted": False, "reason_code": str(exc), "raw_payload_persisted": False}
        try:
            return self._admit(envelope, verifier)
        except (FederationError, TelemetryContractError) as exc:
            return {"accepted": False, "reason_code": str(exc), "raw_payload_persisted": False}

    def _admit(
        self,
        envelope: Mapping[str, Any],
        verifier: Callable[[bytes, str, str], bool],
    ) -> dict[str, Any]:
        if not isinstance(envelope, Mapping):
            raise FederationError("federation_envelope_must_be_object")
        if len(_canonical(envelope)) > MAX_ENVELOPE_BYTES:
            raise FederationError("federation_envelope_too_large")
        expected_keys = {
            "federation_schema_version",
            "federation_contract_id",
            "telemetry_contract_sha256",
            "node_id",
            "key_id",
            "public_key_sha256",
            "signature_algorithm",
            "sequence",
            "nonce",
            "payload_sha256",
            "payload",
            "signature",
        }
        if set(envelope) != expected_keys:
            raise FederationError("federation_wrapper_fields_mismatch")
        if envelope["federation_schema_version"] != self.federation_contract["schema_version"]:
            raise FederationError("federation_schema_mismatch")
        if envelope["federation_contract_id"] != self.federation_contract["contract_id"]:
            raise FederationError("federation_contract_id_mismatch")
        if envelope["telemetry_contract_sha256"] != self.telemetry_contract_sha256:
            raise FederationError("federation_telemetry_contract_hash_mismatch")
        node_id = envelope["node_id"]
        key_id = envelope["key_id"]
        registration = self._keys.get((node_id, key_id))
        if registration is None:
            raise FederationError("federation_key_registration_missing")
        if node_id in self._node_revoked or registration.status != "ACTIVE":
            raise FederationError("federation_node_or_key_not_active")
        if envelope["public_key_sha256"] != registration.public_key_sha256:
            raise FederationError("federation_public_key_binding_mismatch")
        if envelope["signature_algorithm"] != SIGNATURE_ALGORITHM:
            raise FederationError("federation_signature_algorithm_mismatch")
        payload = envelope["payload"]
        if not isinstance(payload, Mapping) or payload.get("node_id") != node_id:
            raise FederationError("federation_payload_node_mismatch")
        if sha256_bytes(_canonical(payload)) != envelope["payload_sha256"]:
            raise FederationError("federation_payload_hash_mismatch")
        _validate_signature(envelope["signature"])
        try:
            signature_valid = bool(
                verifier(_canonical(_attestation_body(envelope)), registration.public_key_hex, envelope["signature"])
            )
        except Exception as exc:  # pragma: no cover - defensive backend boundary
            raise FederationError("federation_asymmetric_backend_error") from exc
        if not signature_valid:
            raise FederationError("federation_asymmetric_signature_invalid")
        validate_telemetry(payload, self.telemetry_contract)
        if payload["identity_attestation"]["node_identity_hash"] != registration.node_identity_hash:
            raise FederationError("federation_node_identity_binding_mismatch")
        if payload["node_state"] in {"revoked", "offline"}:
            raise FederationError("federation_node_state_not_admissible")
        sequence = envelope["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise FederationError("federation_sequence_invalid")
        replay_key = (node_id, key_id)
        if sequence <= self._last_sequence.get(replay_key, -1):
            raise FederationError("federation_sequence_replay")
        nonce = envelope["nonce"]
        nonce_key = (node_id, key_id, str(nonce))
        if nonce_key in self._nonces:
            raise FederationError("federation_nonce_replay")
        self._last_sequence[replay_key] = sequence
        self._nonces.add(nonce_key)
        return {
            "accepted": True,
            "reason_code": "federation_telemetry_admitted",
            "node_id": node_id,
            "key_id": key_id,
            "sequence": sequence,
            "payload_sha256": envelope["payload_sha256"],
            "telemetry_contract_sha256": envelope["telemetry_contract_sha256"],
            "federation_contract_sha256": self.federation_contract_sha256,
            "signature_algorithm": SIGNATURE_ALGORITHM,
            "signature_verified": True,
            "asymmetric_signature": True,
            "raw_payload_persisted": False,
        }

    def snapshot(self) -> dict[str, Any]:
        """Return registry metadata without private keys or telemetry content."""
        return {
            "federation_contract_sha256": self.federation_contract_sha256,
            "telemetry_contract_sha256": self.telemetry_contract_sha256,
            "nodes": [
                {
                    "node_id": node_id,
                    "key_id": key_id,
                    "public_key_sha256": record.public_key_sha256,
                    "node_identity_hash": record.node_identity_hash,
                    "algorithm": record.algorithm,
                    "status": record.status,
                    "active": self._active_key.get(node_id) == key_id,
                }
                for (node_id, key_id), record in sorted(self._keys.items())
            ],
            "revocation_epoch": self._revocation_epoch,
            "raw_private_keys_present": False,
            "raw_payload_persisted": False,
            "network_socket_enabled": False,
            "network_write_authorized": False,
        }


__all__ = [
    "FederationError",
    "MasterFederationRegistry",
    "NodeKeyRecord",
    "RustCngSigner",
    "RustCngVerifier",
    "SIGNATURE_ALGORITHM",
    "build_signed_attestation",
    "load_federation_contract",
    "sha256_bytes",
    "sha256_file",
]
