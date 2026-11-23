"""One-session Viv-owned fixed loopback Master listener.

The listener is intentionally a bounded lifecycle component: it can bind only
to ``127.0.0.1:54443``, accepts one TLS 1.3 mutual-auth session, admits one
application-signed federation frame, sends an aggregate receipt, and closes.
It has no external destination, retry, reauthorization, daemon installation,
or persistent payload path.
"""
from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
import socket
import ssl
import struct
import threading
from typing import Any

from lib.node_federation import FederationError, MasterFederationRegistry, _require_asymmetric_backend
from lib.node_federation_tls_loopback import TlsLoopbackCertificatePaths


LOOPBACK_HOST = "127.0.0.1"
FIXED_LOOPBACK_PORT = 54443
TLS_VERSION = "TLSv1.3"
MAX_FRAME_BYTES = 65536
SOCKET_TIMEOUT_SECONDS = 5.0
FRAME_HEADER_BYTES = 4


class FixedLoopbackMasterListenerError(ValueError):
    """Raised when the fixed loopback listener is misconfigured or closed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest().upper()


def _subject_alt_names(certificate: Mapping[str, Any]) -> set[str]:
    return {
        str(value)
        for kind, value in certificate.get("subjectAltName", ())
        if kind in {"DNS", "IP Address", "URI"}
    }


def _receive_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("fixed_loopback_peer_closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _receive_frame(sock: ssl.SSLSocket) -> dict[str, Any]:
    header = _receive_exact(sock, FRAME_HEADER_BYTES)
    (size,) = struct.unpack("!I", header)
    if size <= 0 or size > MAX_FRAME_BYTES:
        raise FixedLoopbackMasterListenerError("fixed_loopback_frame_too_large")
    value = json.loads(_receive_exact(sock, size).decode("utf-8"))
    if not isinstance(value, dict):
        raise FixedLoopbackMasterListenerError("fixed_loopback_frame_must_be_object")
    return value


def _send_frame(sock: ssl.SSLSocket, value: Mapping[str, Any]) -> None:
    payload = _canonical(dict(value))
    if len(payload) > MAX_FRAME_BYTES:
        raise FixedLoopbackMasterListenerError("fixed_loopback_receipt_too_large")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


class VivFixedLoopbackMasterListener:
    """Serve exactly one signed federation frame on the governed loopback port."""

    def __init__(
        self,
        registry: MasterFederationRegistry,
        verifier: Any,
        certificate_paths: TlsLoopbackCertificatePaths,
        *,
        endpoint_id: str,
        host: str = LOOPBACK_HOST,
        port: int = FIXED_LOOPBACK_PORT,
        socket_timeout_seconds: float = SOCKET_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(registry, MasterFederationRegistry):
            raise FixedLoopbackMasterListenerError("fixed_loopback_requires_master_registry")
        try:
            _require_asymmetric_backend(verifier, "verifier")
        except FederationError as exc:
            raise FixedLoopbackMasterListenerError(str(exc)) from exc
        if not isinstance(certificate_paths, TlsLoopbackCertificatePaths):
            raise FixedLoopbackMasterListenerError("fixed_loopback_requires_certificate_paths")
        certificate_paths.validate()
        if endpoint_id != "viv-fixed-loopback-master-rehearsal-001":
            raise FixedLoopbackMasterListenerError("fixed_loopback_endpoint_id_not_allowlisted")
        if host != LOOPBACK_HOST:
            raise FixedLoopbackMasterListenerError("fixed_loopback_host_not_allowlisted")
        if isinstance(port, bool) or port != FIXED_LOOPBACK_PORT:
            raise FixedLoopbackMasterListenerError("fixed_loopback_port_not_allowlisted")
        if isinstance(socket_timeout_seconds, bool) or not isinstance(socket_timeout_seconds, (int, float)):
            raise FixedLoopbackMasterListenerError("fixed_loopback_socket_timeout_invalid")
        if socket_timeout_seconds <= 0 or socket_timeout_seconds > 30:
            raise FixedLoopbackMasterListenerError("fixed_loopback_socket_timeout_out_of_bounds")
        self._registry = registry
        self._verifier = verifier
        self._certificate_paths = certificate_paths
        self._endpoint_id = endpoint_id
        self._host = host
        self._port = port
        self._socket_timeout_seconds = float(socket_timeout_seconds)
        self._state = "CLOSED"
        self._started_once = False
        self._server_socket: socket.socket | None = None
        self._server_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._complete_event = threading.Event()
        self._lock = threading.RLock()
        self._server_tls_version: str | None = None
        self._client_certificate_verified = False
        self._application_frame_received = False
        self._application_frame_accepted = False
        self._peer_node_id: str | None = None
        self._last_failure: str | None = None
        self._last_failure_sha256: str | None = None

    def start(self) -> dict[str, Any]:
        """Bind the fixed loopback port and start the one-session server."""
        with self._lock:
            if self._started_once:
                return self._failure("fixed_loopback_reauthorization_denied")
            self._started_once = True
            self._stop_event.clear()
            self._complete_event.clear()
            try:
                server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                server_socket.settimeout(self._socket_timeout_seconds)
                server_socket.bind((self._host, self._port))
                server_socket.listen(1)
            except (OSError, ValueError) as exc:
                self._record_failure("fixed_loopback_listener_bind_failed", exc)
                try:
                    server_socket.close()
                except (UnboundLocalError, OSError):
                    pass
                self._state = "CLOSED"
                self._complete_event.set()
                return self._failure("fixed_loopback_listener_bind_failed")
            self._server_socket = server_socket
            self._state = "LISTENING"
            self._server_thread = threading.Thread(
                target=self._serve_once,
                name="viv-fixed-loopback-master-listener",
                daemon=True,
            )
            self._server_thread.start()
            return self._metadata("fixed_loopback_listener_started")

    def wait_for_completion(self, timeout: float = SOCKET_TIMEOUT_SECONDS + 2.0) -> dict[str, Any]:
        """Wait for the one-session lifecycle to close and return aggregate state."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise FixedLoopbackMasterListenerError("fixed_loopback_wait_timeout_invalid")
        self._complete_event.wait(float(timeout))
        thread = self._server_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=0.5)
        return self.snapshot()

    def close(self) -> None:
        """Close the listener and return to CLOSED without retrying."""
        with self._lock:
            self._stop_event.set()
            server_socket = self._server_socket
            server_thread = self._server_thread
            self._server_socket = None
            self._server_thread = None
            self._state = "CLOSED"
        if server_socket is not None:
            try:
                server_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                server_socket.close()
            except OSError:
                pass
        if server_thread is not None and server_thread is not threading.current_thread():
            server_thread.join(timeout=self._socket_timeout_seconds + 0.5)
        self._complete_event.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            active = self._state in {"LISTENING", "SERVING"}
            return {
                "state": self._state,
                "endpoint_id": self._endpoint_id,
                "host": self._host,
                "port": self._port,
                "tls_version": self._server_tls_version,
                "tls_handshake_verified": self._server_tls_version == TLS_VERSION,
                "client_certificate_verified": self._client_certificate_verified,
                "peer_node_id": self._peer_node_id,
                "listener_active": active,
                "local_loopback_only": self._host == LOOPBACK_HOST,
                "local_loopback_socket_enabled": active,
                "socket_closed": not active,
                "external_network_contacted": False,
                "network_write_authorized": False,
                "application_frame_received": self._application_frame_received,
                "application_frame_accepted": self._application_frame_accepted,
                "one_session_only": True,
                "persistent_listener_started": False,
                "automatic_retry": False,
                "automatic_reauthorization": False,
                "raw_payload_persisted": False,
                "last_failure": self._last_failure,
                "last_failure_sha256": self._last_failure_sha256,
            }

    def _serve_once(self) -> None:
        server_socket = self._server_socket
        if server_socket is None:
            self._complete_event.set()
            return
        try:
            raw_connection, remote = server_socket.accept()
            if remote[0] != LOOPBACK_HOST:
                raise FixedLoopbackMasterListenerError("fixed_loopback_peer_not_loopback")
            with self._lock:
                if self._stop_event.is_set():
                    return
                self._state = "SERVING"
            raw_connection.settimeout(self._socket_timeout_seconds)
            with self._server_context().wrap_socket(raw_connection, server_side=True) as tls_socket:
                self._server_tls_version = tls_socket.version()
                if self._server_tls_version != TLS_VERSION:
                    raise ssl.SSLError("fixed_loopback_tls_version_mismatch")
                peer_certificate = tls_socket.getpeercert()
                peer_names = _subject_alt_names(peer_certificate)
                node_names = [name.removeprefix("urn:viv:node:") for name in peer_names if name.startswith("urn:viv:node:")]
                if len(node_names) != 1 or not node_names[0]:
                    raise ssl.SSLError("fixed_loopback_client_identity_uri_san_missing")
                self._peer_node_id = node_names[0]
                self._client_certificate_verified = True
                frame = _receive_frame(tls_socket)
                self._application_frame_received = True
                if frame.get("node_id") != self._peer_node_id:
                    raise FixedLoopbackMasterListenerError("fixed_loopback_application_identity_mismatch")
                receipt = self._registry.admit(frame, self._verifier)
                receipt.pop("payload", None)
                _send_frame(tls_socket, receipt)
                self._application_frame_accepted = receipt.get("accepted") is True
        except (OSError, ssl.SSLError, ValueError, json.JSONDecodeError, ConnectionError) as exc:
            if not self._stop_event.is_set():
                self._record_failure("fixed_loopback_listener_session_failed", exc)
        finally:
            self._close_server_socket()
            with self._lock:
                self._state = "CLOSED"
            self._complete_event.set()

    def _close_server_socket(self) -> None:
        with self._lock:
            server_socket = self._server_socket
            self._server_socket = None
        if server_socket is not None:
            try:
                server_socket.close()
            except OSError:
                pass

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

    def _metadata(self, reason_code: str) -> dict[str, Any]:
        return {
            "accepted": reason_code == "fixed_loopback_listener_started",
            "reason_code": reason_code,
            "endpoint_id": self._endpoint_id,
            "host": self._host,
            "port": self._port,
            "local_loopback_only": self._host == LOOPBACK_HOST,
            "external_network_contacted": False,
            "network_write_authorized": False,
            "persistent_listener_started": False,
            "automatic_retry": False,
            "automatic_reauthorization": False,
        }

    def _failure(self, reason_code: str) -> dict[str, Any]:
        return self._metadata(reason_code)

    def _record_failure(self, reason_code: str, exc: BaseException | None) -> None:
        with self._lock:
            self._last_failure = reason_code
            if exc is not None:
                self._last_failure_sha256 = _hash_text(f"{type(exc).__name__}:{exc}")


__all__ = [
    "FIXED_LOOPBACK_PORT",
    "FixedLoopbackMasterListenerError",
    "LOOPBACK_HOST",
    "TLS_VERSION",
    "VivFixedLoopbackMasterListener",
]
