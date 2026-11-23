import unittest
from pathlib import Path

from privacy_core import PrivacyCore


class PrivacyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.core = PrivacyCore.__new__(PrivacyCore)
        self.allowed_root = Path(__file__).parent / "policy_sandbox"
        self.core.config = {
            "file_write_boundary": {
                "allowed_directories": [str(self.allowed_root)],
                "blocked_extensions": [".exe", ".bat"],
            },
            "egress_sovereignty": {
                "allowed_protocols": ["http", "https"],
                "blocked_ports": [80, 443],
            },
            "api_port_whitelist": {"allowed_ports": [5000, 8080, 11434]},
        }

    def test_file_write_requires_containment_and_safe_extension(self):
        allowed = self.core.authorize_file_write(self.allowed_root / "notes.txt")
        blocked_path = self.core.authorize_file_write(self.allowed_root.parent / "notes.txt")
        blocked_extension = self.core.authorize_file_write(self.allowed_root / "payload.EXE")

        self.assertTrue(allowed["allowed"])
        self.assertFalse(blocked_path["allowed"])
        self.assertFalse(blocked_extension["allowed"])

    def test_file_write_policy_mediates_the_actual_write(self):
        target = self.allowed_root / "nested" / "memory.json"
        result = self.core.write_text(target, '{"ok": true}')
        self.assertTrue(result["allowed"])
        self.assertEqual(target.read_text(encoding="utf-8"), '{"ok": true}')

        denied_target = self.allowed_root.parent / "outside.json"
        with self.assertRaisesRegex(PermissionError, "file_write_outside_allowed_roots"):
            self.core.write_text(denied_target, "must not exist")
        self.assertFalse(denied_target.exists())

    def test_file_write_policy_rejects_non_text_payload(self):
        with self.assertRaises(TypeError):
            self.core.write_text(self.allowed_root / "memory.json", b"not text")

    def test_egress_requires_protocol_and_nonblocked_allowlisted_port(self):
        self.assertTrue(self.core.authorize_egress("https", 8080)["allowed"])
        self.assertFalse(self.core.authorize_egress("https", 443)["allowed"])
        self.assertFalse(self.core.authorize_egress("ftp", 8080)["allowed"])
        self.assertFalse(self.core.authorize_egress("http", True)["allowed"])

    def test_policy_api_does_not_claim_process_wide_coverage(self):
        self.assertEqual(
            self.core.get_health_status()["status"],
            "unverified",
        )

    def test_egress_url_requires_loopback_and_an_allowlisted_port(self):
        self.assertTrue(
            self.core.authorize_egress_url("http://127.0.0.1:11434/api/chat")["allowed"]
        )
        self.assertTrue(
            self.core.authorize_egress_url("http://[::1]:11434/api/chat")["allowed"]
        )
        self.assertFalse(
            self.core.authorize_egress_url("http://example.com:11434/api/chat")["allowed"]
        )
        self.assertFalse(
            self.core.authorize_egress_url("http://127.0.0.1:11435/api/chat")["allowed"]
        )
        self.assertFalse(
            self.core.authorize_egress_url("http://user@127.0.0.1:11434/api/chat")["allowed"]
        )
        self.assertFalse(
            self.core.authorize_egress_url("http://@127.0.0.1:11434/api/chat")["allowed"]
        )


if __name__ == "__main__":
    unittest.main()
