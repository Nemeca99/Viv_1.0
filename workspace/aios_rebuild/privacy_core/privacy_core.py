"""Privacy Core - deterministic policy mediation for AIOS.

Implements the frozen policy contract defined by privacy_config.json and
test_privacy_core.py, and the consumers main_core.main_core (get_health_status) and
main_core.mind_runtime_gate (authorize_egress_url).

Two mediation surfaces, both fail-closed:

1. file_write_boundary -- explicit allowlist of directories and exact files, plus a
   blocked-extension set. A write outside the allowlist is denied, not default-allowed.
2. egress_sovereignty  -- the Mind may reach loopback services only, on allowlisted
   ports, over allowed protocols, with no URL userinfo. No external network egress.

Authorizer availability vs process-wide coverage:
- The authorizers (authorize_file_write / authorize_egress) are "available" because the
  methods exist and are functional; get_health_status() reports their flags True.
- Process-wide coverage is a separate question. The Body container already confines I/O
  at the OS level (read-only root, network=none, bounded tmpfs), and the Rust Body
  verifies that boundary independently (container_io_boundary_verified). Python cannot
  prove process-wide coverage on its own, so status stays "unverified" and the Rust
  gate combines both signals to clear the HOLD. No monkeypatching is used: it is
  redundant inside an already-confined container and breaks reads/health checks.
"""

import json
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

_DEFAULT_BLOCKED_EXTENSIONS = [
    ".exe", ".dll", ".pyd", ".so", ".dylib", ".bat", ".ps1", ".sh",
]


class PrivacyCore:
    """Manage privacy policy and mediate file writes and network egress."""

    def __init__(self, config_file: str | Path | None = None):
        self.config_file = Path(config_file) if config_file else (
            Path(__file__).parent / "privacy_config.json"
        )
        self.config = self._load_config()
        self.mode = self.config.get("mode", "semi-auto")

    # --- config -------------------------------------------------------------

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    def _save_config(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)

    # --- learning mode (backward-compatible surface) ------------------------

    def get_mode(self) -> str:
        return self.mode

    def set_semi_auto(self) -> None:
        self.mode = "semi-auto"
        self.config["mode"] = self.mode
        self._save_config()

    def set_full_auto(self) -> None:
        self.mode = "full-auto"
        self.config["mode"] = self.mode
        self._save_config()

    def enable_full_auto(self, confirmed: bool = True) -> None:
        if confirmed:
            self.set_full_auto()

    def get_status(self) -> Dict[str, Any]:
        return {"mode": self.mode}

    # --- file-write boundary -------------------------------------------------

    def authorize_file_write(self, file_path) -> Dict[str, Any]:
        """Decide whether a single file write is allowed. Fail-closed."""
        try:
            resolved = Path(file_path).resolve()
        except Exception:
            return {"allowed": False, "reason": "file_write_path_unresolvable"}

        boundary = self.config.get("file_write_boundary", {})
        blocked_extensions = {
            ext.lower() for ext in boundary.get(
                "blocked_extensions", _DEFAULT_BLOCKED_EXTENSIONS
            )
        }
        if resolved.suffix.lower() in blocked_extensions:
            return {
                "allowed": False,
                "reason": "file_write_blocked_extension:%s" % resolved.suffix.lower(),
            }

        for allowed_file in boundary.get("allowed_files", []):
            try:
                if resolved == Path(allowed_file).resolve():
                    return {"allowed": True, "reason": ""}
            except Exception:
                continue

        for allowed_dir in boundary.get("allowed_directories", []):
            try:
                allowed_resolved = Path(allowed_dir).resolve()
                if resolved == allowed_resolved or allowed_resolved in resolved.parents:
                    return {"allowed": True, "reason": ""}
            except Exception:
                continue

        return {"allowed": False, "reason": "file_write_outside_allowed_roots"}

    def write_text(self, file_path, content, encoding: str = "utf-8") -> Dict[str, Any]:
        """Authorize and perform a text write. Raises on denial or non-text payload."""
        if not isinstance(content, str):
            raise TypeError("file_write_policy_rejects_non_text_payload")
        auth = self.authorize_file_write(file_path)
        if not auth.get("allowed"):
            raise PermissionError(auth.get("reason", "file_write_denied"))
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=encoding)
        return {"allowed": True, "reason": ""}

    # --- egress sovereignty ---------------------------------------------------

    def authorize_egress(self, protocol, port) -> Dict[str, Any]:
        """Decide whether a protocol+port egress is allowed. Fail-closed."""
        egress = self.config.get("egress_sovereignty", {})
        allowed_protocols = egress.get("allowed_protocols", ["http", "https"])
        blocked_ports = egress.get("blocked_ports", [])
        whitelist = self.config.get("api_port_whitelist", {}).get("allowed_ports", [])

        if protocol not in allowed_protocols:
            return {"allowed": False, "reason": "egress_protocol_not_allowed"}
        if isinstance(port, bool) or not isinstance(port, int):
            return {"allowed": False, "reason": "egress_port_not_integer"}
        if port in blocked_ports:
            return {"allowed": False, "reason": "egress_port_blocked"}
        if port not in whitelist:
            return {"allowed": False, "reason": "egress_port_not_allowlisted"}
        return {"allowed": True, "reason": ""}

    def authorize_egress_url(self, url) -> Dict[str, Any]:
        """Decide whether a full URL egress is allowed. Loopback + allowlisted port only."""
        try:
            parsed = urlparse(url)
        except Exception:
            return {"allowed": False, "reason": "egress_url_unparseable"}

        if "@" in parsed.netloc:
            return {"allowed": False, "reason": "egress_url_userinfo_rejected"}

        protocol = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        port = parsed.port

        if host not in _LOOPBACK_HOSTS:
            return {"allowed": False, "reason": "egress_url_non_loopback_host"}
        if port is None:
            return {"allowed": False, "reason": "egress_url_port_missing"}
        return self.authorize_egress(protocol, port)

    # --- health ---------------------------------------------------------------

    def get_health_status(self) -> Dict[str, Any]:
        """Honest health report read by the Rust Body gate.

        status stays "unverified": Python cannot prove process-wide I/O coverage on its
        own. The authorizer-available flags report that the mediation methods exist and
        are functional (True); the Rust Body combines that with its own independent
        container-boundary verification before clearing the HOLD.
        """
        return {
            "status": "unverified",
            "reason": "authorization_calls_not_proven_to_cover_process_io",
            "file_write_authorizer_available": True,
            "egress_authorizer_available": True,
            "mode": getattr(self, "mode", self.config.get("mode", "semi-auto")),
        }
