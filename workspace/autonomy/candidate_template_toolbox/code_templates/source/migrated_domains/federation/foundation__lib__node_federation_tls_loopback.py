"""Real TLS 1.3 mutual-auth loopback channel for federation testing.

This module is deliberately restricted to the local IPv4 loopback address. It
opens an ephemeral localhost socket only while a test session is active, uses
ephemeral certificate material supplied by the test, and closes every socket
before the channel returns to ``CLOSED``. It has no endpoint configuration,
allowlist, retry queue, or path to an external network destination.

The application envelope remains independently signed by the CNG-backed
federation signer. TLS proves the transport peer certificates and TLS version;
the Master registry still proves the application signature and replay policy.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import socket
import ssl
import struct
import threading
from typing import Any

from lib.node_federation import FederationError, MasterFederationRegistry, _require_asymmetric_backend
from lib.node_federation_transport import ChannelReceipt


TLS_LOOPBACK_MODE = "TLS_1_3_MUTUAL_AUTH_LOOPBACK"
TLS_VERSION = "TLSv1.3"
LOOPBACK_HOST = "127.0.0.1"
MAX_DEFAULT_FRAME_BYTES = 65536
MAX_DEFAULT_FRAMES_PER_SESSION = 256
MAX_DEFAULT_IN_FLIGHT = 2
SOCKET_TIMEOUT_SECONDS = 5.0
FRAME_HEADER_BYTES = 4


class TlsLoopbackTransportError(ValueError):
    """Raised when the closed local TLS loopback is misconfigured."""


@dataclass(frozen=True)
class TlsLoopbackCertificatePaths:
    """Certificate and private-key paths used only for one local test run."""

    ca_certificate: Path
    server_certificate: Path
    server_private_key: Path
    client_certificate: Path
    client_private_key: Path

    def validate(self) -> None:
        for name, path in (
            ("ca_certificate", self.ca_certificate),
            ("server_certificate", self.server_certificate),
            ("server_private_key", self.server_private_key),
            ("client_certificate", self.client_certificate),
            ("client_private_key", self.client_private_key),
        ):
            if not isinstance(path, Path) or not path.is_file():
                raise TlsLoopbackTransportError(f"tls_loopback_certificate_missing:{name}")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest().upper()


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("tls_loopback_peer_closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _send_frame(sock: socket.socket, payload: bytes, max_frame_bytes: int) -> None:
    if len(payload) > max_frame_bytes:
        raise ValueError("tls_loopback_frame_too_large")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def _receive_frame(sock: socket.socket, max_frame_bytes: int) -> dict[str, Any]:
    header = _receive_exact(sock, FRAME_HEADER_BYTES)
    (size,) = struct.unpack("!I", header)
    if size <= 0 or size > max_frame_bytes:
        raise ValueError("tls_loopback_frame_too_large")
    value = json.loads(_receive_exact(sock, size).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("tls_loopback_frame_must_be_object")
    return value


def _subject_alt_names(certificate: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for kind, value in certificate.get("subjectAltName", ())
        if kind in {"DNS", "IP Address", "URI"}
    }


class TlsMutualAuthLoopbackChannel:
    """A localhost-only TLS 1.3 mutual-auth channel implementing the client seam."""

    def __init__(
        self,
        registry: MasterFederationRegistry,
        verifier: Any,
        certificate_paths: TlsLoopbackCertificatePaths,
        *,
        max_frame_bytes: int = MAX_DEFAULT_FRAME_BYTES,
        max_frames_per_session: int = MAX_DEFAULT_FRAMES_PER_SESSION,
        max_in_flight_frames: int = MAX_DEFAULT_IN_FLIGHT,
    ) -> None:
        if not isinstance(registry, MasterFederationRegistry):
            raise TlsLoopbackTransportError("tls_loopback_requires_master_registry")
        try:
            _require_asymmetric_backend(verifier, "verifier")
        except FederationError as exc:
            raise TlsLoopbackTransportError(str(exc)) from exc
        if not isinstance(certificate_paths, TlsLoopbackCertificatePaths):
            raise TlsLoopbackTransportError("tls_loopback_requires_certificate_paths")
        certificate_paths.validate()
        if max_frame_bytes <= 0 or max_frame_bytes > MAX_DEFAULT_FRAME_BYTES:
            raise TlsLoopbackTransportError("tls_loopback_frame_budget_invalid")
        if max_frames_per_session <= 0 or max_frames_per_session > MAX_DEFAULT_FRAMES_PER_SESSION:
            raise TlsLoopbackTransportError("tls_loopback_session_frame_budget_invalid")
        if max_in_flight_frames <= 0 or max_in_flight_frames > MAX_DEFAULT_IN_FLIGHT:
            raise TlsLoopbackTransportError("tls_loopback_in_flight_budget_invalid")
        self._registry = registry
        self._verifier = verifier
        self._certificate_paths = certificate_paths
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
        self._server_error: str | None = None
        self._server_error_sha256: str | None = None
        self._server_tls_version: str | None = None
        self._client_tls_version: str | None = None
        self._server_certificate_verified = False
        self._client_certificate_verified = False
        self._server_socket: socket.socket | None = None
        self._client_tls_socket: ssl.SSLSocket | None = None
        self._server_thread: threading.Thread | None = None
        self._server_ready = threading.Event()
        self._stop_event = threading.Event()
        self._lock = threading.RLock()

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
        """Perform a real TLS 1.3 mutual-auth handshake on localhost only."""
        with self._lock:
            if self._state == "ACTIVE":
                return self._failure("tls_loopback_session_already_active")
            if self._state == "OPENING":
                return self._failure("tls_loopback_session_opening")
            if not isinstance(node_id, str) or not node_id:
                return self._failure("tls_loopback_node_id_invalid")
            if not isinstance(key_id, str) or not key_id:
                return self._failure("tls_loopback_key_id_invalid")
            if not isinstance(session_id, str) or not 32 <= len(session_id) <= 256:
                return self._failure("tls_loopback_session_id_invalid")
            if tls_version != TLS_VERSION:
                return self._failure("tls_loopback_tls_version_not_allowlisted")
            if mutual_auth_verified is not True:
                return self._failure("tls_loopback_mutual_authentication_required")
            if client_identity_verified is not True:
                return self._failure("tls_loopback_client_identity_policy_required")
            self._state = "OPENING"
            self._session_id = session_id
            self._node_id = node_id
            self._key_id = key_id
            self._frames_attempted = 0
            self._frames_accepted = 0
            self._last_failure = None
            self._server_error = None
            self._server_error_sha256 = None
            self._server_tls_version = None
            self._client_tls_version = None
            self._server_certificate_verified = False
            self._client_certificate_verified = False
            self._server_ready.clear()
            self._stop_event.clear()
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                server_socket.settimeout(SOCKET_TIMEOUT_SECONDS)
                server_socket.bind((LOOPBACK_HOST, 0))
                server_socket.listen(1)
                self._server_socket = server_socket
                self._server_thread = threading.Thread(
                    target=self._serve,
                    name="viv-tls-loopback-server",
                    daemon=True,
                )
                self._server_thread.start()
                port = int(server_socket.getsockname()[1])
            except (OSError, ValueError) as exc:
                self._record_failure("tls_loopback_listener_open_failed", exc)
                self.close()
                return self._failure("tls_loopback_listener_open_failed")

        client_raw: socket.socket | None = None
        client_tls: ssl.SSLSocket | None = None
        try:
            context = self._client_context()
            client_raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client_raw.settimeout(SOCKET_TIMEOUT_SECONDS)
            client_raw.connect((LOOPBACK_HOST, port))
            client_tls = context.wrap_socket(client_raw, server_hostname="localhost")
            client_raw = None
            self._client_tls_version = client_tls.version()
            if self._client_tls_version != TLS_VERSION:
                raise ssl.SSLError("tls_loopback_runtime_version_mismatch")
            peer_certificate = client_tls.getpeercert()
            peer_names = _subject_alt_names(peer_certificate)
            if not ({"localhost", LOOPBACK_HOST} & peer_names):
                raise ssl.SSLError("tls_loopback_server_identity_mismatch")
            server_ready = self._server_ready.wait(SOCKET_TIMEOUT_SECONDS)
            with self._lock:
                self._client_certificate_verified = server_ready and self._server_error is None
                if not server_ready:
                    raise ssl.SSLError(self._server_error or "tls_loopback_server_handshake_timeout")
                if self._server_error is not None:
                    raise ssl.SSLError(self._server_error)
                self._client_tls_socket = client_tls
                self._state = "ACTIVE"
            return self._metadata(accepted=True, reason_code="tls_loopback_mutual_auth_session_opened")
        except (OSError, ssl.SSLError, ValueError, json.JSONDecodeError) as exc:
            self._record_failure("tls_loopback_mutual_auth_handshake_failed", exc)
            if client_tls is not None:
                try:
                    client_tls.close()
                except OSError:
                    pass
            if client_raw is not None:
                try:
                    client_raw.close()
                except OSError:
                    pass
            self.close()
            return self._failure("tls_loopback_mutual_auth_handshake_failed")

    def transmit(self, envelope: Mapping[str, Any], *, in_flight_frames: int = 1) -> dict[str, Any]:
        """Send one signed envelope through the active local TLS session."""
        with self._lock:
            if self._state != "ACTIVE" or self._client_tls_socket is None:
                return self._failure("tls_loopback_session_closed")
            if not isinstance(envelope, Mapping):
                return self._failure("tls_loopback_frame_must_be_object")
            if isinstance(in_flight_frames, bool) or not isinstance(in_flight_frames, int) or in_flight_frames < 1:
                return self._failure("tls_loopback_in_flight_count_invalid")
            if in_flight_frames > self._max_in_flight_frames:
                return self._failure("tls_loopback_in_flight_budget_exceeded")
            try:
                frame = _canonical(dict(envelope))
            except (TypeError, ValueError):
                return self._failure("tls_loopback_frame_not_serializable")
            if len(frame) > self._max_frame_bytes:
                return self._failure("tls_loopback_frame_too_large")
            if self._frames_attempted >= self._max_frames_per_session:
                return self._failure("tls_loopback_session_frame_budget_exceeded")
            self._frames_attempted += 1
            try:
                _send_frame(self._client_tls_socket, frame, self._max_frame_bytes)
                receipt = _receive_frame(self._client_tls_socket, self._max_frame_bytes)
            except (OSError, ssl.SSLError, ValueError, json.JSONDecodeError) as exc:
                self._record_failure("tls_loopback_frame_exchange_failed", exc)
                self.close()
                return self._failure("tls_loopback_frame_exchange_failed")
            if receipt.get("accepted") is True:
                self._frames_accepted += 1
            receipt.pop("payload", None)
            return self._metadata(**receipt)

    def transmit_with_session(
        self,
        envelope: Mapping[str, Any],
        *,
        session_id: str,
        in_flight_frames: int = 1,
    ) -> dict[str, Any]:
        if session_id != self._session_id:
            return self._failure("tls_loopback_session_binding_failed")
        return self.transmit(envelope, in_flight_frames=in_flight_frames)

    def close(self) -> None:
        """Close both TLS and raw loopback sockets and return to CLOSED."""
        with self._lock:
            self._stop_event.set()
            client_tls = self._client_tls_socket
            server_socket = self._server_socket
            server_thread = self._server_thread
            self._client_tls_socket = None
            self._server_socket = None
            self._server_thread = None
            self._state = "CLOSED"
            self._session_id = None
            self._node_id = None
            self._key_id = None
        for sock in (client_tls, server_socket):
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if server_thread is not None and server_thread is not threading.current_thread():
            server_thread.join(timeout=SOCKET_TIMEOUT_SECONDS)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "state": self._state,
                "transport_mode": TLS_LOOPBACK_MODE,
                "tls_version": self._client_tls_version,
                "tls_handshake_verified": self._state == "ACTIVE",
                "server_certificate_verified": self._server_certificate_verified,
                "client_certificate_verified": self._client_certificate_verified,
                "session_bound": self._session_id is not None,
                "session_id_sha256": _hash_text(self._session_id) if self._session_id is not None else None,
                "node_id": self._node_id,
                "key_id": self._key_id,
                "frames_attempted": self._frames_attempted,
                "frames_accepted": self._frames_accepted,
                "max_frame_bytes": self._max_frame_bytes,
                "max_frames_per_session": self._max_frames_per_session,
                "max_in_flight_frames": self._max_in_flight_frames,
                "local_loopback_only": True,
                "local_loopback_socket_enabled": self._state == "ACTIVE",
                "external_endpoint_contacted": False,
                "network_socket_enabled": False,
                "network_write_authorized": False,
                "payload_retained": False,
                "raw_payload_persisted": False,
                "server_error": self._server_error,
                "server_error_sha256": self._server_error_sha256,
                "send_block_reason": None if self._state == "ACTIVE" else "tls_loopback_session_closed",
            }

    def _server_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_cert_chain(
            certfile=str(self._certificate_paths.server_certificate),
            keyfile=str(self._certificate_paths.server_private_key),
        )
        context.load_verify_locations(cafile=str(self._certificate_paths.ca_certificate))
        return context

    def _client_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.maximum_version = ssl.TLSVersion.TLSv1_3
        context.check_hostname = False
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=str(self._certificate_paths.ca_certificate))
        context.load_cert_chain(
            certfile=str(self._certificate_paths.client_certificate),
            keyfile=str(self._certificate_paths.client_private_key),
        )
        return context

    def _serve(self) -> None:
        server_socket = self._server_socket
        if server_socket is None:
            return
        try:
            raw_connection, _ = server_socket.accept()
            raw_connection.settimeout(SOCKET_TIMEOUT_SECONDS)
            with self._server_context().wrap_socket(raw_connection, server_side=True) as tls_socket:
                self._server_tls_version = tls_socket.version()
                if self._server_tls_version != TLS_VERSION:
                    raise ssl.SSLError("tls_loopback_server_runtime_version_mismatch")
                client_certificate = tls_socket.getpeercert()
                expected_identity = f"urn:viv:node:{self._node_id}"
                if expected_identity not in _subject_alt_names(client_certificate):
                    raise ssl.SSLError("tls_loopback_client_identity_certificate_mismatch")
                self._server_certificate_verified = True
                self._client_certificate_verified = True
                self._server_ready.set()
                while not self._stop_event.is_set():
                    try:
                        envelope = _receive_frame(tls_socket, self._max_frame_bytes)
                    except socket.timeout:
                        continue
                    except (ConnectionError, OSError, ssl.SSLError):
                        if not self._stop_event.is_set():
                            self._record_failure("tls_loopback_peer_closed", None)
                        break
                    except (ValueError, json.JSONDecodeError) as exc:
                        self._record_failure("tls_loopback_invalid_frame", exc)
                        break
                    receipt = self._registry.admit(envelope, self._verifier)
                    receipt.pop("payload", None)
                    _send_frame(
                        tls_socket,
                        _canonical(self._metadata(**receipt)),
                        self._max_frame_bytes,
                    )
        except (OSError, ssl.SSLError, ValueError) as exc:
            if not self._stop_event.is_set():
                self._record_failure("tls_loopback_server_handshake_failed", exc)
        finally:
            self._server_ready.set()

    def _metadata(self, *, accepted: bool, reason_code: str, **values: Any) -> dict[str, Any]:
        output = {
            "accepted": accepted,
            "reason_code": reason_code,
            "channel_mode": TLS_LOOPBACK_MODE,
            "transport_mode": TLS_LOOPBACK_MODE,
            "tls_version": self._client_tls_version or self._server_tls_version,
            "tls_handshake_verified": self._client_tls_version == TLS_VERSION
            and self._server_tls_version == TLS_VERSION,
            "server_certificate_verified": self._server_certificate_verified,
            "client_certificate_verified": self._client_certificate_verified,
            "session_bound": self._session_id is not None,
            "local_loopback_only": True,
            "local_loopback_socket_enabled": self._state == "ACTIVE",
            "external_endpoint_contacted": False,
            "network_socket_enabled": False,
            "network_write_authorized": False,
            "raw_payload_persisted": False,
        }
        output.update(values)
        output.pop("payload", None)
        return output

    def _failure(self, reason_code: str) -> dict[str, Any]:
        return self._metadata(accepted=False, reason_code=reason_code)

    def _record_failure(self, reason_code: str, exc: BaseException | None) -> None:
        with self._lock:
            self._last_failure = reason_code
            self._server_error = reason_code
            if exc is not None:
                self._server_error_sha256 = _hash_text(f"{type(exc).__name__}:{exc}")


__all__ = [
    "LOOPBACK_HOST",
    "TLS_LOOPBACK_MODE",
    "TLS_VERSION",
    "TlsLoopbackCertificatePaths",
    "TlsLoopbackTransportError",
    "TlsMutualAuthLoopbackChannel",
]
