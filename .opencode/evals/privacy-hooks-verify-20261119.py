"""Standalone verification of PrivacyCore process-wide hook layer (isolated process)."""
import json
import socket
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"L:\LocalCoder\workspace\aios_rebuild")
from privacy_core import PrivacyCore, install_process_wide_hooks

tmp = Path(tempfile.mkdtemp())
allowed = tmp / "allowed"
disallowed = tmp / "disallowed"
allowed.mkdir()
disallowed.mkdir()

config = {
    "mode": "semi-auto",
    "file_write_boundary": {
        "allowed_directories": [str(allowed)],
        "allowed_files": [],
        "blocked_extensions": [".exe", ".dll"],
    },
    "egress_sovereignty": {"allowed_protocols": ["http", "https"], "blocked_ports": [80, 443]},
    "api_port_whitelist": {"allowed_ports": [5000, 8080, 11434]},
}

cfg_path = tmp / "privacy_config.json"
cfg_path.write_text(json.dumps(config))

# Pre-install: honest defaults.
core = PrivacyCore(config_file=cfg_path)
pre = core.get_health_status()
assert pre["status"] == "unverified", pre
assert pre["file_write_authorizer_available"] is False, pre
assert pre["egress_authorizer_available"] is False, pre

# Seed a disallowed read file BEFORE hooks install.
(disallowed / "readme.txt").write_text("free to read")

# Install; idempotent.
assert install_process_wide_hooks(core) is True
assert install_process_wide_hooks(core) is False

post = core.get_health_status()
assert post["file_write_authorizer_available"] is True, post
assert post["egress_authorizer_available"] is True, post

# 1. allowed write via hooked open succeeds
with open(allowed / "ok.txt", "w") as f:
    f.write("hello")
assert (allowed / "ok.txt").read_text() == "hello"

# 2. blocked extension denied even inside allowed root
try:
    open(allowed / "payload.exe", "w")
    raise AssertionError("extension block not enforced")
except PermissionError as e:
    assert "file_write_blocked_extension" in str(e), e

# 3. write outside allowed roots denied
try:
    open(disallowed / "nope.txt", "w")
    raise AssertionError("root block not enforced")
except PermissionError as e:
    assert "file_write_outside_allowed_roots" in str(e), e

# 4. read outside roots is FREE (look is free)
assert (disallowed / "readme.txt").read_text() == "free to read"

# 5. sqlite connect: allowed path ok, disallowed path denied
conn = sqlite3.connect(str(allowed / "db.sqlite3"))
conn.close()
try:
    sqlite3.connect(str(disallowed / "db.sqlite3"))
    raise AssertionError("sqlite root block not enforced")
except PermissionError as e:
    assert "sqlite_write_denied" in str(e) or "file_write_outside_allowed_roots" in str(e), e

# 6. egress: non-loopback blocked at hook (no real network attempted)
try:
    s = socket.socket()
    s.connect(("8.8.8.8", 53))
    raise AssertionError("egress block not enforced")
except PermissionError as e:
    assert "egress_non_loopback_blocked" in str(e), e

# 7. loopback passes the hook (OS may refuse if no listener, but NOT our PermissionError)
try:
    s = socket.socket()
    s.connect(("127.0.0.1", 9))
except PermissionError as e:
    if "egress_non_loopback_blocked" in str(e):
        raise AssertionError("loopback was wrongly blocked")
except OSError:
    pass  # connection refused/timeout means the hook let it through to the OS

print("HOOK_VERIFY_PASS: file-write, sqlite, egress hooks all enforced; flags honest; read free")
