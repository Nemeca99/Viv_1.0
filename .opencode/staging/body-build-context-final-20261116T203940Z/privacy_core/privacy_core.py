import json
import ipaddress
import time
from pathlib import Path
from urllib.parse import urlsplit


class PrivacyCore:
    def __init__(self):
        self.config = self._load_config()
        self.status = {
            "egress_sovereignty": "unverified",
            "file_write_boundary": "unverified",
            "api_port_whitelist": "unverified",
            "health": "unverified",
        }

    def _load_config(self):
        config_path = Path(__file__).with_name("privacy_config.json")
        if not config_path.exists():
            return {
                "egress_sovereignty": {
                    "allowed_protocols": ["http", "https"],
                    "blocked_ports": [80, 443],
                },
                "file_write_boundary": {
                    "allowed_directories": [
                        str(Path.home() / "Documents"),
                        str(Path.home() / "Downloads"),
                    ],
                    "blocked_extensions": [".exe", ".dll", ".pyd", ".so", ".dylib", ".bat", ".ps1", ".sh"],
                },
                "api_port_whitelist": {"allowed_ports": [8080, 5000]},
            }
        with config_path.open("r", encoding="utf-8") as config_file:
            return json.load(config_file)

    def authorize_file_write(self, file_path):
        try:
            raw_target = Path(file_path).expanduser()
            if ".." in raw_target.parts:
                return {"allowed": False, "reason": "file_write_traversal_denied"}
            target = raw_target.resolve(strict=False)
            boundary = self.config["file_write_boundary"]
            allowed_roots = [
                Path(value).expanduser().resolve(strict=False)
                for value in boundary["allowed_directories"]
            ]
            allowed_files = {
                Path(value).expanduser().resolve(strict=False)
                for value in boundary.get("allowed_files", [])
            }
            blocked_extensions = {
                str(value).casefold() for value in boundary["blocked_extensions"]
            }
        except (KeyError, TypeError, ValueError, OSError):
            return {"allowed": False, "reason": "file_write_policy_invalid"}

        contained = target in allowed_files
        for root in allowed_roots:
            try:
                target.relative_to(root)
                contained = target != root
                if contained:
                    break
            except ValueError:
                continue
        if not contained:
            return {"allowed": False, "reason": "file_write_outside_allowed_roots"}
        if target.suffix.casefold() in blocked_extensions:
            return {"allowed": False, "reason": "file_extension_blocked"}
        return {"allowed": True, "reason": "file_write_policy_passed"}

    def write_text(self, file_path, content, *, encoding="utf-8"):
        if not isinstance(content, str):
            raise TypeError("PrivacyCore text writes require a string payload")
        decision = self.authorize_file_write(file_path)
        if decision.get("allowed") is not True:
            reason = decision.get("reason", "file_write_denied")
            raise PermissionError(f"AIOS PrivacyCore denied file write: {reason}")
        target = Path(file_path).expanduser().resolve(strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding=encoding) as stream:
            stream.write(content)
        return {"allowed": True, "reason": "file_write_performed", "path": str(target)}

    def authorize_egress(self, protocol, port):
        if not isinstance(protocol, str) or not isinstance(port, int) or isinstance(port, bool):
            return {"allowed": False, "reason": "egress_request_invalid"}
        if not 1 <= port <= 65535:
            return {"allowed": False, "reason": "egress_port_invalid"}
        try:
            policy = self.config["egress_sovereignty"]
            allowed_protocols = {
                str(value).casefold() for value in policy["allowed_protocols"]
            }
            blocked_ports = set(policy["blocked_ports"])
            allowed_ports = set(self.config["api_port_whitelist"]["allowed_ports"])
        except (KeyError, TypeError):
            return {"allowed": False, "reason": "egress_policy_invalid"}

        normalized_protocol = protocol.casefold()
        if normalized_protocol not in allowed_protocols:
            return {"allowed": False, "reason": "egress_protocol_not_allowlisted"}
        if port in blocked_ports:
            return {"allowed": False, "reason": "egress_port_blocked"}
        if port not in allowed_ports:
            return {"allowed": False, "reason": "egress_port_not_allowlisted"}
        return {"allowed": True, "reason": "egress_policy_passed"}

    def authorize_egress_url(self, endpoint):
        if not isinstance(endpoint, str):
            return {"allowed": False, "reason": "egress_endpoint_invalid"}
        try:
            parsed = urlsplit(endpoint)
            hostname = parsed.hostname
            port = parsed.port
            if (parsed.scheme.casefold() not in {"http", "https"}
                    or not hostname or parsed.username is not None
                    or parsed.password is not None):
                return {"allowed": False, "reason": "egress_endpoint_invalid"}
            if hostname.casefold() == "localhost":
                is_loopback = True
            else:
                try:
                    is_loopback = ipaddress.ip_address(hostname).is_loopback
                except ValueError:
                    is_loopback = False
            if not is_loopback:
                return {"allowed": False, "reason": "egress_endpoint_not_loopback"}
            effective_port = port or (443 if parsed.scheme.casefold() == "https" else 80)
        except (ValueError, TypeError):
            return {"allowed": False, "reason": "egress_endpoint_invalid"}
        return self.authorize_egress(parsed.scheme, effective_port)

    def get_health_status(self):
        return {
            "status": "unverified",
            "reason": "authorization_calls_not_proven_to_cover_process_io",
            "file_write_authorizer_available": callable(self.authorize_file_write),
            "egress_authorizer_available": callable(self.authorize_egress),
        }

    def _report_health(self):
        report = self.get_health_status()
        self.status["health"] = report["status"]
        return report

    def run(self):
        while True:
            print(json.dumps(self._report_health(), indent=2))
            time.sleep(10)


if __name__ == "__main__":
    core = PrivacyCore()
    core.run()
